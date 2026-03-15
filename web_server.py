import asyncio
import time
import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

from astrbot.api import logger


class WebServer:
    """Embedded WebUI server for Screen Companion."""

    CLIENT_MAX_SIZE = 50 * 1024 * 1024
    SESSION_CLEANUP_INTERVAL = 300
    SESSION_MAX_COUNT = 1000
    START_RETRY_COUNT = 3
    START_RETRY_DELAY = 0.5

    def __init__(self, plugin: Any, host: str = "0.0.0.0", port: int = 6314):
        self.plugin = plugin
        self.host: str = host
        self.port: int = self._normalize_port(port)
        self.app: web.Application = web.Application(
            client_max_size=self.CLIENT_MAX_SIZE,
            middlewares=[self._error_middleware, self._auth_middleware],
        )
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._started: bool = False

        # Web UI 静态文件目录(插件目录下的 web 文件夾)
        self.static_dir: Path = Path(__file__).resolve().parent / "web"

        # 数据目录
        self.data_dir: Path = self.plugin.diary_storage

        self._cookie_name: str = "screen_companion_webui_session"
        self._sessions: dict[str, float] = {}
        self._last_session_cleanup: float = 0.0  # 上次 session 清理时间
        self._session_cleanup_interval: int = self.SESSION_CLEANUP_INTERVAL

        self._setup_routes()

    @staticmethod
    def _normalize_port(port: Any) -> int:
        try:
            normalized = int(port)
        except Exception:
            normalized = 6314

        if normalized < 1 or normalized > 65535:
            logger.warning(f"WebUI 端口 {port} 不在有效范围内，已回退到 6314")
            return 6314
        elif normalized < 1024:
            logger.warning(f"WebUI 端口 {port} 是系统保留端口，可能需要管理员权限")
        return normalized

    # === 响应辅助方法 ====

    @staticmethod
    def _ok(data: dict | None = None, **kwargs) -> web.Response:
        """Return a success JSON response."""
        body: dict = {"success": True}
        if data:
            body.update(data)
        if kwargs:
            body.update(kwargs)
        # JSON响应默认使用UTF-8编码
        return web.json_response(body)

    @staticmethod
    def _err(msg: str, status: int = 500) -> web.Response:
        """Return an error JSON response."""
        return web.json_response({"success": False, "error": msg}, status=status)

    # === 中间件 ====

    async def _error_middleware(self, app: web.Application, handler):
        async def middleware_handler(request: web.Request):
            try:
                return await handler(request)
            except web.HTTPException:
                raise
            except Exception as e:
                logger.error(f"Unhandled WebUI error: {e}", exc_info=True)
                if (request.path or "").startswith("/api/"):
                    return WebServer._err("Internal Server Error")
                return web.Response(text="500 Internal Server Error", content_type="text/plain", charset="utf-8", status=500)

        return middleware_handler

    def _is_auth_enabled(self) -> bool:
        try:
            auth_enabled = self.plugin.plugin_config.webui.auth_enabled
            return bool(auth_enabled)
        except Exception:
            return True

    def _get_expected_secret(self) -> str:
        # 尝试从配置获取
        password = ""
        try:
            password = str(self.plugin.plugin_config.webui.password or "").strip()
        except Exception:
            password = ""

        # 如果密码为空，即使认证开关开启，也视为未启用认证
        if not password:
            return ""

        # 检查认证是否启用
        if not self._is_auth_enabled():
            return ""

        return password

    def _get_session_timeout(self) -> int:
        timeout = 3600
        # Try reading the timeout from config
        try:
            timeout = int(self.plugin.plugin_config.webui.session_timeout or 3600)
        except Exception:
            timeout = 3600

        if timeout <= 0:
            timeout = 3600
        return timeout

    async def _auth_middleware(self, app: web.Application, handler):
        async def middleware_handler(request: web.Request):
            if request.method == "OPTIONS":
                return await handler(request)

            path = request.path or "/"
            expected = self._get_expected_secret()
            
            # 检查是否是外部API调用
            if path in ("/api/analyze", "/api/analyze/base64"):
                if not self.plugin.webui_allow_external_api:
                    return WebServer._err("外部 API 未启用", 403)
                
                # 检查API密钥
                if expected:
                    # 从header获取API密钥
                    api_key = request.headers.get("X-API-Key", "")
                    if not api_key or api_key != expected:
                        return WebServer._err("Unauthorized", 401)
                return await handler(request)
            
            # 其他API需要认证
            if not expected:
                return await handler(request)

            if (
                path in ("/", "/index.html")
                or path.startswith("/web")
                or path in ("/auth/info", "/auth/login", "/auth/logout")
                or path == "/api/config"  # 允许无需认证访问基本配置信息
                or path.startswith("/api/runtime")  # 允许无需认证访问运行时信息
                or path == "/api/health"  # 允许无需认证访问健康检查
                or path == "/api/settings"  # 允许无需认证访问设置信息
                or path.startswith("/api/diaries")  # 允许无需认证访问日记列表
                or path.startswith("/api/diary/")  # 允许无需认证访问单日日记
                or path.startswith("/api/observations")  # 允许无需认证访问观察记录
                or path.startswith("/api/memories")  # 允许无需认证访问记忆
                or path.startswith("/api/windows")  # 允许无需认证访问窗口列表
                or path.startswith("/api/dashboard")  # 允许无需认证访问统计面板
            ):
                return await handler(request)

            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            now = time.time()

            # Periodically clean expired sessions
            if now - self._last_session_cleanup > self._session_cleanup_interval:
                expired = [k for k, v in self._sessions.items() if v < now]
                for k in expired:
                    self._sessions.pop(k, None)
                self._last_session_cleanup = now

                # Trim oldest sessions if the session pool grows too large
                if len(self._sessions) > self.SESSION_MAX_COUNT:
                    sorted_sessions = sorted(self._sessions.items(), key=lambda x: x[1])
                    to_remove = len(self._sessions) - self.SESSION_MAX_COUNT // 2
                    for k, _ in sorted_sessions[:to_remove]:
                        self._sessions.pop(k, None)
                    logger.warning(
                        f"Session 数量超过上限 {self.SESSION_MAX_COUNT}，已清理 {to_remove} 个最旧的 session"
                    )

            exp = self._sessions.get(sid)
            if not exp or exp < now:
                if sid:
                    self._sessions.pop(sid, None)
                if path.startswith("/api/"):
                    return WebServer._err("Unauthorized", 401)
                raise web.HTTPUnauthorized(text="Unauthorized")

            return await handler(request)

        return middleware_handler

    def _setup_routes(self):
        # API 路由
        self.app.router.add_get("/api/diaries", self.handle_list_diaries)
        self.app.router.add_get("/api/diary/{date}", self.handle_get_diary)
        self.app.router.add_get("/api/observations", self.handle_list_observations)
        self.app.router.add_delete("/api/observations/{index}", self.handle_delete_observation)
        self.app.router.add_delete("/api/observations/batch", self.handle_batch_delete_observations)
        self.app.router.add_post("/api/data/clear", self.handle_clear_all_data)
        self.app.router.add_get("/api/memories", self.handle_list_memories)
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_get("/api/settings", self.handle_get_settings)
        self.app.router.add_post("/api/settings", self.handle_update_settings)
        self.app.router.add_get("/api/health", self.handle_health_check)
        self.app.router.add_get("/api/runtime", self.handle_get_runtime_status)
        self.app.router.add_post("/api/runtime/config", self.handle_update_runtime_config)
        self.app.router.add_post("/api/runtime/stop", self.handle_stop_runtime_tasks)
        self.app.router.add_get("/api/windows", self.handle_list_windows)
        self.app.router.add_get("/api/activity", self.handle_get_activity_stats)
        self.app.router.add_get("/api/dashboard", self.handle_get_dashboard_stats)
        self.app.router.add_get("/api/media/latest/{kind}", self.handle_get_latest_media)
        
        # 外部图片分析API
        self.app.router.add_post("/api/analyze", self.handle_analyze_image)
        self.app.router.add_post("/api/analyze/base64", self.handle_analyze_image_base64)
        
        # 认证相关
        self.app.router.add_get("/auth/info", self.handle_auth_info)
        self.app.router.add_post("/auth/login", self.handle_auth_login)
        self.app.router.add_post("/auth/logout", self.handle_auth_logout)

        # 静态文件路由
        # 1. 首页入口
        self.app.router.add_get("/", self.handle_index)
        # 某些客户端或代理在 FileResponse 异常时会误报 "HTTP/0.9"，这里显式提供入口便于排查
        self.app.router.add_get("/index.html", self.handle_index)

        # 2. 静态资源
        # 交给 aiohttp 原生静态托管，避免 Windows 下手写路径校验导致误判
        self.app.router.add_static("/web/", path=str(self.static_dir), show_index=False)

    def _resolve_safe_path(
        self, raw: str, base_dir: Path
    ) -> tuple[Path | None, str | None]:
        """将请求路径安全映射到指定基础目录。"""
        raw = str(raw or "").lstrip("/")
        if not raw:
            return None, "not_found"

        if (
            ".." in raw
            or raw.startswith(("/", "\\"))
            or ":" in raw
            or "\x00" in raw
        ):
            logger.warning(f"Rejected suspicious path request: {raw!r}")
            return None, "bad_request"

        win_reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        }
        name_part = raw.split("/")[0].split("\\")[0].upper()
        if name_part in win_reserved:
            logger.warning(f"Windows 保留设备名请求被拒绝: {raw!r}")
            return None, "bad_request"

        base_dir = base_dir.resolve()
        try:
            abs_path = (base_dir / raw).resolve()

            try:
                abs_path.relative_to(base_dir)
            except ValueError:
                logger.warning(f"路径遍历尝试被阻止: {raw!r} -> {abs_path}")
                return None, "not_found"

        except Exception as e:
            logger.debug(f"路径解析失败: {raw!r}, 错误: {e}")
            return None, "not_found"

        return abs_path, None

    def _require_safe_existing_file(self, raw_path: str, base_dir: Path) -> Path:
        abs_path, error = self._resolve_safe_path(raw_path, base_dir)
        if error == "bad_request":
            raise web.HTTPBadRequest(text="invalid path")
        if not abs_path or not abs_path.exists() or not abs_path.is_file():
            raise web.HTTPNotFound()
        return abs_path

    async def handle_web_static(self, request: web.Request) -> web.StreamResponse:
        abs_path = self._require_safe_existing_file(
            request.match_info.get("path", ""), self.static_dir
        )

        # Manually read the file to avoid FileResponse edge cases on Windows
        try:
            import mimetypes

            content_type, _ = mimetypes.guess_type(abs_path)
            if not content_type:
                content_type = "application/octet-stream"

            # 读取文件内容
            if content_type.startswith("text/") or content_type in (
                "application/javascript",
                "application/json",
                "application/xml",
            ):
                try:
                    content = await asyncio.to_thread(
                        abs_path.read_text, encoding="utf-8"
                    )
                    # 添加字符集信息，确保中文正常显示
                    charset = None
                    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json", "application/xml"):
                        charset = "utf-8"
                    return web.Response(text=content, content_type=content_type, charset=charset)
                except UnicodeDecodeError:
                    # 如果不是 UTF-8，尝试使用系统默认编码
                    try:
                        import locale
                        default_encoding = locale.getpreferredencoding(False)
                        content = await asyncio.to_thread(
                            abs_path.read_text, encoding=default_encoding
                        )
                        charset = None
                        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json", "application/xml"):
                            charset = default_encoding
                        return web.Response(text=content, content_type=content_type, charset=charset)
                    except Exception:
                        # 如果还是失败，尝试二进制
                        pass

            content = await asyncio.to_thread(abs_path.read_bytes)
            return web.Response(body=content, content_type=content_type)

        except Exception as e:
            logger.error(f"Failed to serve static file {abs_path}: {e}")
            raise web.HTTPNotFound()

    async def start(self) -> bool:
        """Start the embedded WebUI server."""
        if not self.static_dir.exists():
            logger.warning(f"WebUI static directory not found: {self.static_dir}")

        base_port = self.port
        for port_attempt in range(0, 3):  # 尝试3个连续端口
            current_port = base_port + port_attempt
            if current_port > 65535:
                break
                
            logger.info(f"尝试启动 WebUI，监听地址 {self.host}:{current_port}")
            last_error = ""
            for attempt in range(1, self.START_RETRY_COUNT + 1):
                try:
                    await self._reset_server_resources()
                    self.runner = web.AppRunner(self.app, access_log=None)
                    await self.runner.setup()

                    # 直接使用 host 和 port 创建 TCPSite
                    # aiohttp 会自动处理 socket 的创建和绑定
                    self.site = web.TCPSite(self.runner, str(self.host), current_port)
                    await self.site.start()

                    self._started = True
                    old_port = self.port
                    self.port = current_port  # 更新实际使用的端口
                    
                    # 如果端口发生变化，尝试回写到插件配置
                    if old_port != current_port:
                        try:
                            if hasattr(self.plugin, 'plugin_config') and hasattr(self.plugin.plugin_config, 'webui'):
                                self.plugin.plugin_config.webui.port = current_port
                                if hasattr(self.plugin.plugin_config, 'save_webui_config'):
                                    self.plugin.plugin_config.save_webui_config()
                                logger.info(f"WebUI 端口已更新为: {current_port}")
                        except Exception as e:
                            logger.debug(f"更新 WebUI 端口配置失败: {e}")
                    
                    protocol = "http"
                    if self.host == "0.0.0.0":
                        logger.info(
                            f"WebUI 启动成功，访问地址: {protocol}://127.0.0.1:{current_port}"
                        )
                    else:
                        logger.info(
                            f"WebUI 启动成功，访问地址: {protocol}://{self.host}:{current_port}"
                        )
                    return True
                except OSError as e:
                    await self._reset_server_resources()
                    last_error = str(e)
                    if self._is_port_in_use_error(e) and attempt < self.START_RETRY_COUNT:
                        delay = self.START_RETRY_DELAY * attempt
                        await asyncio.sleep(delay)
                        continue
                    if not self._is_port_in_use_error(e):
                        # 不是端口占用错误，直接退出
                        break
                except Exception as e:
                    await self._reset_server_resources()
                    last_error = str(e)
                    break

        logger.error(f"WebUI 启动失败，原因: {last_error or '未知错误'}")
        return False

    async def stop(self):
        """Stop the embedded WebUI server."""
        if not self._started and not self.site and not self.runner:
            return
        try:
            if self.site:
                await self.site.stop()
                # 增加延迟时间，确保端口完全释放
                await asyncio.sleep(0.5)
            if self.runner:
                await self.runner.cleanup()
                # 增加延迟时间，确保资源完全清理
                await asyncio.sleep(0.5)
        finally:
            self.site = None
            self.runner = None
            self._started = False
            # 最终延迟，确保所有资源完全释放
            await asyncio.sleep(0.5)
        logger.info("Screen Companion WebUI stopped")

    @staticmethod
    def _is_port_in_use_error(error: OSError) -> bool:
        return (
            "Address already in use" in str(error)
            or getattr(error, "errno", None) in {48, 98, 10048}
        )

    async def _reset_server_resources(self) -> None:
        if self.site:
            try:
                await self.site.stop()
                # 增加延迟，确保端口完全释放
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"停止 site 时出错: {e}")
        if self.runner:
            try:
                await self.runner.cleanup()
                # 增加延迟，确保资源完全清理
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.debug(f"清理 runner 时出错: {e}")
        self.site = None
        self.runner = None
        self._started = False

    async def handle_index(self, request):
        """Return the main index page."""
        try:
            index_file = self.static_dir / "index.html"
            if not index_file.exists():
                return web.Response(
                    text="<h1>Screen Companion WebUI</h1><p>index.html not found</p>",
                    content_type="text/html",
                    charset="utf-8",
                    status=404,
                )
            # Avoid FileResponse edge cases by reading the file manually
            try:
                content = await asyncio.to_thread(
                    index_file.read_text, encoding="utf-8"
                )
            except UnicodeDecodeError:
                content = await asyncio.to_thread(
                    index_file.read_text, encoding="utf-8", errors="replace"
                )
                logger.warning(
                    "WebUI index.html is not valid UTF-8, returned with replacement characters.",
                )
            return web.Response(text=content, content_type="text/html", charset="utf-8", status=200)
        except Exception as e:
            logger.error(f"Error serving index.html: {e}")
            return web.Response(text=f"Error: {e}", content_type="text/plain", charset="utf-8", status=500)

    async def handle_list_diaries(self, request):
        """List available diary files."""
        try:
            diaries = []
            if os.path.exists(self.data_dir):
                for filename in os.listdir(self.data_dir):
                    if filename.startswith('diary_') and filename.endswith('.md'):
                        date_str = filename[6:-3]
                        date = datetime.strptime(date_str, '%Y%m%d')
                        diaries.append({
                            'date': date.strftime('%Y-%m-%d'),
                            'filename': filename
                        })
                diaries.sort(key=lambda x: x['date'], reverse=True)
            return self._ok({
                'diaries': diaries
            })
        except Exception as e:
            logger.error(f"Error listing diaries: {e}")
            return self._err(str(e))

    async def handle_get_diary(self, request):
        """Return a diary by date."""
        try:
            date = request.match_info["date"]
            filename = f'diary_{date.replace("-", "")}.md'
            diary_path = os.path.join(self.data_dir, filename)
            content = ""
            if os.path.exists(diary_path):
                with open(diary_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            return self._ok({
                'date': date,
                'content': content
            })
        except Exception as e:
            logger.error(f"Error getting diary: {e}")
            return self._err(str(e))

    @staticmethod
    def _format_duration(seconds: float | int) -> str:
        total_seconds = max(0, int(seconds or 0))
        return f"{int(total_seconds // 60)}分{int(total_seconds % 60)}秒"

    @staticmethod
    def _build_custom_dashboard_range(start_date: str, end_date: str) -> dict[str, Any] | None:
        start_text = str(start_date or "").strip()
        end_text = str(end_date or "").strip()
        if not start_text or not end_text:
            return None

        try:
            start_day = datetime.strptime(start_text, "%Y-%m-%d").date()
            end_day = datetime.strptime(end_text, "%Y-%m-%d").date()
        except Exception:
            return None

        if start_day > end_day:
            start_day, end_day = end_day, start_day

        start_dt = datetime.combine(start_day, datetime.min.time())
        end_dt_exclusive = datetime.combine(end_day + timedelta(days=1), datetime.min.time())
        return {
            "key": "custom",
            "label": f"{start_text} 至 {end_text}",
            "start_datetime": start_dt,
            "end_datetime_exclusive": end_dt_exclusive,
            "start_date": start_day,
            "end_date": end_day,
            "start_timestamp": start_dt.timestamp(),
            "end_timestamp_exclusive": end_dt_exclusive.timestamp(),
        }

    @staticmethod
    def _get_dashboard_range(range_key: str, start_date: str = "", end_date: str = "") -> dict[str, Any]:
        normalized = str(range_key or "30d").strip().lower()
        if normalized == "custom":
            custom_range = WebServer._build_custom_dashboard_range(start_date, end_date)
            if custom_range:
                return custom_range
            normalized = "30d"
        now_dt = datetime.now()
        today_start = datetime.combine(now_dt.date(), datetime.min.time())
        range_map = {
            "today": {
                "key": "today",
                "label": "今天",
                "start_datetime": today_start,
                "end_datetime_exclusive": None,
                "start_date": today_start.date(),
                "end_date": None,
                "start_timestamp": today_start.timestamp(),
                "end_timestamp_exclusive": None,
            },
            "7d": {
                "key": "7d",
                "label": "近 7 天",
                "start_datetime": now_dt - timedelta(days=7),
                "end_datetime_exclusive": None,
                "start_date": (now_dt - timedelta(days=7)).date(),
                "end_date": None,
                "start_timestamp": (now_dt - timedelta(days=7)).timestamp(),
                "end_timestamp_exclusive": None,
            },
            "30d": {
                "key": "30d",
                "label": "近 30 天",
                "start_datetime": now_dt - timedelta(days=30),
                "end_datetime_exclusive": None,
                "start_date": (now_dt - timedelta(days=30)).date(),
                "end_date": None,
                "start_timestamp": (now_dt - timedelta(days=30)).timestamp(),
                "end_timestamp_exclusive": None,
            },
            "all": {
                "key": "all",
                "label": "全部时间",
                "start_datetime": None,
                "end_datetime_exclusive": None,
                "start_date": None,
                "end_date": None,
                "start_timestamp": None,
                "end_timestamp_exclusive": None,
            },
        }
        return range_map.get(normalized, range_map["30d"])

    @staticmethod
    def _parse_iso_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except Exception:
            return None

    @staticmethod
    def _parse_iso_date(value: Any):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text).date()
        except Exception:
            try:
                return datetime.strptime(text, "%Y-%m-%d").date()
            except Exception:
                return None

    def _is_iso_datetime_in_range(self, value: Any, range_info: dict[str, Any]) -> bool:
        parsed = self._parse_iso_datetime(value)
        if not parsed:
            return False
        start_dt = range_info.get("start_datetime")
        end_dt_exclusive = range_info.get("end_datetime_exclusive")
        if start_dt is not None and parsed < start_dt:
            return False
        if end_dt_exclusive is not None and parsed >= end_dt_exclusive:
            return False
        return True

    def _is_iso_date_in_range(self, value: Any, range_info: dict[str, Any]) -> bool:
        parsed = self._parse_iso_date(value)
        if not parsed:
            return False
        start_date = range_info.get("start_date")
        end_date = range_info.get("end_date")
        if start_date is not None and parsed < start_date:
            return False
        if end_date is not None and parsed > end_date:
            return False
        return True

    def _collect_formatted_observations(self) -> list[dict[str, Any]]:
        observations = []
        for index, obs in enumerate((getattr(self.plugin, "observations", []) or []).copy()):
            scene_name = str(obs.get("scene", "") or "").strip()
            if scene_name.lower() in {"unknown", "none", "null"} or scene_name == "鏈煡":
                scene_name = ""

            active_window = str(
                obs.get("active_window")
                or obs.get("window_title")
                or ""
            ).strip()
            if active_window.lower() in {"unknown", "none", "null"} or active_window in {"??", "?????"}:
                active_window = ""

            content = str(
                obs.get("content")
                or obs.get("description")
                or obs.get("recognition")
                or ""
            ).strip()

            time_period = ""
            timestamp = obs.get("timestamp", "")
            if timestamp:
                try:
                    if "T" in timestamp:
                        hour = int(timestamp.split("T")[1].split(":")[0])
                        if 0 <= hour < 6:
                            time_period = "凌晨"
                        elif 6 <= hour < 12:
                            time_period = "上午"
                        elif 12 <= hour < 18:
                            time_period = "下午"
                        else:
                            time_period = "晚上"
                except Exception:
                    pass

            observations.append(
                {
                    "index": index,
                    **obs,
                    "scene": scene_name,
                    "active_window": active_window,
                    "content": content,
                    "time_period": time_period,
                }
            )

        return observations

    def _collect_memory_records(self) -> list[dict[str, Any]]:
        memories = []
        if hasattr(self.plugin, "_clean_long_term_memory_noise"):
            self.plugin._clean_long_term_memory_noise()
        long_term_memory = getattr(self.plugin, "long_term_memory", {}) or {}

        applications = long_term_memory.get("applications", {})
        for app_name, data in applications.items():
            scenes = data.get("scenes", {}) or {}
            top_scenes = sorted(scenes.items(), key=lambda item: item[1], reverse=True)[:3]
            scene_summary = "、".join(name for name, _ in top_scenes) if top_scenes else ""
            memories.append(
                {
                    "category": "applications",
                    "category_label": "常用应用",
                    "title": app_name,
                    "summary": f"出现 {int(data.get('usage_count', 0) or 0)} 次",
                    "meta": f"最近使用: {data.get('last_used', '未知')} | 关联场景: {scene_summary or '暂无'}",
                    "priority": data.get("priority", 0),
                    "last_date": data.get("last_used", ""),
                }
            )

        scenes = long_term_memory.get("scenes", {})
        for scene_name, data in scenes.items():
            memories.append(
                {
                    "category": "scenes",
                    "category_label": "高频场景",
                    "title": scene_name,
                    "summary": f"出现 {int(data.get('count', 0) or 0)} 次",
                    "meta": f"最近出现: {data.get('last_used', '未知')}",
                    "priority": data.get("priority", 0),
                    "last_date": data.get("last_used", ""),
                }
            )

        user_preferences = long_term_memory.get("user_preferences", {})
        for category, preferences in user_preferences.items():
            for pref_name, data in preferences.items():
                memories.append(
                    {
                        "category": "preferences",
                        "category_label": "用户偏好",
                        "title": pref_name,
                        "summary": f"记录于 {category}",
                        "meta": f"最近提及: {data.get('last_mentioned', '未知')}",
                        "priority": data.get("priority", 0),
                        "last_date": data.get("last_mentioned", ""),
                    }
                )

        associations = long_term_memory.get("memory_associations", {})
        for assoc_name, data in associations.items():
            if "_" in assoc_name:
                scene_name, app_name = assoc_name.split("_", 1)
                title = f"{scene_name} x {app_name}"
            else:
                title = assoc_name
            memories.append(
                {
                    "category": "associations",
                    "category_label": "记忆关联",
                    "title": title,
                    "summary": f"关联出现 {int(data.get('count', 0) or 0)} 次",
                    "meta": f"最近出现: {data.get('last_occurred', '未知')}",
                    "priority": data.get("count", 0),
                    "last_date": data.get("last_occurred", ""),
                }
            )

        shared_activities = long_term_memory.get("shared_activities", {})
        for activity_name, data in shared_activities.items():
            category = str(data.get("category", "other") or "other")
            category_label_map = {
                "watch_media": "一起看过",
                "game": "一起玩过",
                "test": "一起做过测试",
                "screen_interaction": "识屏共同经历",
                "other": "共同经历",
            }
            memories.append(
                {
                    "category": "shared_activities",
                    "category_label": "共同经历",
                    "title": activity_name,
                    "summary": category_label_map.get(category, "共同经历"),
                    "meta": f"最近一次: {data.get('last_shared', '未知')} | 提及 {int(data.get('count', 0) or 0)} 次",
                    "priority": data.get("priority", data.get("count", 0)),
                    "last_date": data.get("last_shared", ""),
                }
            )

        memories.sort(
            key=lambda item: (item.get("priority", 0), item.get("title", "")),
            reverse=True,
        )
        return memories

    async def handle_list_observations(self, request):
        """List observation records."""
        try:
            # 获取查询参数
            page = int(request.query.get('page', 1))
            limit = int(request.query.get('limit', 20))
            sort = request.query.get('sort', 'desc')  # desc 或 asc
            scene = request.query.get('scene', '')
            
            observations = self._collect_formatted_observations()
            
            # 按场景过滤
            if scene:
                observations = [
                    obs for obs in observations
                    if obs.get('scene', '').lower() == scene.lower()
                ]
            
            # 按时间排序
            observations.sort(key=lambda x: x.get('timestamp', ''), reverse=(sort == 'desc'))
            
            # 分页
            total = len(observations)
            start = (page - 1) * limit
            end = start + limit
            paginated_observations = observations[start:end]
            
            return self._ok({
                'observations': paginated_observations,
                'total': total,
                'page': page,
                'limit': limit,
                'pages': (total + limit - 1) // limit
            })
        except Exception as e:
            logger.error(f"Error listing observations: {e}")
            return self._err(str(e))

    async def handle_list_memories(self, request):
        """获取长期记忆列表。"""
        try:
            return self._ok({'memories': self._collect_memory_records()})
        except Exception as e:
            logger.error(f"Error listing memories: {e}")
            return self._err(str(e))

    async def handle_get_config(self, request):
        """Return basic config metadata."""
        try:
            return self._ok({
            "version": "2.6.0",
            "plugin_version": "2.6.0"
            })
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return self._err(str(e))

    def _get_settings_schema_path(self) -> Path:
        return Path(__file__).resolve().parent / "_conf_schema.json"

    def _load_settings_schema(self) -> dict[str, Any]:
        schema_path = self._get_settings_schema_path()
        try:
            import json

            with schema_path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            if isinstance(schema, dict):
                return schema
        except Exception as e:
            logger.error(f"璇诲彇閰嶇疆 schema 澶辫触: {e}")
        return {}

    def _build_settings_payload(self) -> dict[str, Any]:
        schema = self._load_settings_schema()
        values = {}

        for key in schema.keys():
            if key == "screen_recognition_mode":
                values[key] = bool(self.plugin._use_screen_recording_mode())
            else:
                values[key] = getattr(self.plugin, key, None)

        webui_config = getattr(getattr(self.plugin, "plugin_config", None), "webui", None)
        if webui_config:
            values.update(
                {
                    "webui.enabled": bool(getattr(webui_config, "enabled", False)),
                    "webui.host": getattr(webui_config, "host", "0.0.0.0"),
                    "webui.port": int(getattr(webui_config, "port", 6314) or 6314),
                    "webui.auth_enabled": bool(getattr(webui_config, "auth_enabled", True)),
                    "webui.password": getattr(webui_config, "password", ""),
                    "webui.session_timeout": int(getattr(webui_config, "session_timeout", 3600) or 3600),
                    "webui.allow_external_api": bool(getattr(webui_config, "allow_external_api", False)),
                }
            )

        groups = [
            {
                "id": "persona",
                "title": "人格与对话",
                "description": "配置 Bot 的称呼、系统提示词和陪伴式对话风格。",
                "fields": [
                    "bot_name",
                    "system_prompt",
                    "companion_prompt",
                    "user_preferences",
                    "enable_natural_language_screen_assist",
                    "use_llm_for_start_end",
                    "start_preset",
                    "end_preset",
                    "start_llm_prompt",
                    "end_llm_prompt",
                ],
            },
            {
                "id": "runtime",
                "title": "运行节奏",
                "description": "调整自动识屏频率、预设、截图模式和窗口陪伴规则。",
                "fields": [
                    "enabled",
                    "interaction_mode",
                    "check_interval",
                    "trigger_probability",
                    "interaction_frequency",
                    "active_time_range",
                    "rest_time_range",
                    "custom_presets",
                    "current_preset_index",
                    "use_companion_mode",
                    "capture_active_window",
                    "enable_window_companion",
                    "window_companion_targets",
                    "window_companion_check_interval",
                ],
            },
            {
                "id": "vision",
                "title": "识屏与视觉",
                "description": "控制截图来源、视觉模型和识屏提示词。",
                "fields": [
                    "screen_recognition_mode",
                    "ffmpeg_path",
                    "recording_fps",
                    "recording_duration_seconds",
                    "save_local",
                    "use_shared_screenshot_dir",
                    "shared_screenshot_dir",
                    "bot_vision_quality",
                    "image_quality",
                    "image_prompt",
                    "use_external_vision",
                    "allow_unsafe_video_direct_fallback",
                    "vision_api_url",
                    "vision_api_key",
                    "vision_api_model",
                ],
            },
            {
                "id": "diary",
                "title": "日记与记忆",
                "description": "设置日记生成、回顾提醒和长期记忆保留策略。",
                "fields": [
                    "enable_diary",
                    "diary_time",
                    "diary_reference_days",
                    "diary_auto_recall",
                    "diary_recall_time",
                    "diary_send_as_image",
                    "diary_generation_prompt",
                    "enable_learning",
                    "max_observations",
                ],
            },
            {
                "id": "sensing",
                "title": "环境感知",
                "description": "管理麦克风、天气、主动消息目标和自定义监控任务。",
                "fields": [
                    "enable_mic_monitor",
                    "mic_threshold",
                    "mic_check_interval",
                    "weather_api_key",
                    "weather_city",
                    "admin_qq",
                    "proactive_target",
                    "custom_tasks",
                    "debug",
                ],
            },
            {
                "id": "webui",
                "title": "WebUI",
                "description": "配置 WebUI 的访问地址、密码和外部 API 权限。",
                "fields": [
                    "webui.enabled",
                    "webui.host",
                    "webui.port",
                    "webui.auth_enabled",
                    "webui.password",
                    "webui.session_timeout",
                    "webui.allow_external_api",
                ],
            },
        ]

        webui_schema = {
            "webui.enabled": {
                "description": "启用 WebUI",
                "type": "bool",
                "hint": "关闭后不会启动网页管理界面。",
                "default": False,
            },
            "webui.host": {
                "description": "WebUI 监听地址",
                "type": "string",
                "hint": "本机使用可填 127.0.0.1；局域网访问可填 0.0.0.0。",
                "default": "0.0.0.0",
            },
            "webui.port": {
                "description": "WebUI 端口",
                "type": "int",
                "hint": "默认 6314，修改后需要按新端口访问 WebUI。",
                "default": 6314,
                "min": 1024,
                "max": 65535,
            },
            "webui.auth_enabled": {
                "description": "启用访问密码",
                "type": "bool",
                "hint": "开启后访问 WebUI 时需要先登录。",
                "default": True,
            },
            "webui.password": {
                "description": "WebUI 密码",
                "type": "password",
                "hint": "留空时会在首次启动时自动生成随机密码。",
                "default": "",
            },
            "webui.session_timeout": {
                "description": "会话过期时间",
                "type": "int",
                "hint": "单位为秒，超时后需要重新登录。",
                "default": 3600,
                "min": 300,
                "max": 604800,
            },
            "webui.allow_external_api": {
                "description": "允许外部 API 调用",
                "type": "bool",
                "hint": "开启后外部服务可以调用部分 WebUI 接口，默认建议关闭。",
                "default": False,
            },
        }

        schema.update(webui_schema)
        schema.update(
            {
                "enable_window_companion": {
                    "description": "开启窗口自动陪伴",
                    "type": "bool",
                    "hint": "命中的窗口一出现就自动把 Bot 叫过来陪你，窗口关闭后自动结束。",
                    "default": False,
                },
                "window_companion_targets": {
                    "description": "窗口陪伴目标",
                    "type": "text",
                    "hint": "每行一个窗口关键字，也支持\"关键字|补充提示词\"的格式，适合给不同窗口加不同陪伴重点。",
                    "default": "",
                },
                "window_companion_check_interval": {
                    "description": "窗口检查间隔",
                    "type": "int",
                    "hint": "后台每隔多少秒检查一次目标窗口是否出现或关闭。",
                    "default": 5,
                    "min": 2,
                    "max": 300,
                },
            }
        )
        values.update(
            {
                "enable_window_companion": bool(
                    getattr(self.plugin, "enable_window_companion", False)
                ),
                "window_companion_targets": getattr(
                    self.plugin, "window_companion_targets", ""
                )
                or "",
                "window_companion_check_interval": int(
                    getattr(self.plugin, "window_companion_check_interval", 5) or 5
                ),
            }
        )
        return {"schema": schema, "values": values, "groups": groups}

    @staticmethod
    def _coerce_setting_value(field_key: str, field_meta: dict[str, Any], raw_value: Any) -> Any:
        field_type = str(field_meta.get("type", "string") or "string")

        if field_type == "bool":
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, str):
                return raw_value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(raw_value)

        if field_type in {"int", "integer"}:
            value = int(raw_value)
            min_value = field_meta.get("min")
            max_value = field_meta.get("max")
            if min_value is not None and value < int(min_value):
                raise ValueError(f"{field_key} 不能小于 {min_value}")
            if max_value is not None and value > int(max_value):
                raise ValueError(f"{field_key} 不能大于 {max_value}")
            return value

        value = "" if raw_value is None else str(raw_value)
        enum_values = field_meta.get("enum")
        if enum_values and value not in enum_values:
            raise ValueError(f"{field_key} 必须是以下值之一: {', '.join(map(str, enum_values))}")
        return value

    async def handle_get_settings(self, request):
        """返回设置页所需的完整配置数据。"""
        try:
            return self._ok({"settings": self._build_settings_payload()})
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return self._err(str(e))

    async def handle_update_settings(self, request):
        """接收并保存 WebUI 提交的配置更新。"""
        try:
            payload = await request.json()
        except Exception:
            return self._err("Invalid JSON", 400)

        provided_updates = (payload or {}).get("updates")
        if not isinstance(provided_updates, dict) or not provided_updates:
            return self._err("No settings provided", 400)

        settings_payload = self._build_settings_payload()
        schema = settings_payload.get("schema", {})
        normalized_updates: dict[str, Any] = {}
        webui_updates: dict[str, Any] = {}

        try:
            for key, raw_value in provided_updates.items():
                if key not in schema:
                    continue

                coerced = self._coerce_setting_value(key, schema[key], raw_value)
                if key.startswith("webui."):
                    webui_updates[key.split(".", 1)[1]] = coerced
                else:
                    normalized_updates[key] = coerced
        except ValueError as e:
            return self._err(str(e), 400)

        if webui_updates:
            normalized_updates["webui"] = webui_updates

        if not normalized_updates:
            return self._err("No valid settings provided", 400)

        self.plugin._update_config_from_dict(normalized_updates)
        return self._ok({"settings": self._build_settings_payload()})

    async def handle_health_check(self, request):
        """返回 WebUI 健康状态与自检信息。"""
        return self._ok(
            {
                "status": "ok",
                "service": "screen-companion-webui",
            "version": "2.6.0",
            "plugin_version": "2.6.0",
                "host": self.host,
                "port": self.port,
                "auth_enabled": bool(self._get_expected_secret()),
                "session_count": len(self._sessions),
                "started": bool(self._started),
                "instance_match": getattr(self.plugin, "web_server", None) is self,
                "pid": os.getpid(),
                "checked_at": datetime.now().isoformat(),
            }
        )

    def _build_runtime_status(self) -> dict[str, Any]:
        current_interval, current_probability = self.plugin._get_current_preset_params()
        presets = []
        for index, preset in enumerate(getattr(self.plugin, "parsed_custom_presets", []) or []):
            presets.append(
                {
                    "index": index,
                    "name": preset.get("name", f"预设 {index}"),
                    "check_interval": preset.get("check_interval", 0),
                    "trigger_probability": preset.get("trigger_probability", 0),
                    "active": index == getattr(self.plugin, "current_preset_index", -1),
                }
            )

        latest_screenshot = self._build_latest_media_info("image")
        latest_video = self._build_latest_media_info("video")

        return {
            "enabled": bool(getattr(self.plugin, "enabled", False)),
            "is_running": bool(getattr(self.plugin, "is_running", False)),
            "state": getattr(self.plugin, "state", "unknown"),
            "active_task_count": len(getattr(self.plugin, "auto_tasks", {}) or {}),
            "temporary_task_count": len(getattr(self.plugin, "temporary_tasks", {}) or {}),
            "current_preset_index": getattr(self.plugin, "current_preset_index", -1),
            "current_check_interval": current_interval,
            "current_trigger_probability": current_probability,
            "check_interval": getattr(self.plugin, "check_interval", 0),
            "trigger_probability": getattr(self.plugin, "trigger_probability", 0),
            "active_time_range": getattr(self.plugin, "active_time_range", ""),
            "rest_time_range": getattr(self.plugin, "rest_time_range", ""),
            "interaction_mode": getattr(self.plugin, "interaction_mode", ""),
            "interaction_frequency": getattr(self.plugin, "interaction_frequency", 0),
            "enable_diary": bool(getattr(self.plugin, "enable_diary", False)),
            "enable_learning": bool(getattr(self.plugin, "enable_learning", False)),
            "enable_mic_monitor": bool(getattr(self.plugin, "enable_mic_monitor", False)),
            "debug": bool(getattr(self.plugin, "debug", False)),
            "save_local": bool(getattr(self.plugin, "save_local", False)),
            "screen_recognition_mode": bool(self.plugin._use_screen_recording_mode()),
            "use_external_vision": bool(getattr(self.plugin, "use_external_vision", True)),
            "use_shared_screenshot_dir": bool(getattr(self.plugin, "use_shared_screenshot_dir", False)),
            "shared_screenshot_dir": getattr(self.plugin, "shared_screenshot_dir", "") or "",
            "enable_natural_language_screen_assist": bool(getattr(self.plugin, "enable_natural_language_screen_assist", False)),
            "enable_window_companion": bool(getattr(self.plugin, "enable_window_companion", False)),
            "window_companion_targets": getattr(self.plugin, "window_companion_targets", "") or "",
            "window_companion_check_interval": int(getattr(self.plugin, "window_companion_check_interval", 5) or 5),
            "window_companion_active_title": getattr(self.plugin, "window_companion_active_title", "") or "",
            "diary_time": getattr(self.plugin, "diary_time", ""),
            "observation_count": len(getattr(self.plugin, "observations", []) or []),
            "latest_screenshot": latest_screenshot,
            "latest_video": latest_video,
            "presets": presets,
        }

    def _resolve_latest_media_path(self, kind: str) -> tuple[Path | None, str]:
        plugin_data_dir = Path(getattr(self.plugin.plugin_config, "data_dir", Path.cwd()))

        if kind == "image":
            local_path = plugin_data_dir / "screen_shot_latest.jpg"
            if local_path.is_file():
                return local_path, "local_snapshot"

            if bool(getattr(self.plugin, "use_shared_screenshot_dir", False)):
                shared_dir = Path(str(getattr(self.plugin, "shared_screenshot_dir", "") or "").strip())
                if shared_dir.is_dir():
                    candidates: list[Path] = []
                    for suffix in ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp"):
                        candidates.extend(shared_dir.glob(suffix))
                    if candidates:
                        latest = max(candidates, key=lambda item: item.stat().st_mtime)
                        return latest, "shared_directory"
            return None, "missing"

        if kind == "video":
            local_path = plugin_data_dir / "screen_record_latest.mp4"
            if local_path.is_file():
                return local_path, "local_snapshot"

            current_path = Path(str(getattr(self.plugin, "_screen_recording_path", "") or "").strip())
            if current_path.is_file():
                return current_path, "recording_cache"
            return None, "missing"

        return None, "invalid"

    def _build_latest_media_info(self, kind: str) -> dict[str, Any]:
        path, source = self._resolve_latest_media_path(kind)
        if path is None:
            message = (
                "当前没有可预览的最新截图。"
                if kind == "image"
                else "当前没有可预览的最新录屏。"
            )
            if kind == "image" and not bool(getattr(self.plugin, "save_local", False)):
                message = "未找到可预览的截图。可以开启素材留存，或使用共享截图目录模式。"
            if kind == "video" and not bool(getattr(self.plugin, "save_local", False)):
                message = "未找到可预览的录屏。建议开启素材留存后再查看最近录屏。"
            return {
                "available": False,
                "kind": kind,
                "url": "",
                "updated_at": "",
                "size_bytes": 0,
                "source": source,
                "message": message,
            }

        stat = path.stat()
        return {
            "available": True,
            "kind": kind,
            "url": f"/api/media/latest/{kind}?ts={int(stat.st_mtime)}",
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "size_bytes": int(stat.st_size),
            "source": source,
            "message": "",
            "filename": path.name,
        }

    def _build_activity_stats(self, activity_history: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if activity_history is None:
            activity_history = getattr(self.plugin, "activity_history", []) or []
        today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))

        today_work_time = 0
        today_play_time = 0
        today_other_time = 0

        for activity in activity_history:
            if activity.get("start_time", 0) >= today_start:
                duration = activity.get("duration", 0)
                activity_type = activity.get("type", "其他")
                if activity_type == "工作":
                    today_work_time += duration
                elif activity_type == "摸鱼":
                    today_play_time += duration
                else:
                    today_other_time += duration

        total_work_time = sum(
            activity.get("duration", 0)
            for activity in activity_history
            if activity.get("type") == "工作"
        )
        total_play_time = sum(
            activity.get("duration", 0)
            for activity in activity_history
            if activity.get("type") == "摸鱼"
        )
        total_other_time = sum(
            activity.get("duration", 0)
            for activity in activity_history
            if activity.get("type") not in {"工作", "摸鱼"}
        )

        recent_activities = sorted(
            activity_history,
            key=lambda x: x.get("start_time", 0),
            reverse=True,
        )[:10]

        formatted_activities = []
        for activity in recent_activities:
            start_ts = activity.get("start_time", 0)
            end_ts = activity.get("end_time", 0)
            duration = activity.get("duration", 0)
            formatted_activities.append(
                {
                    "type": activity.get("type", "其他"),
                    "scene": activity.get("scene", ""),
                    "window": activity.get("window", ""),
                    "start_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_ts)),
                    "end_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_ts)),
                    "duration": self._format_duration(duration),
                    "duration_seconds": int(duration or 0),
                }
            )

        return {
            "today": {
                "work_time": self._format_duration(today_work_time),
                "play_time": self._format_duration(today_play_time),
                "other_time": self._format_duration(today_other_time),
                "total_time": self._format_duration(
                    today_work_time + today_play_time + today_other_time
                ),
                "work_seconds": int(today_work_time),
                "play_seconds": int(today_play_time),
                "other_seconds": int(today_other_time),
                "total_seconds": int(today_work_time + today_play_time + today_other_time),
            },
            "total": {
                "work_time": self._format_duration(total_work_time),
                "play_time": self._format_duration(total_play_time),
                "other_time": self._format_duration(total_other_time),
                "total_time": self._format_duration(
                    total_work_time + total_play_time + total_other_time
                ),
                "work_seconds": int(total_work_time),
                "play_seconds": int(total_play_time),
                "other_seconds": int(total_other_time),
                "total_seconds": int(total_work_time + total_play_time + total_other_time),
            },
            "recent_activities": formatted_activities,
            "activity_count": len(activity_history),
        }

    async def handle_get_runtime_status(self, request):
        """将静态资源请求安全地映射到 web 目录。"""
        try:
            return self._ok({"runtime": self._build_runtime_status()})
        except Exception as e:
            logger.error(f"Error getting runtime status: {e}")
            return self._err(str(e))

    async def handle_list_windows(self, request):
        """Return currently visible window titles."""
        try:
            titles = self.plugin._list_open_window_titles()
            return self._ok({"windows": titles, "count": len(titles)})
        except Exception as e:
            logger.error(f"读取窗口列表失败: {e}")
            return self._err(str(e))

    async def handle_get_activity_stats(self, request):
        """Get activity statistics (work vs play time)."""
        try:
            return self._ok(self._build_activity_stats())
        except Exception as e:
            logger.error(f"Error getting activity stats: {e}")
            return self._err(str(e))

    async def handle_get_dashboard_stats(self, request):
        """Return aggregated statistics for the WebUI dashboard tables."""
        try:
            requested_range = request.query.get("range", "30d")
            requested_start_date = request.query.get("start_date", "")
            requested_end_date = request.query.get("end_date", "")
            range_info = self._get_dashboard_range(
                requested_range,
                requested_start_date,
                requested_end_date,
            )
            runtime = self._build_runtime_status()
            all_activity_history = getattr(self.plugin, "activity_history", []) or []
            filtered_activity_history = [
                item
                for item in all_activity_history
                if (
                    (range_info.get("start_timestamp") is None
                     or float(item.get("start_time", 0) or 0) >= float(range_info["start_timestamp"]))
                    and (
                        range_info.get("end_timestamp_exclusive") is None
                        or float(item.get("start_time", 0) or 0) < float(range_info["end_timestamp_exclusive"])
                    )
                )
            ]
            activity = self._build_activity_stats(filtered_activity_history)
            total_activity = self._build_activity_stats(all_activity_history)
            observations = [
                item
                for item in self._collect_formatted_observations()
                if self._is_iso_datetime_in_range(item.get("timestamp", ""), range_info)
            ]
            memories = [
                item
                for item in self._collect_memory_records()
                if self._is_iso_date_in_range(item.get("last_date", ""), range_info)
            ]
            diaries = []
            try:
                diaries = [
                    item
                    for item in self.plugin._get_diary_dates_with_content()
                    if self._is_iso_date_in_range(item.get("date", ""), range_info)
                ]
            except Exception:
                diaries = []

            overview_rows = [
                {
                    "metric": "统计范围",
                    "value": range_info["label"],
                    "detail": f"筛选键 {range_info['key']}",
                },
                {
                    "metric": "插件状态",
                    "value": "已启用" if runtime.get("enabled") else "已关闭",
                    "detail": f"运行态 {runtime.get('state', 'unknown')} / 自动任务 {runtime.get('active_task_count', 0)} 个",
                },
                {
                    "metric": "当前预设",
                    "value": str(runtime.get("current_preset_index", -1)),
                    "detail": f"生效间隔 {runtime.get('current_check_interval', 0)} 秒 / 触发 {runtime.get('current_trigger_probability', 0)}%",
                },
                {
                    "metric": "互动频率",
                    "value": str(runtime.get("interaction_frequency", 0)),
                    "detail": f"模式 {runtime.get('interaction_mode', '未设置')}",
                },
                {
                    "metric": "日记数量",
                    "value": str(len(diaries)),
                    "detail": f"最近日期 {diaries[0].get('date', '暂无') if diaries else '暂无'}",
                },
                {
                    "metric": "观察记录",
                    "value": str(len(observations)),
                    "detail": "包含全部已保留观察条目",
                },
                {
                    "metric": "长期记忆",
                    "value": str(len(memories)),
                    "detail": "包含应用、场景、偏好、关联与共同经历",
                },
                {
                    "metric": "活动片段",
                    "value": str(activity.get("activity_count", 0)),
                    "detail": f"{range_info['label']}内累计 {activity.get('total', {}).get('total_time', '0分0秒')}",
                },
            ]

            activity_rows = []
            if range_info["key"] == "today":
                activity_rows.append(
                    {
                        "range": "今天",
                        "work": activity.get("today", {}).get("work_time", "0分0秒"),
                        "play": activity.get("today", {}).get("play_time", "0分0秒"),
                        "other": activity.get("today", {}).get("other_time", "0分0秒"),
                        "total": activity.get("today", {}).get("total_time", "0分0秒"),
                    }
                )
            else:
                activity_rows.append(
                    {
                        "range": range_info["label"],
                        "work": activity.get("total", {}).get("work_time", "0分0秒"),
                        "play": activity.get("total", {}).get("play_time", "0分0秒"),
                        "other": activity.get("total", {}).get("other_time", "0分0秒"),
                        "total": activity.get("total", {}).get("total_time", "0分0秒"),
                    }
                )
            if range_info["key"] != "all":
                activity_rows.append(
                    {
                        "range": "全部历史",
                        "work": total_activity.get("total", {}).get("work_time", "0分0秒"),
                        "play": total_activity.get("total", {}).get("play_time", "0分0秒"),
                        "other": total_activity.get("total", {}).get("other_time", "0分0秒"),
                        "total": total_activity.get("total", {}).get("total_time", "0分0秒"),
                    }
                )

            scene_groups: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"count": 0, "latest_timestamp": "", "latest_window": "", "time_period": ""}
            )
            for observation in observations:
                scene_name = observation.get("scene") or "未标注"
                bucket = scene_groups[scene_name]
                bucket["count"] += 1
                timestamp = str(observation.get("timestamp", "") or "")
                if timestamp >= bucket["latest_timestamp"]:
                    bucket["latest_timestamp"] = timestamp
                    bucket["latest_window"] = observation.get("active_window") or "暂无"
                    bucket["time_period"] = observation.get("time_period") or "未知"

            scene_rows = [
                {
                    "scene": scene_name,
                    "count": str(data["count"]),
                    "last_seen": data["latest_timestamp"] or "未知",
                    "time_period": data["time_period"] or "未知",
                    "window": data["latest_window"] or "暂无",
                }
                for scene_name, data in sorted(
                    scene_groups.items(),
                    key=lambda item: (item[1]["count"], item[1]["latest_timestamp"]),
                    reverse=True,
                )[:12]
            ]

            memory_category_groups: dict[str, dict[str, Any]] = defaultdict(
                lambda: {"count": 0, "max_priority": 0, "top_title": ""}
            )
            for memory in memories:
                category_label = memory.get("category_label") or "未分类"
                bucket = memory_category_groups[category_label]
                bucket["count"] += 1
                priority = int(memory.get("priority", 0) or 0)
                if priority >= bucket["max_priority"]:
                    bucket["max_priority"] = priority
                    bucket["top_title"] = memory.get("title", "")

            memory_category_rows = [
                {
                    "category": category_label,
                    "count": str(data["count"]),
                    "max_priority": str(data["max_priority"]),
                    "example": data["top_title"] or "暂无",
                }
                for category_label, data in sorted(
                    memory_category_groups.items(),
                    key=lambda item: (item[1]["count"], item[1]["max_priority"]),
                    reverse=True,
                )
            ]

            top_memory_rows = [
                {
                    "rank": str(index + 1),
                    "title": memory.get("title", ""),
                    "category": memory.get("category_label", ""),
                    "priority": str(memory.get("priority", 0)),
                    "summary": memory.get("summary", ""),
                }
                for index, memory in enumerate(memories[:10])
            ]

            recent_activity_rows = [
                {
                    "start": item.get("start_time", ""),
                    "end": item.get("end_time", ""),
                    "type": item.get("type", ""),
                    "scene": item.get("scene", "") or "未标注",
                    "window": item.get("window", "") or "暂无",
                    "duration": item.get("duration", ""),
                }
                for item in activity.get("recent_activities", [])
            ]

            return self._ok(
                {
                    "generated_at": datetime.now().isoformat(),
                    "range_key": range_info["key"],
                    "range_label": range_info["label"],
                    "range_start_date": str(range_info.get("start_date") or ""),
                    "range_end_date": str(range_info.get("end_date") or ""),
                    "overview_rows": overview_rows,
                    "activity_rows": activity_rows,
                    "scene_rows": scene_rows,
                    "memory_category_rows": memory_category_rows,
                    "top_memory_rows": top_memory_rows,
                    "recent_activity_rows": recent_activity_rows,
                }
            )
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            return self._err(str(e))

    async def handle_update_runtime_config(self, request):
        """更新运行时配置并返回最新状态。"""
        try:
            payload = await request.json()
        except Exception:
            return self._err("Invalid JSON", 400)

        allowed_keys = {
            "enabled",
            "check_interval",
            "trigger_probability",
            "active_time_range",
            "rest_time_range",
            "interaction_mode",
            "interaction_frequency",
            "enable_diary",
            "enable_learning",
            "enable_mic_monitor",
            "debug",
            "current_preset_index",
        }

        updates = {}
        for key, value in (payload or {}).items():
            if key in allowed_keys:
                updates[key] = value

        if not updates:
            return self._err("No valid runtime fields provided", 400)

        if "current_preset_index" in updates:
            try:
                preset_index = int(updates["current_preset_index"])
            except Exception:
                return self._err("current_preset_index must be an integer", 400)

            preset_count = len(getattr(self.plugin, "parsed_custom_presets", []) or [])
            if preset_index < -1 or preset_index >= preset_count:
                return self._err("Preset index out of range", 400)
            updates["current_preset_index"] = preset_index

        self.plugin._update_config_from_dict(updates)
        return self._ok({"runtime": self._build_runtime_status()})

    async def handle_stop_runtime_tasks(self, request):
        """停止当前自动观察任务。"""
        try:
            auto_tasks = list((getattr(self.plugin, "auto_tasks", {}) or {}).items())
            self.plugin.is_running = False
            self.plugin.state = "inactive"

            for _, task in auto_tasks:
                task.cancel()

            for task_id, task in auto_tasks:
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待任务 {task_id} 停止超时")
                except asyncio.CancelledError:
                    logger.info(f"[Task {task_id}] status update")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

            if hasattr(self.plugin, "auto_tasks"):
                self.plugin.auto_tasks.clear()

            return self._ok({"runtime": self._build_runtime_status()})
        except Exception as e:
            logger.error(f"Error stopping runtime tasks: {e}")
            return self._err(str(e))

    async def handle_delete_observation(self, request):
        """删除单个观察记录。"""
        try:
            index = int(request.match_info["index"])
            if 0 <= index < len(self.plugin.observations):
                deleted_observation = self.plugin.observations.pop(index)
                self.plugin._save_observations()
                return self._ok({"deleted": deleted_observation})
            else:
                return self._err("索引超出范围", 400)
        except Exception as e:
            logger.error(f"删除观察记录失败: {e}")
            return self._err(str(e))

    async def handle_batch_delete_observations(self, request):
        """批量删除观察记录。"""
        try:
            payload = await request.json()
            indices = payload.get("indices", [])
            # 确保索引为整数并倒序删除，避免索引位移
            sorted_indices = sorted([int(i) for i in indices], reverse=True)
            deleted_count = 0
            for index in sorted_indices:
                if 0 <= index < len(self.plugin.observations):
                    self.plugin.observations.pop(index)
                    deleted_count += 1
            self.plugin._save_observations()
            return self._ok({"deleted_count": deleted_count})
        except Exception as e:
            logger.error(f"批量删除观察记录失败: {e}")
            return self._err(str(e))

    async def handle_clear_all_data(self, request):
        """清空所有资料（观察记录、学习数据、日记等）。"""
        try:
            payload = await request.json()
            confirm = payload.get("confirm", False)
            
            if not confirm:
                return self._err("需要确认才能清空资料", 400)
            
            cleared_items = []
            
            # 清空观察记录
            if hasattr(self.plugin, "observations"):
                obs_count = len(self.plugin.observations or [])
                self.plugin.observations = []
                self.plugin._save_observations()
                if obs_count > 0:
                    cleared_items.append(f"观察记录({obs_count}条)")
            
            # 清空学习数据
            if hasattr(self.plugin, "learning_data"):
                self.plugin.learning_data = {}
                self.plugin._save_learning_data()
                cleared_items.append("学习数据")
            
            # 清空长期记忆
            if hasattr(self.plugin, "long_term_memory"):
                self.plugin.long_term_memory = {}
                self.plugin._save_long_term_memory()
                cleared_items.append("长期记忆")
            
            # 清空纠正数据
            if hasattr(self.plugin, "corrections"):
                self.plugin.corrections = {}
                self.plugin._save_corrections()
                cleared_items.append("纠正数据")
            
            # 清空日记
            if hasattr(self.plugin, "diary_entries"):
                diary_count = len(self.plugin.diary_entries or [])
                self.plugin.diary_entries = []
                if diary_count > 0:
                    cleared_items.append(f"日记({diary_count}条)")
            
            logger.info(f"用户清空了以下资料: {', '.join(cleared_items)}")
            
            return self._ok({
                "cleared": cleared_items,
                "message": f"已清空: {', '.join(cleared_items)}"
            })
        except Exception as e:
            logger.error(f"清空资料失败: {e}")
            return self._err(str(e))

    async def handle_analyze_image(self, request):
        """通过文件上传分析图片"""
        try:
            reader = await request.multipart()
            
            image_bytes = None
            custom_prompt = None
            webhook_url = None
            
            async for field in reader:
                if field.name == "image":
                    image_bytes = await field.read()
                elif field.name == "prompt":
                    custom_prompt = await field.text()
                elif field.name == "webhook":
                    webhook_url = await field.text()
            
            if not image_bytes:
                return self._err("Invalid request", 400)
            
            # 调用插件的分析方法
            result = await self._analyze_image_logic(image_bytes, custom_prompt)
            
            # 如果提供了 webhook，则异步发送分析结果
            if webhook_url and result.get("success"):
                asyncio.create_task(self._send_webhook(webhook_url, result))
            
            return self._ok(result)
            
        except Exception as e:
            logger.error(f"图片分析失败: {e}")
            return self._err(str(e))

    async def handle_get_latest_media(self, request):
        kind = str(request.match_info.get("kind", "") or "").strip().lower()
        if kind not in {"image", "video"}:
            return self._err("Unsupported media kind", 400)

        try:
            path, _ = self._resolve_latest_media_path(kind)
            if path is None or not path.is_file():
                return self._err("Latest media is not available", 404)
            return web.FileResponse(path=path)
        except Exception as e:
            logger.error(f"读取最新{kind}预览失败: {e}")
            return self._err(str(e))

    async def handle_analyze_image_base64(self, request):
        """通过Base64分析图片"""
        try:
            payload = await request.json()
            
            image_base64 = payload.get("image", "")
            custom_prompt = payload.get("prompt", "")
            webhook_url = payload.get("webhook", "")
            
            if not image_base64:
                return self._err("未提供图片 Base64 数据", 400)
            
            # 解码 Base64
            import base64
            try:
                if image_base64.startswith("data:"):
                    # 去除 data:image/xxx;base64, 前缀
                    image_base64 = image_base64.split(",", 1)[1]
                image_bytes = base64.b64decode(image_base64)
            except Exception:
                return self._err("Base64 解码失败", 400)

            # 调用插件的图片分析逻辑
            result = await self._analyze_image_logic(image_bytes, custom_prompt)

            # 如果提供了 webhook，则异步发送分析结果
            if webhook_url and result.get("success"):
                asyncio.create_task(self._send_webhook(webhook_url, result))

            return self._ok(result)
            
        except Exception as e:
            logger.error(f"鍥剧墖鍒嗘瀽澶辫触: {e}")
            return self._err(str(e))

    async def _analyze_image_logic(self, image_bytes: bytes, custom_prompt: str = None) -> dict:
        """Analyze an uploaded image and build a companion reply."""
        try:
            if not self.plugin.vision_api_url:
                return {
                    "success": False,
                    "error": "Vision API is not configured",
                    "reply": "I do not have vision configured yet.",
                }

            recognition_text = await self.plugin._call_external_vision_api(image_bytes)
            if not recognition_text or "??" in recognition_text or "??" in recognition_text:
                return {
                    "success": False,
                    "error": recognition_text or "Vision recognition failed",
                    "reply": "I could not see the screen clearly just now.",
                }

            scene = self.plugin._identify_scene("external_image")
            interaction_prompt = f"请基于这张图片里的内容给出自然、实用的观察与建议：{recognition_text}"
            if custom_prompt:
                interaction_prompt += f" {custom_prompt}"

            system_prompt = await self.plugin._get_persona_prompt()
            provider = self.plugin.context.get_using_provider()
            if provider:
                try:
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=interaction_prompt, system_prompt=system_prompt),
                        timeout=60.0,
                    )
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        reply_text = response.completion_text
                    else:
                        reply_text = "I saw the screen, but I do not have a strong suggestion yet."
                except asyncio.TimeoutError:
                    reply_text = "I paused for too long just now. Try asking me again."
                except Exception as e:
                    logger.error(f"LLM call failed: {e}")
                    reply_text = "Something interrupted my reply just now. Try me again."
            else:
                reply_text = "No enabled LLM provider is available."

            return {
                "success": True,
                "recognition": recognition_text,
                "scene": scene,
                "reply": reply_text,
            }

        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "reply": "Something went wrong during image analysis.",
            }

    async def _send_webhook(self, url: str, data: dict) -> None:
        """Send analysis result to webhook URL."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=data, timeout=10.0)
        except Exception as e:
            logger.error(f"Webhook delivery failed: {e}")

    async def handle_auth_info(self, request):
        """Return auth status and config."""
        try:
            expected = self._get_expected_secret()
            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            now = time.time()
            authenticated = bool(
                expected
                and sid
                and sid in self._sessions
                and self._sessions[sid] >= now
            )
            return self._ok({
                "requires_auth": bool(expected),
                "authenticated": authenticated,
                "auth_enabled": bool(expected),
                "session_timeout": self._get_session_timeout(),
            })
        except Exception as e:
            logger.error(f"Error getting auth info: {e}")
            return self._err(str(e))

    async def handle_auth_login(self, request):
        """Handle login request."""
        try:
            payload = await request.json()
            password = payload.get("password", "")
            expected = self._get_expected_secret()
            
            if not expected:
                return self._err("Authentication is not enabled", 403)
            
            if password != expected:
                return self._err("Invalid password", 401)
            
            # Create session
            sid = str(uuid.uuid4())
            timeout = self._get_session_timeout()
            self._sessions[sid] = time.time() + timeout
            
            # Set cookie
            response = self._ok({"success": True})
            response.set_cookie(
                self._cookie_name,
                sid,
                max_age=timeout,
                httponly=True,
                samesite="strict",
            )
            return response
        except Exception as e:
            logger.error(f"Error handling login: {e}")
            return self._err(str(e))

    async def handle_auth_logout(self, request):
        """Handle logout request."""
        try:
            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            if sid:
                self._sessions.pop(sid, None)
            
            response = self._ok({"success": True})
            response.del_cookie(self._cookie_name)
            return response
        except Exception as e:
            logger.error(f"Error handling logout: {e}")
            return self._err(str(e))
