import asyncio
import time
import os
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

from astrbot.api import logger


class WebServer:
    """Embedded WebUI server for Screen Companion."""

    APP_VERSION = "2.9.5"
    CLIENT_MAX_SIZE = 50 * 1024 * 1024
    SESSION_CLEANUP_INTERVAL = 300
    SESSION_MAX_COUNT = 1000
    START_RETRY_COUNT = 3
    START_RETRY_DELAY = 0.5
    FOCUS_SESSION_THRESHOLD_SECONDS = 25 * 60
    ACTIVITY_TREND_DAYS = 7
    TOP_WINDOW_LIMIT = 5
    ACTIVITY_SESSION_GAP_SECONDS = 12 * 60
    ACTIVITY_SURFACE_LIMIT = 6
    SENSITIVE_SETTINGS_KEYS = frozenset(
        {
            "vision_api_key",
            "vision_api_key_backup",
            "weather_api_key",
            "webui.password",
        }
    )

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

    def _plugin_bool(self, name: str, default: bool = False) -> bool:
        value = getattr(self.plugin, name, default)
        coerce = getattr(self.plugin, "_coerce_bool", None)
        if callable(coerce):
            return coerce(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _safe_plugin_call(self, name: str, default: Any = None, *args, **kwargs):
        method = getattr(self.plugin, name, None)
        if not callable(method):
            return default
        try:
            return method(*args, **kwargs)
        except Exception as e:
            logger.warning(f"调用插件方法 {name} 失败，已回退默认值: {e}")
            return default

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
        password = ""
        try:
            password = str(self.plugin.plugin_config.webui.password or "").strip()
        except Exception:
            password = ""

        if not password:
            return ""
        if not self._is_auth_enabled():
            return ""
        return password

    def _get_session_timeout(self) -> int:
        timeout = 3600
        try:
            timeout = int(self.plugin.plugin_config.webui.session_timeout or 3600)
        except Exception:
            timeout = 3600

        if timeout <= 0:
            timeout = 3600
        return timeout

    @staticmethod
    def _is_public_path(path: str) -> bool:
        return path in {
            "/",
            "/index.html",
            "/auth/info",
            "/auth/login",
            "/auth/logout",
            "/api/config",
            "/api/health",
        } or path == "/web" or path.startswith("/web/")

    @classmethod
    def _is_sensitive_setting_key(cls, key: str) -> bool:
        return str(key or "") in cls.SENSITIVE_SETTINGS_KEYS

    @classmethod
    def _should_preserve_sensitive_value(cls, key: str, raw_value: Any) -> bool:
        if not cls._is_sensitive_setting_key(key):
            return False
        return not str(raw_value or "").strip()

    async def _auth_middleware(self, app: web.Application, handler):
        async def middleware_handler(request: web.Request):
            if request.method == "OPTIONS":
                return await handler(request)

            path = request.path or "/"
            expected = self._get_expected_secret()

            if path in ("/api/analyze", "/api/analyze/base64"):
                if not self.plugin.webui_allow_external_api:
                    return WebServer._err("External API disabled", 403)

                if expected:
                    api_key = request.headers.get("X-API-Key", "")
                    if not api_key or api_key != expected:
                        return WebServer._err("Unauthorized", 401)
                return await handler(request)

            if not expected:
                return await handler(request)

            if self._is_public_path(path):
                return await handler(request)

            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            now = time.time()

            if now - self._last_session_cleanup > self._session_cleanup_interval:
                expired = [k for k, v in self._sessions.items() if v < now]
                for k in expired:
                    self._sessions.pop(k, None)
                self._last_session_cleanup = now

                if len(self._sessions) > self.SESSION_MAX_COUNT:
                    sorted_sessions = sorted(self._sessions.items(), key=lambda x: x[1])
                    to_remove = len(self._sessions) - self.SESSION_MAX_COUNT // 2
                    for k, _ in sorted_sessions[:to_remove]:
                        self._sessions.pop(k, None)
                    logger.warning(
                        f"Session 数量超过上限 {self.SESSION_MAX_COUNT}，已清理 {to_remove} 个最早过期的 session"
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
        self.app.router.add_delete("/api/diary/{date}", self.handle_delete_diary)
        self.app.router.add_delete("/api/diaries/batch", self.handle_batch_delete_diaries)
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
            structured_summary: dict[str, Any] = {}
            if os.path.exists(diary_path):
                with open(diary_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except Exception:
                target_date = None
            if target_date and hasattr(self.plugin, "_load_diary_structured_summary"):
                structured_summary = self.plugin._load_diary_structured_summary(target_date) or {}
            return self._ok({
                'date': date,
                'content': content,
                'structured_summary': structured_summary,
            })
        except Exception as e:
            logger.error(f"Error getting diary: {e}")
            return self._err(str(e))

    @staticmethod
    def _parse_diary_date(date_str: str) -> date | None:
        try:
            return datetime.strptime(str(date_str or "").strip(), "%Y-%m-%d").date()
        except Exception:
            return None

    def _get_diary_markdown_path(self, target_date: date) -> Path:
        return Path(self.data_dir) / f"diary_{target_date.strftime('%Y%m%d')}.md"

    def _get_diary_summary_path(self, target_date: date) -> Path:
        helper = getattr(self.plugin, "_get_diary_summary_path", None)
        if callable(helper):
            try:
                return Path(helper(target_date))
            except Exception as e:
                logger.debug(f"读取日记摘要路径失败，已回退默认路径: {e}")
        return Path(self.data_dir) / f"diary_{target_date.strftime('%Y%m%d')}.summary.json"

    def _drop_diary_metadata(self, date_str: str) -> bool:
        metadata = getattr(self.plugin, "diary_metadata", None)
        if not isinstance(metadata, dict) or date_str not in metadata:
            return False
        metadata.pop(date_str, None)
        saver = getattr(self.plugin, "_save_diary_metadata", None)
        if callable(saver):
            saver()
        return True

    def _delete_diary_artifacts(self, target_date: date) -> dict[str, Any]:
        removed_files: list[str] = []
        removed_any = False
        for path in (
            self._get_diary_markdown_path(target_date),
            self._get_diary_summary_path(target_date),
        ):
            try:
                if path.exists():
                    path.unlink()
                    removed_files.append(path.name)
                    removed_any = True
            except Exception as e:
                logger.error(f"删除日记文件失败: {path} - {e}")
                raise

        metadata_removed = self._drop_diary_metadata(target_date.isoformat())
        return {
            "date": target_date.isoformat(),
            "removed": removed_any or metadata_removed,
            "removed_files": removed_files,
            "metadata_removed": metadata_removed,
        }

    async def handle_delete_diary(self, request):
        """删除单篇日记及其附属摘要。"""
        try:
            target_date = self._parse_diary_date(request.match_info["date"])
            if not target_date:
                return self._err("日期格式无效，应为 YYYY-MM-DD", 400)

            result = self._delete_diary_artifacts(target_date)
            if not result["removed"]:
                return self._err("没有找到对应的日记", 404)
            return self._ok(result)
        except Exception as e:
            logger.error(f"删除日记失败: {e}")
            return self._err(str(e))

    async def handle_batch_delete_diaries(self, request):
        """批量删除多篇日记及其附属摘要。"""
        try:
            payload = await request.json()
            dates = payload.get("dates", [])
            if not isinstance(dates, list) or not dates:
                return self._err("请提供要删除的日期列表", 400)

            deleted_items: list[dict[str, Any]] = []
            missing_dates: list[str] = []
            for raw_date in dates:
                target_date = self._parse_diary_date(str(raw_date or "").strip())
                if not target_date:
                    missing_dates.append(str(raw_date or "").strip())
                    continue
                result = self._delete_diary_artifacts(target_date)
                if result["removed"]:
                    deleted_items.append(result)
                else:
                    missing_dates.append(target_date.isoformat())

            return self._ok(
                {
                    "deleted_count": len(deleted_items),
                    "deleted_dates": [item["date"] for item in deleted_items],
                    "missing_dates": missing_dates,
                }
            )
        except Exception as e:
            logger.error(f"批量删除日记失败: {e}")
            return self._err(str(e))

    @staticmethod
    def _format_duration(seconds: float | int) -> str:
        total_seconds = max(0, int(seconds or 0))
        return f"{int(total_seconds // 60)}分{int(total_seconds % 60)}秒"

    @staticmethod
    def _format_clock(timestamp_value: float | int | None) -> str:
        try:
            timestamp = float(timestamp_value or 0)
        except Exception:
            timestamp = 0.0
        if timestamp <= 0:
            return ""
        return time.strftime("%H:%M", time.localtime(timestamp))

    @staticmethod
    def _format_datetime(timestamp_value: float | int | None) -> str:
        try:
            timestamp = float(timestamp_value or 0)
        except Exception:
            timestamp = 0.0
        if timestamp <= 0:
            return ""
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

    @staticmethod
    def _capture_source_label(source: Any) -> str:
        source_key = str(source or "").strip()
        mapping = {
            "screen_analysis": "识屏轨迹",
            "background_tracker": "独立轨迹",
        }
        return mapping.get(source_key, "其他来源")

    @staticmethod
    def _health_status_rank(status: str) -> int:
        normalized = str(status or "ok").strip().lower()
        if normalized == "error":
            return 2
        if normalized == "warn":
            return 1
        return 0

    @staticmethod
    def _health_status_label(status: str) -> str:
        normalized = str(status or "ok").strip().lower()
        labels = {
            "ok": "正常",
            "warn": "注意",
            "error": "异常",
        }
        return labels.get(normalized, "正常")

    @classmethod
    def _merge_health_status(cls, current: str, new_status: str) -> str:
        return (
            str(new_status or "ok").strip().lower()
            if cls._health_status_rank(new_status) > cls._health_status_rank(current)
            else str(current or "ok").strip().lower()
        )

    @classmethod
    def _build_health_check_entry(
        cls,
        *,
        key: str,
        title: str,
        status: str,
        detail: str,
    ) -> dict[str, Any]:
        normalized_status = str(status or "ok").strip().lower() or "ok"
        return {
            "key": key,
            "title": title,
            "status": normalized_status,
            "status_label": cls._health_status_label(normalized_status),
            "detail": str(detail or "").strip(),
        }

    def _build_health_payload(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        recommendations: list[dict[str, str]] = []
        overall_status = "ok"

        def add_check(entry: dict[str, Any]) -> None:
            nonlocal overall_status
            checks.append(entry)
            overall_status = self._merge_health_status(
                overall_status,
                str(entry.get("status", "ok") or "ok"),
            )

        static_targets = {
            "index.html": self.static_dir / "index.html",
            "app.js": self.static_dir / "app.js",
            "app.css": self.static_dir / "app.css",
        }
        missing_static = [
            name for name, path in static_targets.items() if not path.is_file()
        ]
        add_check(
            self._build_health_check_entry(
                key="static_assets",
                title="WebUI 静态资源",
                status="error" if missing_static else "ok",
                detail=(
                    f"缺少 {', '.join(missing_static)}"
                    if missing_static
                    else f"静态目录可用：{self.static_dir}"
                ),
            )
        )
        if missing_static:
            recommendations.append(
                {
                    "title": "检查 WebUI 资源目录",
                    "body": "当前 WebUI 缺少必要静态文件。请确认插件目录完整覆盖，且 web 目录下的 index.html、app.js、app.css 都已更新。",
                }
            )

        diary_dir = Path(str(getattr(self.plugin, "diary_storage", "") or "").strip())
        add_check(
            self._build_health_check_entry(
                key="diary_storage",
                title="日记目录",
                status="ok" if diary_dir.is_dir() else "warn",
                detail=(
                    f"当前目录：{diary_dir}"
                    if diary_dir.is_dir()
                    else f"目录不可用：{diary_dir or '未配置'}"
                ),
            )
        )

        learning_dir = Path(
            str(getattr(self.plugin, "learning_storage", "") or "").strip()
        )
        add_check(
            self._build_health_check_entry(
                key="learning_storage",
                title="学习与轨迹目录",
                status="ok" if learning_dir.is_dir() else "warn",
                detail=(
                    f"当前目录：{learning_dir}"
                    if learning_dir.is_dir()
                    else f"目录不可用：{learning_dir or '未配置'}"
                ),
            )
        )

        activity_count = len(getattr(self.plugin, "activity_history", []) or [])
        add_check(
            self._build_health_check_entry(
                key="activity_history",
                title="活动轨迹样本",
                status="ok",
                detail=f"当前累计 {activity_count} 条活动轨迹记录。",
            )
        )

        input_stats = self._safe_plugin_call("_get_input_stats_runtime_status", {}) or {}
        input_stats_enabled = bool(input_stats.get("enabled"))
        input_stats_available = bool(input_stats.get("available"))
        add_check(
            self._build_health_check_entry(
                key="input_stats",
                title="本地输入统计",
                status="warn" if input_stats_enabled and not input_stats_available else "ok",
                detail=str(
                    input_stats.get("detail")
                    or ("已启用" if input_stats_enabled else "未启用")
                ),
            )
        )
        if input_stats_enabled and not input_stats_available:
            recommendations.append(
                {
                    "title": "检查输入监听权限",
                    "body": "本地输入统计已开启但当前不可用。请确认系统已授予全局键盘、鼠标监听或无障碍权限，并检查依赖是否安装完整。",
                }
            )

        background_tracking = self._safe_plugin_call(
            "_get_background_activity_tracking_runtime_status",
            {},
        ) or {}
        background_enabled = bool(background_tracking.get("enabled"))
        background_active = bool(background_tracking.get("active"))
        background_interval = int(background_tracking.get("interval", 15) or 15)
        background_detail = (
            f"已启用，当前{'正在采样' if background_active else '等待插件空闲时接管'}，采样间隔 {background_interval} 秒。"
            if background_enabled
            else "未启用独立活动轨迹采集。"
        )
        add_check(
            self._build_health_check_entry(
                key="background_tracking",
                title="独立活动轨迹采集",
                status="ok",
                detail=background_detail,
            )
        )

        rule_summary = self._safe_plugin_call(
            "_get_activity_recognition_rule_summary",
            {},
        ) or {}
        invalid_lines = int(rule_summary.get("invalid_lines", 0) or 0)
        add_check(
            self._build_health_check_entry(
                key="recognition_rules",
                title="轨迹识别规则",
                status="warn" if invalid_lines > 0 else "ok",
                detail=(
                    f"已生效 {int(rule_summary.get('total_rules', 0) or 0)} 条规则，另有 {invalid_lines} 行格式未生效。"
                    if invalid_lines > 0
                    else f"已生效 {int(rule_summary.get('total_rules', 0) or 0)} 条规则。"
                ),
            )
        )
        if invalid_lines > 0:
            recommendations.append(
                {
                    "title": "修正未生效的识别规则",
                    "body": "有自定义规则因为格式不正确而没有生效。请确认每行都写成 app|关键词|显示名 或 site|关键词/域名|显示名。",
                }
            )

        try:
            window_titles = self.plugin._list_open_window_titles()
            window_count = len(window_titles or [])
            window_detail = (
                f"当前读取到 {window_count} 个窗口标题。"
                if window_count > 0
                else "当前没有读到窗口标题，可能是桌面环境、权限或当前桌面状态导致。"
            )
            add_check(
                self._build_health_check_entry(
                    key="window_probe",
                    title="窗口读取能力",
                    status="warn" if window_count <= 0 else "ok",
                    detail=window_detail,
                )
            )
        except Exception as e:
            add_check(
                self._build_health_check_entry(
                    key="window_probe",
                    title="窗口读取能力",
                    status="error",
                    detail=f"读取窗口失败：{e}",
                )
            )
            recommendations.append(
                {
                    "title": "检查窗口读取环境",
                    "body": "WebUI 自检在读取窗口列表时失败。请确认当前实例运行在有图形桌面的环境中，并检查相关桌面权限。",
                }
            )

        warning_count = sum(1 for item in checks if item.get("status") == "warn")
        error_count = sum(1 for item in checks if item.get("status") == "error")
        return {
            "status": overall_status,
            "checks": checks,
            "recommendations": recommendations,
            "warning_count": warning_count,
            "error_count": error_count,
        }

    @staticmethod
    def _build_empty_activity_period() -> dict[str, Any]:
        return {
            "work_time": "0分0秒",
            "play_time": "0分0秒",
            "other_time": "0分0秒",
            "total_time": "0分0秒",
            "display_total_time": "0分0秒",
            "work_seconds": 0,
            "play_seconds": 0,
            "other_seconds": 0,
            "total_seconds": 0,
            "display_total_seconds": 0,
            "effective_work_seconds": 0,
            "effective_work_time": "0分0秒",
            "effective_work_ratio": "0%",
            "idle_trimmed_seconds": 0,
            "idle_trimmed_time": "0分0秒",
            "has_input_estimate": False,
            "session_count": 0,
            "focus_session_count": 0,
            "focus_session_label": "0 段",
            "switch_count": 0,
            "switch_count_label": "0 次",
            "unique_window_count": 0,
            "work_ratio": "0%",
            "start_clock": "",
            "end_clock": "",
            "active_span_seconds": 0,
            "active_span_time": "0分0秒",
            "longest_focus_seconds": 0,
            "longest_focus_time": "0分0秒",
            "longest_focus_window": "",
            "longest_focus_scene": "",
            "top_window": {},
            "top_windows": [],
        }

    @staticmethod
    def _activity_bucket_key(activity_type: Any) -> str:
        label = str(activity_type or "").strip()
        if label == "工作":
            return "work"
        if label == "摸鱼":
            return "play"
        return "other"

    @classmethod
    def _activity_bucket_label(cls, activity_type: Any) -> str:
        normalized = str(activity_type or "").strip().lower()
        if normalized in {"work", "play", "other"}:
            bucket = normalized
        else:
            bucket = cls._activity_bucket_key(activity_type)
        if bucket == "work":
            return "工作"
        if bucket == "play":
            return "摸鱼"
        return "其他"

    @staticmethod
    def _get_activity_day_key(timestamp_value: float | int | None) -> str:
        try:
            timestamp = float(timestamp_value or 0)
        except Exception:
            timestamp = 0.0
        if timestamp <= 0:
            return ""
        return time.strftime("%Y-%m-%d", time.localtime(timestamp))

    @staticmethod
    def _mask_window_title(window_name: Any) -> str:
        raw_window = str(window_name or "").strip()
        if not raw_window:
            return "未命名窗口"

        for separator in (" - ", " — ", " | ", " · "):
            if separator in raw_window:
                parts = [part.strip() for part in raw_window.split(separator) if str(part).strip()]
                if len(parts) >= 2:
                    return f"已脱敏 · {parts[-1][:36]}"
        return "已脱敏窗口"

    def _normalize_activity_item_for_display(self, item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        clone = dict(item)
        window_text = str(clone.get("window", "") or "").strip()
        app_name = str(clone.get("app_name", "") or "").strip()
        site_domain = str(clone.get("site_domain", "") or "").strip()
        site_label = str(clone.get("site_label", "") or "").strip() or site_domain
        page_title = str(clone.get("page_title", "") or "").strip()
        if self._plugin_bool("mask_activity_window_titles"):
            clone["window"] = self._mask_window_title(window_text)
            if site_label and site_label != site_domain and not re.search(r"\.[a-z]{2,}$", site_label, flags=re.IGNORECASE):
                clone["site_label"] = "已脱敏网页"
            else:
                clone["site_label"] = site_label
            clone["page_title"] = "已脱敏页面" if page_title else ""
        else:
            clone["window"] = window_text or "未命名窗口"
            clone["site_label"] = site_label
            clone["page_title"] = page_title
        clone["app_name"] = app_name
        clone["site_domain"] = site_domain
        clone["resource_kind"] = str(clone.get("resource_kind", "") or ("site" if clone["site_label"] else "app"))
        clone["resource_label"] = str(
            clone.get("resource_label", "")
            or clone["page_title"]
            or clone["site_label"]
            or app_name
            or clone["window"]
            or "未命名活动"
        ).strip()
        raw_duration = max(0.0, float(clone.get("raw_duration", clone.get("duration", 0)) or 0))
        clone["duration"] = raw_duration
        clone["raw_duration"] = raw_duration
        return clone

    def _build_input_active_ranges(self) -> dict[str, list[tuple[float, float]]]:
        if not self._plugin_bool("enable_input_stats"):
            return {}

        daily = getattr(self.plugin, "input_stats_daily", {})
        if not isinstance(daily, dict):
            return {}

        grace_seconds = max(
            60,
            int(getattr(self.plugin, "ACTIVITY_INPUT_GRACE_SECONDS", 5 * 60) or 5 * 60),
        )
        raw_ranges: dict[str, list[tuple[float, float]]] = defaultdict(list)

        for day_key, payload in daily.items():
            minute_buckets = payload.get("minute_buckets", {}) if isinstance(payload, dict) else {}
            if not isinstance(minute_buckets, dict):
                continue
            for minute_key in minute_buckets.keys():
                try:
                    minute_dt = datetime.strptime(f"{day_key} {minute_key}", "%Y-%m-%d %H:%M")
                except Exception:
                    continue

                range_start = minute_dt.timestamp() - 60
                range_end = minute_dt.timestamp() + 60 + grace_seconds
                current_start = range_start
                while current_start < range_end:
                    current_day = datetime.fromtimestamp(current_start).date()
                    current_day_start = datetime.combine(current_day, datetime.min.time())
                    next_day_start = current_day_start + timedelta(days=1)
                    segment_end = min(range_end, next_day_start.timestamp())
                    raw_ranges[current_day.isoformat()].append((current_start, segment_end))
                    current_start = segment_end

        merged_ranges: dict[str, list[tuple[float, float]]] = {}
        for day_key, ranges in raw_ranges.items():
            ordered = sorted(
                [
                    (float(start or 0), float(end or 0))
                    for start, end in ranges
                    if float(end or 0) > float(start or 0)
                ],
                key=lambda item: item[0],
            )
            merged: list[list[float]] = []
            for start, end in ordered:
                if not merged or start > merged[-1][1]:
                    merged.append([start, end])
                else:
                    merged[-1][1] = max(merged[-1][1], end)
            merged_ranges[day_key] = [(start, end) for start, end in merged]

        return merged_ranges

    def _estimate_input_overlap_seconds(
        self,
        start_time: float,
        end_time: float,
        input_active_ranges: dict[str, list[tuple[float, float]]],
    ) -> float:
        interval_start = float(start_time or 0)
        interval_end = float(end_time or 0)
        if interval_end <= interval_start:
            return 0.0

        overlap_seconds = 0.0
        cursor_day = datetime.fromtimestamp(interval_start).date()
        last_day = datetime.fromtimestamp(max(interval_start, interval_end - 1)).date()

        while cursor_day <= last_day:
            day_start = datetime.combine(cursor_day, datetime.min.time()).timestamp()
            day_end = (datetime.combine(cursor_day, datetime.min.time()) + timedelta(days=1)).timestamp()
            segment_start = max(interval_start, day_start)
            segment_end = min(interval_end, day_end)
            if segment_end > segment_start:
                for active_start, active_end in input_active_ranges.get(cursor_day.isoformat(), []):
                    if active_end <= segment_start:
                        continue
                    if active_start >= segment_end:
                        break
                    overlap_seconds += max(
                        0.0,
                        min(segment_end, active_end) - max(segment_start, active_start),
                    )
            cursor_day += timedelta(days=1)

        return overlap_seconds

    def _estimate_activity_effective_seconds(
        self,
        item: dict[str, Any],
        input_active_ranges: dict[str, list[tuple[float, float]]],
    ) -> tuple[float, float, bool]:
        raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
        if raw_duration <= 0:
            return 0.0, 0.0, False
        if self._activity_bucket_key(item.get("type", "")) != "work":
            return raw_duration, 0.0, False
        if not input_active_ranges:
            return raw_duration, 0.0, False

        start_time = float(item.get("start_time", 0) or 0)
        end_time = float(item.get("end_time", 0) or 0)
        if start_time <= 0:
            return raw_duration, 0.0, False
        if end_time <= start_time:
            end_time = start_time + raw_duration

        effective_seconds = min(
            raw_duration,
            self._estimate_input_overlap_seconds(start_time, end_time, input_active_ranges),
        )
        idle_trimmed_seconds = max(0.0, raw_duration - effective_seconds)
        return effective_seconds, idle_trimmed_seconds, True

    def _prepare_activity_history_for_display(
        self,
        activity_history: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        prepared: list[dict[str, Any]] = []
        input_active_ranges = self._build_input_active_ranges()
        for item in activity_history or []:
            normalized = self._normalize_activity_item_for_display(item)
            if normalized is not None:
                effective_seconds, idle_trimmed_seconds, has_estimate = self._estimate_activity_effective_seconds(
                    normalized,
                    input_active_ranges,
                )
                normalized["effective_duration"] = float(
                    effective_seconds if has_estimate else normalized.get("raw_duration", normalized.get("duration", 0))
                )
                normalized["idle_trimmed_seconds"] = float(idle_trimmed_seconds if has_estimate else 0.0)
                normalized["has_input_estimate"] = bool(has_estimate)
                normalized["effective_duration_label"] = self._format_duration(
                    normalized.get("effective_duration", 0)
                )
                normalized["raw_duration_label"] = self._format_duration(
                    normalized.get("raw_duration", 0)
                )
                normalized["idle_trimmed_label"] = self._format_duration(
                    normalized.get("idle_trimmed_seconds", 0)
                )
                prepared.append(normalized)
        return prepared

    def _build_activity_session_digest(
        self,
        session: dict[str, Any],
        *,
        index: int,
    ) -> dict[str, Any] | None:
        bucket_seconds = session.get("bucket_seconds", {}) if isinstance(session.get("bucket_seconds", {}), dict) else {}
        total_seconds = int(session.get("active_seconds", 0) or 0)
        if total_seconds <= 0:
            return None

        dominant_bucket = max(
            ("work", "play", "other"),
            key=lambda key: float(bucket_seconds.get(key, 0) or 0),
        )
        work_seconds = int(bucket_seconds.get("work", 0) or 0)
        play_seconds = int(bucket_seconds.get("play", 0) or 0)
        switch_count = int(session.get("switch_count", 0) or 0)
        entry_count = int(session.get("entry_count", 0) or 0)
        gap_seconds = int(session.get("gap_from_previous", 0) or 0)
        work_ratio_value = round((work_seconds / total_seconds) * 100) if total_seconds > 0 else 0
        raw_total_seconds = int(session.get("raw_seconds", total_seconds) or total_seconds)
        idle_trimmed_seconds = int(session.get("idle_trimmed_seconds", 0) or 0)
        has_input_estimate = bool(session.get("has_input_estimate", False))

        window_seconds = session.get("window_seconds", {}) if isinstance(session.get("window_seconds", {}), dict) else {}
        if window_seconds:
            top_window, top_window_seconds = max(
                window_seconds.items(),
                key=lambda item: float(item[1] or 0),
            )
        else:
            top_window, top_window_seconds = "未命名窗口", 0

        scene_seconds = session.get("scene_seconds", {}) if isinstance(session.get("scene_seconds", {}), dict) else {}
        if scene_seconds:
            top_scene, _ = max(
                scene_seconds.items(),
                key=lambda item: float(item[1] or 0),
            )
        else:
            top_scene = ""

        app_seconds = session.get("app_seconds", {}) if isinstance(session.get("app_seconds", {}), dict) else {}
        if app_seconds:
            top_app, _ = max(
                app_seconds.items(),
                key=lambda item: float(item[1] or 0),
            )
        else:
            top_app = ""

        site_seconds = session.get("site_seconds", {}) if isinstance(session.get("site_seconds", {}), dict) else {}
        if site_seconds:
            top_site, _ = max(
                site_seconds.items(),
                key=lambda item: float(item[1] or 0),
            )
        else:
            top_site = ""

        source_seconds = session.get("source_seconds", {}) if isinstance(session.get("source_seconds", {}), dict) else {}
        if source_seconds:
            primary_capture_source, _ = max(
                source_seconds.items(),
                key=lambda item: float(item[1] or 0),
            )
        else:
            primary_capture_source = ""
        source_labels = [
            self._capture_source_label(source_key)
            for source_key in source_seconds.keys()
            if str(source_key or "").strip()
        ]
        source_mix_label = ""
        if source_labels:
            source_mix_label = (
                f"混合轨迹 · {source_labels[0]}为主"
                if len(source_labels) > 1
                else source_labels[0]
            )

        tone = ""
        state_label = "稳定推进"
        if dominant_bucket == "play" or play_seconds > work_seconds:
            state_label = "放松调整"
            tone = "warm"
        elif work_seconds >= self.FOCUS_SESSION_THRESHOLD_SECONDS:
            state_label = "深度专注"
            tone = "good"
        elif switch_count >= 6:
            state_label = "频繁切换"
            tone = "warm"
        elif total_seconds < 15 * 60:
            state_label = "短时处理"
        elif work_seconds > 0:
            state_label = "稳定推进"
            tone = "good"

        continuation_label = "这是今天记录到的第一个工作段"
        if index > 0 and gap_seconds > 0:
            continuation_label = f"与上一段间隔 {self._format_duration(gap_seconds)}"
        elif index > 0:
            continuation_label = "与上一段几乎无缝衔接"

        start_time = float(session.get("start_time", 0) or 0)
        end_time = float(session.get("end_time", 0) or 0)
        range_parts = [self._format_clock(start_time), self._format_clock(end_time)]
        effective_note = ""
        if has_input_estimate and idle_trimmed_seconds > 0:
            effective_note = f"按本地输入估算后，扣除了约 {self._format_duration(idle_trimmed_seconds)} 的空闲时间"

        summary_parts = [f"主窗口 {top_window}"]
        if top_app:
            summary_parts.append(f"主应用 {top_app}")
        if top_site:
            summary_parts.append(f"主站点 {top_site}")
        elif top_scene:
            summary_parts.append(f"主场景 {top_scene}")

        return {
            "range_label": " - ".join([part for part in range_parts if part]) or "时间未知",
            "duration": self._format_duration(total_seconds),
            "duration_seconds": total_seconds,
            "dominant_bucket": dominant_bucket,
            "raw_duration": self._format_duration(raw_total_seconds),
            "raw_duration_seconds": raw_total_seconds,
            "state_label": state_label,
            "tone": tone,
            "dominant_label": self._activity_bucket_label(dominant_bucket),
            "top_window": str(top_window or "未命名窗口"),
            "top_window_duration": self._format_duration(top_window_seconds),
            "top_app": str(top_app or ""),
            "top_site": str(top_site or ""),
            "top_scene": str(top_scene or ""),
            "summary": " · ".join(summary_parts),
            "primary_capture_source": str(primary_capture_source or ""),
            "primary_capture_source_label": self._capture_source_label(primary_capture_source),
            "source_mix_label": source_mix_label,
            "continuation_label": continuation_label,
            "work_ratio": f"{int(work_ratio_value)}%",
            "switch_count": switch_count,
            "switch_count_label": f"{switch_count} 次切换",
            "entry_count": entry_count,
            "entry_count_label": f"{entry_count} 段活动",
            "window_count": len(window_seconds),
            "window_count_label": f"{len(window_seconds)} 个窗口",
            "idle_trimmed_seconds": idle_trimmed_seconds,
            "idle_trimmed_time": self._format_duration(idle_trimmed_seconds),
            "has_input_estimate": has_input_estimate,
            "effective_note": effective_note,
        }

    def _build_activity_sessions(
        self,
        activity_history: list[dict[str, Any]] | None,
        *,
        day_key: str | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        valid_items: list[dict[str, Any]] = []
        for item in activity_history or []:
            if not isinstance(item, dict):
                continue
            duration = max(0.0, float(item.get("duration", 0) or 0))
            start_time = float(item.get("start_time", 0) or 0)
            if duration <= 0 or start_time <= 0:
                continue
            if day_key and self._get_activity_day_key(start_time) != day_key:
                continue
            valid_items.append(item)

        if not valid_items:
            return {
                "items": [],
                "count": 0,
                "count_label": "0 段",
                "focus_count": 0,
                "focus_count_label": "0 段",
                "fragmented_count": 0,
                "fragmented_count_label": "0 段",
                "total_time": "0分0秒",
                "raw_total_time": "0分0秒",
                "idle_trimmed_total_time": "0分0秒",
                "longest_duration": "0分0秒",
                "longest_state_label": "暂无",
                "has_input_estimate": False,
                "privacy_masked": self._plugin_bool("mask_activity_window_titles"),
                "privacy_label": (
                    "窗口标题已脱敏"
                    if self._plugin_bool("mask_activity_window_titles")
                    else "显示原始窗口标题"
                ),
            }

        sorted_items = sorted(
            valid_items,
            key=lambda item: float(item.get("start_time", 0) or 0),
        )
        sessions: list[dict[str, Any]] = []
        current_session: dict[str, Any] | None = None

        for item in sorted_items:
            start_time = float(item.get("start_time", 0) or 0)
            end_time = float(item.get("end_time", 0) or 0)
            raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
            duration = max(0.0, float(item.get("effective_duration", raw_duration) or raw_duration))
            effective_end = end_time if end_time > 0 else start_time
            bucket_key = self._activity_bucket_key(item.get("type", ""))
            scene = str(item.get("scene", "") or "").strip()
            window = str(item.get("window", "") or "").strip() or "未命名窗口"
            app_name = str(item.get("app_name", "") or "").strip() or "未识别应用"
            site_label = str(item.get("site_label", "") or "").strip()
            capture_source = str(item.get("capture_source", "") or "screen_analysis").strip() or "screen_analysis"
            idle_trimmed_seconds = max(0.0, float(item.get("idle_trimmed_seconds", 0) or 0))
            has_input_estimate = bool(item.get("has_input_estimate", False))
            marker = (bucket_key, scene, window)

            gap_seconds = 0
            split_session = current_session is None
            if current_session is not None:
                gap_seconds = max(0, int(start_time - float(current_session.get("end_time", 0) or 0)))
                last_bucket = str(current_session.get("last_bucket", "") or "")
                split_session = gap_seconds >= self.ACTIVITY_SESSION_GAP_SECONDS
                if not split_session and {bucket_key, last_bucket} == {"work", "play"}:
                    split_session = True
                if (
                    not split_session
                    and int(current_session.get("active_seconds", 0) or 0) >= 90 * 60
                    and gap_seconds >= 120
                    and marker != current_session.get("last_marker")
                ):
                    split_session = True

            if split_session:
                if current_session is not None:
                    digest = self._build_activity_session_digest(
                        current_session,
                        index=len(sessions),
                    )
                    if digest is not None:
                        sessions.append(digest)
                current_session = {
                    "start_time": start_time,
                    "end_time": effective_end,
                    "active_seconds": 0.0,
                    "raw_seconds": 0.0,
                    "bucket_seconds": {"work": 0.0, "play": 0.0, "other": 0.0},
                    "window_seconds": defaultdict(float),
                    "app_seconds": defaultdict(float),
                    "site_seconds": defaultdict(float),
                    "source_seconds": defaultdict(float),
                    "scene_seconds": defaultdict(float),
                    "entry_count": 0,
                    "switch_count": 0,
                    "last_bucket": "",
                    "last_marker": None,
                    "gap_from_previous": gap_seconds if len(sessions) > 0 else 0,
                    "idle_trimmed_seconds": 0.0,
                    "has_input_estimate": False,
                }

            if current_session is None:
                continue

            current_session["start_time"] = min(float(current_session.get("start_time", start_time) or start_time), start_time)
            current_session["end_time"] = max(float(current_session.get("end_time", effective_end) or effective_end), effective_end)
            current_session["active_seconds"] = float(current_session.get("active_seconds", 0) or 0) + duration
            current_session["raw_seconds"] = float(current_session.get("raw_seconds", 0) or 0) + raw_duration
            current_session["bucket_seconds"][bucket_key] += duration
            current_session["window_seconds"][window] += duration
            current_session["app_seconds"][app_name] += duration
            if site_label:
                current_session["site_seconds"][site_label] += duration
            if capture_source:
                current_session["source_seconds"][capture_source] += duration
            if scene:
                current_session["scene_seconds"][scene] += duration
            current_session["entry_count"] = int(current_session.get("entry_count", 0) or 0) + 1
            current_session["idle_trimmed_seconds"] = float(
                current_session.get("idle_trimmed_seconds", 0) or 0
            ) + idle_trimmed_seconds
            current_session["has_input_estimate"] = bool(
                current_session.get("has_input_estimate", False) or has_input_estimate
            )
            if current_session.get("last_marker") is not None and current_session.get("last_marker") != marker:
                current_session["switch_count"] = int(current_session.get("switch_count", 0) or 0) + 1
            current_session["last_bucket"] = bucket_key
            current_session["last_marker"] = marker

        if current_session is not None:
            digest = self._build_activity_session_digest(
                current_session,
                index=len(sessions),
            )
            if digest is not None:
                sessions.append(digest)

        total_time_seconds = sum(int(item.get("duration_seconds", 0) or 0) for item in sessions)
        raw_total_time_seconds = sum(int(item.get("raw_duration_seconds", item.get("duration_seconds", 0)) or 0) for item in sessions)
        idle_trimmed_total_seconds = sum(int(item.get("idle_trimmed_seconds", 0) or 0) for item in sessions)
        focus_count = sum(
            1
            for item in sessions
            if str(item.get("state_label", "") or "") == "深度专注"
        )
        fragmented_count = sum(
            1
            for item in sessions
            if str(item.get("state_label", "") or "") == "频繁切换"
        )
        longest_session = max(
            sessions,
            key=lambda item: int(item.get("duration_seconds", 0) or 0),
            default={},
        )
        display_items = sessions[-max(1, int(limit or 6)) :]

        return {
            "items": display_items,
            "count": len(sessions),
            "count_label": f"{len(sessions)} 段",
            "focus_count": focus_count,
            "focus_count_label": f"{focus_count} 段",
            "fragmented_count": fragmented_count,
            "fragmented_count_label": f"{fragmented_count} 段",
            "total_time": self._format_duration(total_time_seconds),
            "raw_total_time": self._format_duration(raw_total_time_seconds),
            "idle_trimmed_total_time": self._format_duration(idle_trimmed_total_seconds),
            "longest_duration": str(longest_session.get("duration", "0分0秒") or "0分0秒"),
            "longest_state_label": str(longest_session.get("state_label", "暂无") or "暂无"),
            "has_input_estimate": any(bool(item.get("has_input_estimate", False)) for item in sessions),
            "privacy_masked": self._plugin_bool("mask_activity_window_titles"),
            "privacy_label": (
                "窗口标题已脱敏"
                if self._plugin_bool("mask_activity_window_titles")
                else "显示原始窗口标题"
            ),
        }

    def _build_activity_pulse(
        self,
        *,
        today_summary: dict[str, Any],
        input_stats: dict[str, Any] | None,
        current_activity: dict[str, Any] | None,
        sessions: dict[str, Any] | None,
    ) -> dict[str, Any]:
        input_info = input_stats if isinstance(input_stats, dict) else {}
        current_info = current_activity if isinstance(current_activity, dict) else {}
        session_info = sessions if isinstance(sessions, dict) else {}

        presence_status = str(input_info.get("presence_status", "disabled") or "disabled")
        presence_label = str(input_info.get("presence_label", "未启用输入统计") or "未启用输入统计")
        presence_detail = str(input_info.get("presence_detail", "") or "")
        privacy_masked = self._plugin_bool("mask_activity_window_titles")

        current_type = str(current_info.get("type", "") or "").strip()
        current_scene = str(current_info.get("scene", "") or "").strip()
        current_window = str(current_info.get("window", "") or "").strip() or "未命名窗口"
        current_duration_seconds = max(0, int(current_info.get("duration", 0) or 0))
        current_title = " · ".join([part for part in [current_type, current_scene] if part]) or "当前活动"

        tone = ""
        label = presence_label or "等待样本"
        summary = "今天还没有形成足够的活动轨迹"
        detail = presence_detail or "开始使用插件后，这里会把活动、输入和工作段自动串起来。"

        if current_info:
            if current_type == "工作" and presence_status == "active":
                label = "专注中" if current_duration_seconds >= 15 * 60 else "处理中"
                tone = "good"
                summary = f"{current_title} 已持续 {self._format_duration(current_duration_seconds)}"
                detail = f"当前主要停留在《{current_window}》，{presence_detail or '最近仍有键鼠输入。'}"
            elif current_type == "摸鱼" and presence_status == "active":
                label = "放松中"
                tone = "warm"
                summary = f"{current_title} 已持续 {self._format_duration(current_duration_seconds)}"
                detail = f"当前停留在《{current_window}》，{presence_detail or '最近仍有键鼠输入。'}"
            elif presence_status in {"idle", "away"}:
                label = "挂起中" if presence_status == "idle" else "长时间离开"
                tone = "warm" if presence_status == "idle" else "muted"
                summary = f"{current_title} 还停留在前台，但最近没有新的输入"
                detail = f"当前窗口《{current_window}》，{presence_detail or '更像是暂时挂着没动。'}"
            else:
                label = "记录中"
                summary = f"{current_title} 已记录 {self._format_duration(current_duration_seconds)}"
                detail = presence_detail or "窗口活动已经在持续累计。"
        elif int(today_summary.get("total_seconds", 0) or 0) > 0:
            if presence_status == "active":
                label = "刚有活动"
                tone = "good"
            elif presence_status == "idle":
                label = "暂时离开"
                tone = "warm"
            elif presence_status == "away":
                label = "等待回来"
                tone = "muted"
            summary = (
                f"今天已累计 {today_summary.get('total_time', '0分0秒')}，形成 {session_info.get('count_label', '0 段')} 工作轨迹"
            )
            detail = presence_detail or "当前没有足够长的前台活动片段，但今天的轨迹已经开始成型。"

        meta = [
            f"输入状态：{presence_label}",
            f"今日专注：{today_summary.get('focus_session_label', '0 段')}",
            f"工作段：{session_info.get('count_label', '0 段')}",
            f"隐私：{'窗口脱敏中' if privacy_masked else '显示原始标题'}",
        ]
        if today_summary.get("has_input_estimate"):
            meta.insert(2, f"有效工作：{today_summary.get('effective_work_time', '0分0秒')}")
        if current_info:
            meta.insert(1, f"当前窗口：{current_window}")

        return {
            "label": label,
            "summary": summary,
            "detail": detail,
            "tone": tone,
            "meta": meta,
            "presence_label": presence_label,
            "presence_status": presence_status,
            "privacy_masked": privacy_masked,
        }

    def _build_activity_workspace_story(
        self,
        activity_history: list[dict[str, Any]] | None,
        *,
        today_summary: dict[str, Any] | None = None,
        input_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        today_key = datetime.now().date().isoformat()
        effective_today_summary = (
            today_summary
            if isinstance(today_summary, dict)
            else self._summarize_activity_period(
                [
                    item
                    for item in (activity_history or [])
                    if self._get_activity_day_key(item.get("start_time", 0)) == today_key
                ]
            )
        )
        effective_input_stats = input_stats if isinstance(input_stats, dict) else {}
        current_activity = self._normalize_activity_item_for_display(
            self._safe_plugin_call("_build_current_activity_snapshot", None)
        )
        sessions = self._build_activity_sessions(
            activity_history,
            day_key=today_key,
            limit=6,
        )
        pulse = self._build_activity_pulse(
            today_summary=effective_today_summary,
            input_stats=effective_input_stats,
            current_activity=current_activity,
            sessions=sessions,
        )
        return {
            "pulse": pulse,
            "sessions": sessions,
        }

    def _build_activity_surface_rows(
        self,
        groups: dict[str, dict[str, Any]],
        *,
        total_seconds: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for label, data in sorted(
            groups.items(),
            key=lambda item: (
                float(item[1].get("duration", 0) or 0),
                int(item[1].get("sessions", 0) or 0),
                float(item[1].get("last_seen", 0) or 0),
            ),
            reverse=True,
        )[: max(1, int(limit or self.ACTIVITY_SURFACE_LIMIT))]:
            dominant_bucket = max(
                ("work", "play", "other"),
                key=lambda key: float(data.get(key, 0) or 0),
            )
            duration_seconds = int(data.get("duration", 0) or 0)
            idle_trimmed = int(data.get("idle_trimmed_seconds", 0) or 0)
            rows.append(
                {
                    "label": str(label or "未命名"),
                    "duration": self._format_duration(duration_seconds),
                    "duration_seconds": duration_seconds,
                    "share": (
                        f"{round((duration_seconds / total_seconds) * 100)}%"
                        if total_seconds > 0
                        else "0%"
                    ),
                    "sessions": int(data.get("sessions", 0) or 0),
                    "type": self._activity_bucket_label(dominant_bucket),
                    "last_seen": self._format_clock(data.get("last_seen", 0)),
                    "domain": str(data.get("domain", "") or ""),
                    "idle_trimmed_time": self._format_duration(idle_trimmed),
                }
            )
        return rows

    def _build_activity_surface_trail(
        self,
        activity_history: list[dict[str, Any]] | None,
        *,
        day_key: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        valid_items: list[dict[str, Any]] = []
        for item in activity_history or []:
            if not isinstance(item, dict):
                continue
            raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
            start_time = float(item.get("start_time", 0) or 0)
            if raw_duration <= 0 or start_time <= 0:
                continue
            if day_key and self._get_activity_day_key(start_time) != day_key:
                continue
            valid_items.append(item)

        if not valid_items:
            return {
                "summary": {
                    "app_count": 0,
                    "app_count_label": "0 个应用",
                    "site_count": 0,
                    "site_count_label": "0 个站点",
                    "effective_time": "0分0秒",
                    "idle_trimmed_time": "0分0秒",
                    "estimate_enabled": False,
                    "estimate_label": "未启用空闲扣减",
                    "top_app": "",
                    "top_site": "",
                },
                "apps": [],
                "sites": [],
            }

        app_groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "duration": 0.0,
                "sessions": 0,
                "last_seen": 0.0,
                "work": 0.0,
                "play": 0.0,
                "other": 0.0,
                "idle_trimmed_seconds": 0.0,
                "domain": "",
            }
        )
        site_groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "duration": 0.0,
                "sessions": 0,
                "last_seen": 0.0,
                "work": 0.0,
                "play": 0.0,
                "other": 0.0,
                "idle_trimmed_seconds": 0.0,
                "domain": "",
            }
        )
        measured_total_seconds = 0.0
        idle_trimmed_total_seconds = 0.0
        estimate_enabled = False

        for item in valid_items:
            raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
            bucket_key = self._activity_bucket_key(item.get("type", ""))
            effective_duration = max(
                0.0,
                float(item.get("effective_duration", raw_duration) or raw_duration),
            )
            measure_duration = effective_duration if bucket_key == "work" else raw_duration
            idle_trimmed = max(0.0, float(item.get("idle_trimmed_seconds", 0) or 0))
            last_seen = float(item.get("end_time", 0) or item.get("start_time", 0) or 0)

            measured_total_seconds += measure_duration
            idle_trimmed_total_seconds += idle_trimmed
            estimate_enabled = bool(estimate_enabled or item.get("has_input_estimate", False))

            app_label = str(item.get("app_name", "") or "").strip() or "未识别应用"
            app_bucket = app_groups[app_label]
            app_bucket["duration"] += measure_duration
            app_bucket["sessions"] += 1
            app_bucket["last_seen"] = max(float(app_bucket["last_seen"] or 0), last_seen)
            app_bucket[bucket_key] += measure_duration
            app_bucket["idle_trimmed_seconds"] += idle_trimmed

            site_label = str(item.get("site_label", "") or "").strip()
            if site_label:
                site_bucket = site_groups[site_label]
                site_bucket["duration"] += measure_duration
                site_bucket["sessions"] += 1
                site_bucket["last_seen"] = max(float(site_bucket["last_seen"] or 0), last_seen)
                site_bucket[bucket_key] += measure_duration
                site_bucket["idle_trimmed_seconds"] += idle_trimmed
                site_bucket["domain"] = str(item.get("site_domain", "") or "").strip()

        app_rows = self._build_activity_surface_rows(
            app_groups,
            total_seconds=measured_total_seconds,
            limit=limit or self.ACTIVITY_SURFACE_LIMIT,
        )
        site_rows = self._build_activity_surface_rows(
            site_groups,
            total_seconds=measured_total_seconds,
            limit=limit or self.ACTIVITY_SURFACE_LIMIT,
        )

        return {
            "summary": {
                "app_count": len(app_groups),
                "app_count_label": f"{len(app_groups)} 个应用",
                "site_count": len(site_groups),
                "site_count_label": f"{len(site_groups)} 个站点",
                "effective_time": self._format_duration(measured_total_seconds),
                "idle_trimmed_time": self._format_duration(idle_trimmed_total_seconds),
                "estimate_enabled": estimate_enabled,
                "estimate_label": (
                    "已按本地输入扣除了长时间空闲"
                    if estimate_enabled
                    else "当前按原始窗口停留时长统计"
                ),
                "top_app": str(app_rows[0].get("label", "") if app_rows else ""),
                "top_site": str(site_rows[0].get("label", "") if site_rows else ""),
            },
            "apps": app_rows,
            "sites": site_rows,
        }

    def _summarize_activity_period(
        self,
        activity_history: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        valid_items: list[dict[str, Any]] = []
        for item in activity_history or []:
            if not isinstance(item, dict):
                continue
            duration = max(0.0, float(item.get("duration", 0) or 0))
            if duration <= 0:
                continue
            valid_items.append(item)

        if not valid_items:
            return self._build_empty_activity_period()

        sorted_items = sorted(
            valid_items,
            key=lambda x: float(x.get("start_time", 0) or 0),
        )
        totals = {"work": 0.0, "play": 0.0, "other": 0.0}
        display_totals = {"work": 0.0, "play": 0.0, "other": 0.0}
        unique_windows: set[str] = set()
        switch_count = 0
        focus_session_count = 0
        effective_work_seconds = 0.0
        idle_trimmed_seconds = 0.0
        has_input_estimate = False
        longest_focus: dict[str, Any] = {
            "seconds": 0.0,
            "window": "",
            "scene": "",
        }
        earliest_start = 0.0
        latest_end = 0.0
        previous_marker: tuple[str, str, str] | None = None
        window_groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "duration": 0.0,
                "sessions": 0,
                "last_seen": 0.0,
                "work": 0.0,
                "play": 0.0,
                "other": 0.0,
            }
        )

        for item in sorted_items:
            raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
            effective_duration = max(
                0.0,
                float(item.get("effective_duration", raw_duration) or raw_duration),
            )
            start_ts = float(item.get("start_time", 0) or 0)
            end_ts = float(item.get("end_time", 0) or 0)
            effective_end = end_ts if end_ts > 0 else start_ts
            activity_type = str(item.get("type", "") or "").strip()
            scene = str(item.get("scene", "") or "").strip()
            window = str(item.get("window", "") or "").strip() or "未命名窗口"
            bucket_key = self._activity_bucket_key(activity_type)
            measure_duration = effective_duration if bucket_key == "work" else raw_duration

            totals[bucket_key] += raw_duration
            display_totals[bucket_key] += measure_duration
            unique_windows.add(window)

            if earliest_start <= 0 or (start_ts > 0 and start_ts < earliest_start):
                earliest_start = start_ts
            if effective_end > latest_end:
                latest_end = effective_end

            marker = (bucket_key, scene, window)
            if previous_marker is not None and marker != previous_marker:
                switch_count += 1
            previous_marker = marker

            if bucket_key == "work":
                effective_work_seconds += effective_duration
                idle_trimmed_seconds += max(
                    0.0,
                    float(item.get("idle_trimmed_seconds", raw_duration - effective_duration) or 0),
                )
                has_input_estimate = bool(
                    has_input_estimate or item.get("has_input_estimate", False)
                )
                if effective_duration >= self.FOCUS_SESSION_THRESHOLD_SECONDS:
                    focus_session_count += 1
                if effective_duration > float(longest_focus["seconds"] or 0):
                    longest_focus = {
                        "seconds": effective_duration,
                        "window": window,
                        "scene": scene,
                    }

            window_bucket = window_groups[window]
            window_bucket["duration"] += measure_duration
            window_bucket["sessions"] += 1
            window_bucket["last_seen"] = max(
                float(window_bucket["last_seen"] or 0),
                float(effective_end or 0),
            )
            window_bucket[bucket_key] += measure_duration

        total_seconds = sum(totals.values())
        display_total_seconds = sum(display_totals.values())
        active_span_seconds = max(0.0, latest_end - earliest_start) if earliest_start > 0 and latest_end > 0 else 0.0

        top_windows = []
        for window_name, data in sorted(
            window_groups.items(),
            key=lambda item: (
                float(item[1]["duration"] or 0),
                int(item[1]["sessions"] or 0),
                float(item[1]["last_seen"] or 0),
            ),
            reverse=True,
        )[: self.TOP_WINDOW_LIMIT]:
            dominant_bucket = max(
                ("work", "play", "other"),
                key=lambda key: float(data.get(key, 0) or 0),
            )
            top_windows.append(
                {
                    "window": window_name,
                    "duration": self._format_duration(data["duration"]),
                    "duration_seconds": int(data["duration"] or 0),
                    "sessions": int(data["sessions"] or 0),
                    "share": (
                        f"{round((float(data['duration'] or 0) / display_total_seconds) * 100)}%"
                        if display_total_seconds > 0
                        else "0%"
                    ),
                    "type": self._activity_bucket_label(dominant_bucket),
                }
            )

        top_window = dict(top_windows[0]) if top_windows else {}

        return {
            "work_time": self._format_duration(totals["work"]),
            "play_time": self._format_duration(totals["play"]),
            "other_time": self._format_duration(totals["other"]),
            "total_time": self._format_duration(total_seconds),
            "display_total_time": self._format_duration(display_total_seconds),
            "work_seconds": int(totals["work"]),
            "play_seconds": int(totals["play"]),
            "other_seconds": int(totals["other"]),
            "total_seconds": int(total_seconds),
            "display_total_seconds": int(display_total_seconds),
            "effective_work_seconds": int(effective_work_seconds),
            "effective_work_time": self._format_duration(effective_work_seconds),
            "idle_trimmed_seconds": int(idle_trimmed_seconds),
            "idle_trimmed_time": self._format_duration(idle_trimmed_seconds),
            "has_input_estimate": has_input_estimate,
            "session_count": len(sorted_items),
            "focus_session_count": int(focus_session_count),
            "focus_session_label": f"{int(focus_session_count)} 段",
            "switch_count": int(switch_count),
            "switch_count_label": f"{int(switch_count)} 次",
            "unique_window_count": len(unique_windows),
            "work_ratio": (
                f"{round((totals['work'] / total_seconds) * 100)}%"
                if total_seconds > 0
                else "0%"
            ),
            "effective_work_ratio": (
                f"{round((effective_work_seconds / display_total_seconds) * 100)}%"
                if display_total_seconds > 0
                else "0%"
            ),
            "start_clock": self._format_clock(earliest_start),
            "end_clock": self._format_clock(latest_end),
            "active_span_seconds": int(active_span_seconds),
            "active_span_time": self._format_duration(active_span_seconds),
            "longest_focus_seconds": int(longest_focus["seconds"] or 0),
            "longest_focus_time": self._format_duration(longest_focus["seconds"]),
            "longest_focus_window": str(longest_focus["window"] or ""),
            "longest_focus_scene": str(longest_focus["scene"] or ""),
            "top_window": top_window,
            "top_windows": top_windows,
        }

    def _build_activity_trend(
        self,
        activity_history: list[dict[str, Any]] | None,
        *,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        trend_days = max(1, int(days or self.ACTIVITY_TREND_DAYS))
        today = datetime.now().date()
        day_list = [
            today - timedelta(days=offset)
            for offset in reversed(range(trend_days))
        ]
        buckets: dict[str, dict[str, Any]] = {
            day.isoformat(): {
                "date": day.isoformat(),
                "raw_work_seconds": 0,
                "work_seconds": 0,
                "play_seconds": 0,
                "other_seconds": 0,
                "effective_work_seconds": 0,
                "idle_trimmed_seconds": 0,
                "display_total_seconds": 0,
                "has_input_estimate": False,
                "session_count": 0,
            }
            for day in day_list
        }

        for item in activity_history or []:
            if not isinstance(item, dict):
                continue
            day_key = self._get_activity_day_key(item.get("start_time", 0))
            if not day_key or day_key not in buckets:
                continue
            raw_duration = max(
                0.0,
                float(item.get("raw_duration", item.get("duration", 0)) or 0),
            )
            if raw_duration <= 0:
                continue
            bucket_key = self._activity_bucket_key(item.get("type", ""))
            effective_duration = max(
                0.0,
                float(item.get("effective_duration", raw_duration) or raw_duration),
            )
            measure_duration = effective_duration if bucket_key == "work" else raw_duration
            day_bucket = buckets[day_key]
            if bucket_key == "work":
                day_bucket["raw_work_seconds"] += int(raw_duration)
                day_bucket["effective_work_seconds"] += int(effective_duration)
                day_bucket["idle_trimmed_seconds"] += int(
                    max(
                        0.0,
                        float(
                            item.get(
                                "idle_trimmed_seconds",
                                raw_duration - effective_duration,
                            )
                            or 0
                        ),
                    )
                )
                day_bucket["has_input_estimate"] = bool(
                    day_bucket["has_input_estimate"]
                    or item.get("has_input_estimate", False)
                )
            day_bucket[f"{bucket_key}_seconds"] += int(measure_duration)
            day_bucket["display_total_seconds"] += int(measure_duration)
            day_bucket["session_count"] += 1

        rows: list[dict[str, Any]] = []
        yesterday = today - timedelta(days=1)
        for day in day_list:
            day_key = day.isoformat()
            bucket = buckets[day_key]
            raw_total_seconds = (
                int(bucket["raw_work_seconds"])
                + int(bucket["play_seconds"])
                + int(bucket["other_seconds"])
            )
            display_total_seconds = (
                int(bucket["display_total_seconds"])
                if int(bucket["display_total_seconds"] or 0) > 0
                else raw_total_seconds
            )
            has_input_estimate = bool(bucket["has_input_estimate"])
            if day == today:
                label = "今天"
            elif day == yesterday:
                label = "昨天"
            else:
                label = day.strftime("%m-%d")
            rows.append(
                {
                    "date": day_key,
                    "label": label,
                    "work_seconds": int(bucket["work_seconds"]),
                    "raw_work_seconds": int(bucket["raw_work_seconds"]),
                    "play_seconds": int(bucket["play_seconds"]),
                    "other_seconds": int(bucket["other_seconds"]),
                    "total_seconds": int(raw_total_seconds),
                    "total_time": self._format_duration(
                        display_total_seconds if has_input_estimate else raw_total_seconds
                    ),
                    "raw_total_seconds": int(raw_total_seconds),
                    "raw_total_time": self._format_duration(raw_total_seconds),
                    "display_total_seconds": int(display_total_seconds),
                    "display_total_time": self._format_duration(display_total_seconds),
                    "effective_work_seconds": int(bucket["effective_work_seconds"]),
                    "effective_work_time": self._format_duration(
                        bucket["effective_work_seconds"]
                    ),
                    "idle_trimmed_seconds": int(bucket["idle_trimmed_seconds"]),
                    "idle_trimmed_time": self._format_duration(
                        bucket["idle_trimmed_seconds"]
                    ),
                    "has_input_estimate": has_input_estimate,
                    "work_ratio": (
                        f"{round((int(bucket['raw_work_seconds']) / raw_total_seconds) * 100)}%"
                        if raw_total_seconds > 0
                        else "0%"
                    ),
                    "effective_work_ratio": (
                        f"{round((int(bucket['effective_work_seconds']) / display_total_seconds) * 100)}%"
                        if display_total_seconds > 0
                        else "0%"
                    ),
                    "session_count": int(bucket["session_count"]),
                }
            )
        return rows

    def _summarize_activity_capture_sources(
        self,
        activity_history: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        source_seconds: dict[str, float] = defaultdict(float)
        source_count: dict[str, int] = defaultdict(int)
        total_seconds = 0.0

        for item in activity_history or []:
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("capture_source", "") or "screen_analysis").strip() or "screen_analysis"
            duration = max(
                0.0,
                float(item.get("effective_duration", item.get("duration", 0)) or 0),
            )
            if duration <= 0:
                continue
            source_seconds[source_key] += duration
            source_count[source_key] += 1
            total_seconds += duration

        rows = [
            {
                "key": source_key,
                "label": self._capture_source_label(source_key),
                "duration_seconds": int(seconds),
                "duration": self._format_duration(seconds),
                "count": int(source_count.get(source_key, 0) or 0),
                "share": (
                    f"{round((seconds / total_seconds) * 100)}%"
                    if total_seconds > 0
                    else "0%"
                ),
            }
            for source_key, seconds in sorted(
                source_seconds.items(),
                key=lambda item: float(item[1] or 0),
                reverse=True,
            )
        ]

        if not rows:
            return {
                "items": [],
                "summary": "当前还没有足够的轨迹样本来说明来源分布。",
            }

        primary = rows[0]
        if len(rows) == 1:
            summary = f"当前轨迹主要来自 {primary['label']}，累计 {primary['duration']}。"
        else:
            summary = (
                f"当前是混合轨迹，主要来源为 {primary['label']}（{primary['share']}），"
                f"其余来源会一起补充回顾视角。"
            )
        return {"items": rows, "summary": summary}

    def _build_activity_review(
        self,
        *,
        today_summary: dict[str, Any],
        total_summary: dict[str, Any],
        yesterday_summary: dict[str, Any],
        activity_history: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        use_today = int(today_summary.get("total_seconds", 0) or 0) > 0
        active_summary = today_summary if use_today else total_summary
        range_label = "今天" if use_today else "累计"
        source_summary = self._summarize_activity_capture_sources(activity_history)

        longest_focus_value = active_summary.get("longest_focus_time", "0分0秒")
        longest_focus_detail = "还没有形成足够长的工作片段"
        if int(active_summary.get("longest_focus_seconds", 0) or 0) > 0:
            detail_parts = []
            longest_focus_window = str(active_summary.get("longest_focus_window", "") or "").strip()
            longest_focus_scene = str(active_summary.get("longest_focus_scene", "") or "").strip()
            if longest_focus_window:
                detail_parts.append(longest_focus_window)
            if longest_focus_scene:
                detail_parts.append(longest_focus_scene)
            longest_focus_detail = " · ".join(detail_parts) if detail_parts else "来自最近的工作片段"

        top_window = active_summary.get("top_window", {}) if isinstance(active_summary.get("top_window", {}), dict) else {}
        top_window_name = str(top_window.get("window", "") or "").strip() or "暂无"
        top_window_detail = (
            f"累计 {top_window.get('duration', '0分0秒')} · {top_window.get('share', '0%')}"
            if top_window
            else "还没有聚焦出明显主力窗口"
        )
        effective_work_detail = (
            f"已扣除约 {active_summary.get('idle_trimmed_time', '0分0秒')} 的长时间空闲"
            if active_summary.get("has_input_estimate")
            else "当前仍按原始窗口停留时长统计"
        )

        summary_cards = [
            {
                "label": "最长专注",
                "value": longest_focus_value,
                "detail": longest_focus_detail,
                "tone": "good",
            },
            {
                "label": "专注段数",
                "value": active_summary.get("focus_session_label", "0 段"),
                "detail": f"单段至少 {self.FOCUS_SESSION_THRESHOLD_SECONDS // 60} 分钟",
                "tone": "warm",
            },
            {
                "label": "上下文切换",
                "value": active_summary.get("switch_count_label", "0 次"),
                "detail": f"{range_label}共 {active_summary.get('session_count', 0)} 段活动",
                "tone": "",
            },
            {
                "label": "有效工作",
                "value": active_summary.get("effective_work_time", active_summary.get("work_time", "0分0秒")),
                "detail": effective_work_detail,
                "tone": "good" if active_summary.get("has_input_estimate") else "",
            },
            {
                "label": "主力窗口",
                "value": top_window_name,
                "detail": top_window_detail,
                "tone": "",
            },
        ]

        insights: list[str] = []
        if int(today_summary.get("total_seconds", 0) or 0) <= 0:
            insights.append("今天还没有形成足够活动样本，先让插件继续积累一会儿数据。")
        else:
            insights.append(
                f"今天累计记录 {today_summary.get('total_time', '0分0秒')}，工作占比 {today_summary.get('work_ratio', '0%')}。"
            )
            if today_summary.get("has_input_estimate"):
                insights.append(
                    f"按本地输入估算后，今天的有效工作时间约为 {today_summary.get('effective_work_time', '0分0秒')}，扣除了 {today_summary.get('idle_trimmed_time', '0分0秒')} 的长时间空闲。"
                )
            if int(today_summary.get("longest_focus_seconds", 0) or 0) > 0:
                focus_window = str(today_summary.get("longest_focus_window", "") or "").strip() or "当前主任务"
                insights.append(
                    f"最久的一段专注发生在《{focus_window}》，持续 {today_summary.get('longest_focus_time', '0分0秒')}。"
                )
            if str(today_summary.get("start_clock", "") or "").strip() and str(today_summary.get("end_clock", "") or "").strip():
                insights.append(
                    f"今天的活跃跨度是 {today_summary.get('active_span_time', '0分0秒')}，从 {today_summary.get('start_clock')} 到 {today_summary.get('end_clock')}。"
                )
            if int(today_summary.get("switch_count", 0) or 0) > 0:
                insights.append(
                    f"今天发生了 {today_summary.get('switch_count', 0)} 次上下文切换，当前节奏偏 {'稳定' if int(today_summary.get('switch_count', 0) or 0) <= 8 else '碎片化'}。"
                )
            delta_work_seconds = int(today_summary.get("work_seconds", 0) or 0) - int(yesterday_summary.get("work_seconds", 0) or 0)
            if int(yesterday_summary.get("total_seconds", 0) or 0) > 0:
                if delta_work_seconds > 0:
                    insights.append(
                        f"和昨天相比，今天多投入了 {self._format_duration(delta_work_seconds)} 工作时间。"
                    )
                elif delta_work_seconds < 0:
                    insights.append(
                        f"和昨天相比，今天少投入了 {self._format_duration(abs(delta_work_seconds))} 工作时间。"
                    )
                else:
                    insights.append("和昨天相比，今天的工作投入时长基本持平。")

        methodology = [
            {
                "title": "有效工作口径",
                "detail": (
                    f"当前已按本地输入估算，把长时间无键鼠输入的空闲从工作时长里扣除了 {active_summary.get('idle_trimmed_time', '0分0秒')}。"
                    if active_summary.get("has_input_estimate")
                    else "当前还没有使用本地输入统计修正工作时长，因此工作时间仍按窗口停留时长计算。"
                ),
            },
            {
                "title": "工作段怎么聚合",
                "detail": f"相邻活动间隔小于 {self.ACTIVITY_SESSION_GAP_SECONDS // 60} 分钟且节奏连续时，会被合并成同一段工作轨迹；明显跨到娱乐或切换过久时会拆成新段。",
            },
            {
                "title": "轨迹来源",
                "detail": str(source_summary.get("summary", "") or "当前还没有足够的轨迹样本来说明来源分布。"),
            },
        ]

        return {
            "range_label": range_label,
            "summary_cards": summary_cards,
            "insights": insights[:4],
            "methodology": methodology,
            "capture_sources": source_summary.get("items", []),
            "top_windows": active_summary.get("top_windows", []),
            "trend": self._build_activity_trend(activity_history, days=self.ACTIVITY_TREND_DAYS),
        }

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
            if scene_name.lower() in {"unknown", "none", "null"} or scene_name == "未知":
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
                    "trigger_reason": str(obs.get("trigger_reason", "") or "").strip(),
                    "material_kind": str(obs.get("material_kind", "") or "").strip(),
                    "analysis_material_kind": str(obs.get("analysis_material_kind", "") or "").strip(),
                    "sampling_strategy": str(obs.get("sampling_strategy", "") or "").strip(),
                    "recognition_summary": str(obs.get("recognition_summary", "") or "").strip(),
                    "reply_preview": str(obs.get("reply_preview", "") or "").strip(),
                    "frame_count": int(obs.get("frame_count", 0) or 0),
                    "frame_labels": list(obs.get("frame_labels", []) or []),
                    "used_full_video": bool(obs.get("used_full_video", False)),
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
                    "summary": f"出现 {int(data.get('usage_count', data.get('count', 0)) or 0)} 次",
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

        episodic_memories = long_term_memory.get("episodic_memories", [])
        for item in episodic_memories:
            if not isinstance(item, dict):
                continue
            title = (
                str(item.get("active_window", "") or "").strip()
                or str(item.get("scene", "") or "").strip()
                or "近期片段"
            )
            memories.append(
                {
                    "category": "episodes",
                    "category_label": "情节记忆",
                    "title": title,
                    "summary": str(item.get("summary", "") or "").strip() or "暂无摘要",
                    "meta": (
                        f"最近出现: {item.get('last_seen', '未知')} | "
                        f"累计 {int(item.get('count', 0) or 0)} 次"
                    ),
                    "priority": item.get("priority", 0),
                    "last_date": item.get("last_seen", ""),
                }
            )

        focus_patterns = long_term_memory.get("focus_patterns", {})
        for _, item in focus_patterns.items():
            if not isinstance(item, dict):
                continue
            title = (
                str(item.get("scene", "") or "").strip()
                or str(item.get("active_window", "") or "").strip()
                or "重复关注点"
            )
            memories.append(
                {
                    "category": "focus_patterns",
                    "category_label": "重复关注点",
                    "title": title,
                    "summary": str(item.get("summary", "") or "").strip() or "暂无摘要",
                    "meta": (
                        f"最近出现: {item.get('last_seen', '未知')} | "
                        f"累计 {int(item.get('count', 0) or 0)} 次"
                    ),
                    "priority": item.get("priority", 0),
                    "last_date": item.get("last_seen", ""),
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
                "version": self.APP_VERSION,
                "plugin_version": self.APP_VERSION
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
            logger.error(f"读取配置 schema 失败: {e}")
        return {}

    def _build_settings_payload(self) -> dict[str, Any]:
        schema = self._load_settings_schema()
        values = {}

        for key in schema.keys():
            if key == "screen_recognition_mode":
                values[key] = bool(self.plugin._use_screen_recording_mode())
            elif self._is_sensitive_setting_key(key):
                values[key] = ""
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
                    "webui.password": "",
                    "webui.session_timeout": int(getattr(webui_config, "session_timeout", 3600) or 3600),
                    "webui.allow_external_api": bool(getattr(webui_config, "allow_external_api", False)),
                }
            )

        for key in tuple(schema.keys()) + ("webui.password",):
            if not self._is_sensitive_setting_key(key):
                continue

            if key.startswith("webui."):
                attr_name = key.split(".", 1)[1]
                actual_value = getattr(webui_config, attr_name, "") if webui_config else ""
            else:
                actual_value = getattr(self.plugin, key, "")

            field_meta = schema.get(key)
            if isinstance(field_meta, dict):
                schema[key] = {
                    **field_meta,
                    "sensitive": True,
                    "configured": bool(str(actual_value or "").strip()),
                }

        groups = [
            {
                "id": "persona",
                "title": "人格与对话",
                "description": "先决定 Bot 是谁、怎么说话，以及用户主动求助时它该不该介入识屏。",
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
                "description": "决定多久看一次、怎么触发、用截图还是录屏，以及是否按窗口自动开陪伴。",
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
                    "window_companion_reattach_grace_seconds",
                ],
            },
            {
                "id": "vision",
                "title": "识屏与视觉",
                "description": "配置识屏素材从哪里来、先走哪条视觉链路，以及模型该重点看什么。",
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
                "description": "管理日记生成、自动撤回、长期学习和陪伴式记忆的保留方式。",
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
                "description": "放麦克风、天气、电量内存提醒、主动消息目标和定时提示这类环境感知能力。",
                "fields": [
                    "enable_mic_monitor",
                    "mic_threshold",
                    "mic_check_interval",
                    "memory_threshold",
                    "battery_threshold",
                    "weather_api_key",
                    "weather_city",
                    "admin_qq",
                    "proactive_target",
                    "custom_tasks",
                    "debug",
                ],
            },
            {
                "id": "analytics",
                "title": "本地统计",
                "description": "管理键鼠输入统计、活动轨迹、离开自动挂起和活动页隐私保护。",
                "fields": [
                    "enable_background_activity_tracking",
                    "background_activity_tracking_interval",
                    "enable_input_stats",
                    "input_stats_flush_interval",
                    "enable_away_auto_pause",
                    "away_auto_pause_threshold",
                    "away_long_notice_threshold",
                    "mask_activity_window_titles",
                    "activity_recognition_rules",
                ],
            },
            {
                "id": "webui",
                "title": "WebUI",
                "description": "配置 WebUI 的访问地址、登录保护、会话时长，以及是否对外开放分析接口。",
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
                "hint": "总开关。关闭后不会启动网页管理界面，也无法通过浏览器查看日记、活动和配置页。",
                "default": False,
            },
            "webui.host": {
                "description": "WebUI 监听地址",
                "type": "string",
                "hint": "只在本机访问时建议填 127.0.0.1；需要让局域网内其他设备访问时再填 0.0.0.0。",
                "default": "0.0.0.0",
            },
            "webui.port": {
                "description": "WebUI 端口",
                "type": "int",
                "hint": "默认 6314。修改后访问地址会变成新端口；如果端口被占用，WebUI 可能会自动回退到别的可用端口。",
                "default": 6314,
                "min": 1024,
                "max": 65535,
            },
            "webui.auth_enabled": {
                "description": "启用访问密码",
                "type": "bool",
                "hint": "建议保持开启。关闭后，只要能访问到这个地址的人都可以直接打开 WebUI。",
                "default": True,
            },
            "webui.password": {
                "description": "WebUI 密码",
                "type": "password",
                "hint": "留空时会在首次启动时自动生成随机密码；手动填写后，浏览器登录和外部 API 鉴权都会使用这个值。",
                "default": "",
            },
            "webui.session_timeout": {
                "description": "会话过期时间",
                "type": "int",
                "hint": "单位为秒。时间越短越安全，但你会更频繁地重新登录；默认 3600 秒通常够用。",
                "default": 3600,
                "min": 300,
                "max": 604800,
            },
            "webui.allow_external_api": {
                "description": "允许外部 API 调用",
                "type": "bool",
                "hint": "开启后，外部服务可通过 `/api/analyze` 等接口调用识图分析。除非你明确要接别的服务，否则建议保持关闭。",
                "default": False,
            },
        }

        schema.update(webui_schema)
        if "webui.password" in schema:
            schema["webui.password"] = {
                **schema["webui.password"],
                "sensitive": True,
                "configured": bool(str(getattr(webui_config, "password", "") if webui_config else "").strip()),
            }
        schema.update(
            {
                "enable_window_companion": {
                    "description": "开启窗口自动陪伴",
                    "type": "bool",
                    "hint": "命中的窗口一出现就自动开始陪伴，窗口消失后再自动结束。适合常驻游戏、IDE、视频播放器这类固定场景。",
                    "default": False,
                },
                "window_companion_targets": {
                    "description": "窗口陪伴目标",
                    "type": "text",
                    "hint": "每行一个窗口关键字；也支持“关键字|补充提示词”。例如：`Cursor|重点关注报错和下一步`，适合给不同窗口加不同陪伴重点。",
                    "default": "",
                },
                "window_companion_check_interval": {
                    "description": "窗口检查间隔",
                    "type": "int",
                    "hint": "后台每隔多少秒检查一次目标窗口是否出现或关闭。这里只影响窗口命中速度；窗口陪伴真正发消息时，仍继承当前生效的触发间隔和触发概率。",
                    "default": 5,
                    "min": 2,
                    "max": 300,
                },
                "window_companion_reattach_grace_seconds": {
                    "description": "窗口重连宽限期",
                    "type": "int",
                    "hint": "目标窗口短暂关闭后，最多等待多久再判定为真正结束。适合游戏结算、重开、重新匹配这类会短暂销毁窗口的场景。",
                    "default": 300,
                    "min": 10,
                    "max": 3600,
                },
                "enable_input_stats": {
                    "description": "启用本地输入统计",
                    "type": "bool",
                    "hint": "开启后会监听全局键盘和鼠标输入，用来补充工作轨迹、活跃度和离开判断。系统层面可能仍需授予输入监听权限。",
                    "default": False,
                },
                "enable_background_activity_tracking": {
                    "description": "启用独立活动轨迹采集",
                    "type": "bool",
                    "hint": "开启后，即使没有启动自动观察，也会按固定间隔记录当前活动窗口，并尽量拆出应用 / 网站 / 页面轨迹。自动观察运行中会继续优先使用识屏轨迹。",
                    "default": False,
                },
                "background_activity_tracking_interval": {
                    "description": "独立轨迹采样间隔",
                    "type": "int",
                    "hint": "后台每隔多少秒采样一次当前活动窗口。值越小越细，值越大越省资源。",
                    "default": 15,
                    "min": 5,
                    "max": 3600,
                    "condition": {
                        "enable_background_activity_tracking": True,
                    },
                },
                "input_stats_flush_interval": {
                    "description": "输入统计落盘间隔",
                    "type": "int",
                    "hint": "每隔多少秒把输入统计写入本地 JSON。值越小越实时，值越大越省磁盘 IO。",
                    "default": 60,
                    "min": 10,
                    "max": 3600,
                },
                "enable_away_auto_pause": {
                    "description": "离开电脑时自动挂起观察",
                    "type": "bool",
                    "hint": "仅在启用本地输入统计后生效。长时间没有键鼠输入时，自动观察会先安静下来；检测到你回来后再恢复。",
                    "default": False,
                    "condition": {"enable_input_stats": True},
                },
                "away_auto_pause_threshold": {
                    "description": "自动挂起阈值",
                    "type": "int",
                    "hint": "连续多久没有输入后，认为你暂时离开电脑，并挂起自动观察。",
                    "default": 1200,
                    "min": 300,
                    "max": 14400,
                    "condition": {
                        "enable_input_stats": True,
                        "enable_away_auto_pause": True,
                    },
                },
                "away_long_notice_threshold": {
                    "description": "长时间离开提醒阈值",
                    "type": "int",
                    "hint": "离开时间超过这个阈值时，只额外发一次轻量提醒，然后继续安静等待，不会持续刷消息。",
                    "default": 3600,
                    "min": 600,
                    "max": 86400,
                    "condition": {
                        "enable_input_stats": True,
                        "enable_away_auto_pause": True,
                    },
                },
                "mask_activity_window_titles": {
                    "description": "活动页窗口标题脱敏",
                    "type": "bool",
                    "hint": "开启后，活动统计、主力窗口和工作轨迹里的窗口标题会统一脱敏，整体更偏向隐私保护的活动回顾体验。",
                    "default": False,
                },
                "activity_recognition_rules": {
                    "description": "活动识别自定义规则",
                    "type": "text",
                    "hint": "每行一条，格式为 app|关键词|显示名 或 site|关键词/域名|显示名。支持 # 注释，例如：app|cursor.exe|Cursor 或 site|docs.company.com|公司文档。",
                    "default": "",
                },
            }
        )

        def patch_setting_meta(
            key: str,
            *,
            advanced: bool | None = None,
            condition: dict[str, Any] | None = None,
        ) -> None:
            field_meta = schema.get(key)
            if not isinstance(field_meta, dict):
                return

            next_meta = dict(field_meta)
            if advanced is not None:
                next_meta["advanced"] = bool(advanced)
            if condition is not None:
                next_meta["condition"] = dict(condition)
            schema[key] = next_meta

        advanced_fields = {
            "system_prompt",
            "companion_prompt",
            "start_preset",
            "end_preset",
            "start_llm_prompt",
            "end_llm_prompt",
            "interaction_frequency",
            "active_time_range",
            "rest_time_range",
            "custom_presets",
            "current_preset_index",
            "capture_active_window",
            "window_companion_check_interval",
            "ffmpeg_path",
            "recording_fps",
            "recording_duration_seconds",
            "use_shared_screenshot_dir",
            "shared_screenshot_dir",
            "bot_vision_quality",
            "image_quality",
            "allow_unsafe_video_direct_fallback",
            "vision_api_url",
            "vision_api_key",
            "vision_api_model",
            "diary_reference_days",
            "diary_auto_recall",
            "diary_recall_time",
            "diary_send_as_image",
            "diary_generation_prompt",
            "mic_threshold",
            "mic_check_interval",
            "memory_threshold",
            "battery_threshold",
            "weather_api_key",
            "weather_city",
            "custom_tasks",
            "debug",
            "enable_background_activity_tracking",
            "background_activity_tracking_interval",
            "input_stats_flush_interval",
            "away_auto_pause_threshold",
            "away_long_notice_threshold",
            "activity_recognition_rules",
            "webui.host",
            "webui.port",
            "webui.auth_enabled",
            "webui.password",
            "webui.session_timeout",
            "webui.allow_external_api",
        }
        for field_key in advanced_fields:
            patch_setting_meta(field_key, advanced=True)

        conditional_fields = {
            "start_preset": {"use_llm_for_start_end": False},
            "end_preset": {"use_llm_for_start_end": False},
            "start_llm_prompt": {"use_llm_for_start_end": True},
            "end_llm_prompt": {"use_llm_for_start_end": True},
            "window_companion_targets": {"enable_window_companion": True},
            "window_companion_check_interval": {"enable_window_companion": True},
            "window_companion_reattach_grace_seconds": {"enable_window_companion": True},
            "ffmpeg_path": {"screen_recognition_mode": True},
            "recording_fps": {"screen_recognition_mode": True},
            "recording_duration_seconds": {"screen_recognition_mode": True},
            "shared_screenshot_dir": {"use_shared_screenshot_dir": True},
            "allow_unsafe_video_direct_fallback": {"use_external_vision": True},
            "vision_api_url": {"use_external_vision": True},
            "vision_api_key": {"use_external_vision": True},
            "vision_api_model": {"use_external_vision": True},
            "diary_time": {"enable_diary": True},
            "diary_reference_days": {"enable_diary": True},
            "diary_auto_recall": {"enable_diary": True},
            "diary_recall_time": {
                "enable_diary": True,
                "diary_auto_recall": True,
            },
            "diary_send_as_image": {"enable_diary": True},
            "diary_generation_prompt": {"enable_diary": True},
            "mic_threshold": {"enable_mic_monitor": True},
            "mic_check_interval": {"enable_mic_monitor": True},
            "background_activity_tracking_interval": {
                "enable_background_activity_tracking": True,
            },
            "input_stats_flush_interval": {"enable_input_stats": True},
            "enable_away_auto_pause": {"enable_input_stats": True},
            "away_auto_pause_threshold": {
                "enable_input_stats": True,
                "enable_away_auto_pause": True,
            },
            "away_long_notice_threshold": {
                "enable_input_stats": True,
                "enable_away_auto_pause": True,
            },
            "webui.host": {"webui.enabled": True},
            "webui.port": {"webui.enabled": True},
            "webui.auth_enabled": {"webui.enabled": True},
            "webui.password": {
                "webui.enabled": True,
                "webui.auth_enabled": True,
            },
            "webui.session_timeout": {"webui.enabled": True},
            "webui.allow_external_api": {"webui.enabled": True},
        }
        for field_key, condition in conditional_fields.items():
            patch_setting_meta(field_key, condition=condition)

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
                "window_companion_reattach_grace_seconds": int(
                    getattr(self.plugin, "window_companion_reattach_grace_seconds", 300)
                    or 300
                ),
                "enable_input_stats": bool(
                    getattr(self.plugin, "enable_input_stats", False)
                ),
                "enable_background_activity_tracking": bool(
                    getattr(self.plugin, "enable_background_activity_tracking", False)
                ),
                "background_activity_tracking_interval": int(
                    getattr(self.plugin, "background_activity_tracking_interval", 15)
                    or 15
                ),
                "input_stats_flush_interval": int(
                    getattr(self.plugin, "input_stats_flush_interval", 60) or 60
                ),
                "enable_away_auto_pause": bool(
                    getattr(self.plugin, "enable_away_auto_pause", False)
                ),
                "away_auto_pause_threshold": int(
                    getattr(self.plugin, "away_auto_pause_threshold", 1200) or 1200
                ),
                "away_long_notice_threshold": int(
                    getattr(self.plugin, "away_long_notice_threshold", 3600) or 3600
                ),
                "mask_activity_window_titles": bool(
                    getattr(self.plugin, "mask_activity_window_titles", False)
                ),
                "activity_recognition_rules": getattr(
                    self.plugin, "activity_recognition_rules", ""
                )
                or "",
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
                if self._should_preserve_sensitive_value(key, raw_value):
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

        applied_keys = sorted(normalized_updates.keys())
        if "webui" in normalized_updates and isinstance(normalized_updates["webui"], dict):
            applied_keys = [
                *(key for key in applied_keys if key != "webui"),
                *(
                    f"webui.{key}"
                    for key in sorted(normalized_updates["webui"].keys())
                ),
            ]

        try:
            self.plugin._update_config_from_dict(normalized_updates)
            return self._ok(
                {
                    "settings": self._build_settings_payload(),
                    "meta": {
                        "applied_keys": applied_keys,
                        "applied_count": len(applied_keys),
                        "webui_updated": any(
                            str(key).startswith("webui.") for key in applied_keys
                        ),
                    },
                }
            )
        except Exception as e:
            logger.error(f"更新 WebUI 配置失败: {e}", exc_info=True)
            return self._err(str(e))

    async def handle_health_check(self, request):
        """返回 WebUI 健康状态与自检信息。"""
        health_payload = self._build_health_payload()
        return self._ok(
            {
                "status": health_payload.get("status", "ok"),
                "service": "screen-companion-webui",
                "version": self.APP_VERSION,
                "plugin_version": self.APP_VERSION,
                "host": self.host,
                "port": self.port,
                "auth_enabled": bool(self._get_expected_secret()),
                "session_count": len(self._sessions),
                "started": bool(self._started),
                "instance_match": getattr(self.plugin, "web_server", None) is self,
                "pid": os.getpid(),
                "checked_at": datetime.now().isoformat(),
                "checks": health_payload.get("checks", []),
                "recommendations": health_payload.get("recommendations", []),
                "warning_count": int(health_payload.get("warning_count", 0) or 0),
                "error_count": int(health_payload.get("error_count", 0) or 0),
            }
        )

    def _build_runtime_status(self) -> dict[str, Any]:
        default_interval = getattr(self.plugin, "check_interval", 0)
        default_probability = getattr(self.plugin, "trigger_probability", 0)
        preset_params = self._safe_plugin_call(
            "_get_current_preset_params",
            (default_interval, default_probability),
        )
        if isinstance(preset_params, (list, tuple)) and len(preset_params) >= 2:
            current_interval, current_probability = preset_params[0], preset_params[1]
        else:
            current_interval, current_probability = default_interval, default_probability
        window_companion_effective_interval = getattr(
            self.plugin,
            "window_companion_effective_check_interval",
            current_interval,
        )
        window_companion_effective_probability = getattr(
            self.plugin,
            "window_companion_effective_trigger_probability",
            current_probability,
        )
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
        recent_screen_analyses = self._safe_plugin_call(
            "_get_recent_screen_analysis_traces",
            [],
            limit=6,
        ) or []
        activity_history = self._prepare_activity_history_for_display(
            self._safe_plugin_call("_get_activity_history_for_stats", []) or []
        )
        input_stats = self._safe_plugin_call(
            "_get_input_stats_runtime_status",
            {},
        ) or {}
        away_pause = self._safe_plugin_call(
            "_get_away_pause_runtime_status",
            {},
        ) or {}
        background_activity_tracking = self._safe_plugin_call(
            "_get_background_activity_tracking_runtime_status",
            {},
        ) or {}
        today_key = datetime.now().date().isoformat()
        today_history = [
            item
            for item in activity_history
            if self._get_activity_day_key(item.get("start_time", 0)) == today_key
        ]
        activity_pulse = self._build_activity_workspace_story(
            activity_history,
            today_summary=self._summarize_activity_period(today_history),
            input_stats=input_stats,
        ).get("pulse", {})
        activity_recognition_rules = self._safe_plugin_call(
            "_get_activity_recognition_rule_summary",
            {},
        ) or {}
        screen_recognition_mode = bool(
            self._safe_plugin_call("_use_screen_recording_mode", False)
        )
        recording_video_encoder = (
            self._safe_plugin_call("_get_recording_video_encoder", "") or ""
        )

        return {
            "enabled": self._plugin_bool("enabled"),
            "is_running": self._plugin_bool("is_running"),
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
            "enable_diary": self._plugin_bool("enable_diary"),
            "enable_learning": self._plugin_bool("enable_learning"),
            "enable_mic_monitor": self._plugin_bool("enable_mic_monitor"),
            "mic_threshold": getattr(self.plugin, "mic_threshold", 60),
            "memory_threshold": getattr(self.plugin, "memory_threshold", 80),
            "battery_threshold": getattr(self.plugin, "battery_threshold", 20),
            "debug": self._plugin_bool("debug"),
            "save_local": self._plugin_bool("save_local"),
            "screen_recognition_mode": screen_recognition_mode,
            "recording_video_encoder": recording_video_encoder,
            "use_external_vision": self._plugin_bool("use_external_vision"),
            "use_shared_screenshot_dir": self._plugin_bool("use_shared_screenshot_dir"),
            "shared_screenshot_dir": getattr(self.plugin, "shared_screenshot_dir", "") or "",
            "enable_natural_language_screen_assist": self._plugin_bool("enable_natural_language_screen_assist"),
            "enable_window_companion": self._plugin_bool("enable_window_companion"),
            "window_companion_targets": getattr(self.plugin, "window_companion_targets", "") or "",
            "window_companion_check_interval": int(getattr(self.plugin, "window_companion_check_interval", 5) or 5),
            "window_companion_effective_check_interval": int(window_companion_effective_interval),
            "window_companion_effective_trigger_probability": int(window_companion_effective_probability),
            "window_companion_reattach_grace_seconds": int(
                getattr(self.plugin, "window_companion_reattach_grace_seconds", 300) or 300
            ),
            "window_companion_active_title": getattr(self.plugin, "window_companion_active_title", "") or "",
            "diary_time": getattr(self.plugin, "diary_time", ""),
            "observation_count": len(getattr(self.plugin, "observations", []) or []),
            "latest_screenshot": latest_screenshot,
            "latest_video": latest_video,
            "recent_screen_analyses": recent_screen_analyses,
            "input_stats": input_stats,
            "background_activity_tracking": background_activity_tracking,
            "away_pause": away_pause,
            "activity_pulse": activity_pulse,
            "mask_activity_window_titles": self._plugin_bool("mask_activity_window_titles"),
            "activity_recognition_rules": activity_recognition_rules,
            "presets": presets,
        }

    def _resolve_latest_media_path(self, kind: str) -> tuple[Path | None, str]:
        plugin_data_dir = Path(getattr(self.plugin.plugin_config, "data_dir", Path.cwd()))

        if kind == "image":
            local_path = plugin_data_dir / "screen_shot_latest.jpg"
            if local_path.is_file():
                return local_path, "local_snapshot"

            if self._plugin_bool("use_shared_screenshot_dir"):
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
            if kind == "image" and not self._plugin_bool("save_local"):
                message = "未找到可预览的截图。可以开启素材留存，或使用共享截图目录模式。"
            if kind == "video" and not self._plugin_bool("save_local"):
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
            if hasattr(self.plugin, "_get_activity_history_for_stats"):
                activity_history = self.plugin._get_activity_history_for_stats() or []
            else:
                activity_history = getattr(self.plugin, "activity_history", []) or []
        activity_history = self._prepare_activity_history_for_display(activity_history)
        today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        yesterday_start = today_start - 24 * 60 * 60

        activity_history = [
            item for item in (activity_history or []) if isinstance(item, dict)
        ]
        today_history = [
            item
            for item in activity_history
            if float(item.get("start_time", 0) or 0) >= today_start
        ]
        yesterday_history = [
            item
            for item in activity_history
            if (
                yesterday_start
                <= float(item.get("start_time", 0) or 0)
                < today_start
            )
        ]

        today_summary = self._summarize_activity_period(today_history)
        total_summary = self._summarize_activity_period(activity_history)
        yesterday_summary = self._summarize_activity_period(yesterday_history)
        input_stats = self._safe_plugin_call(
            "_build_input_stats_payload",
            {
                "enabled": False,
                "available": False,
                "status": "disabled",
                "detail": "未启用本地输入统计",
                "today": {},
                "recent_days": [],
                "window_total_inputs": 0,
                "window_total_inputs_label": "0 次",
                "window_active_minutes": 0,
                "window_active_minutes_label": "0 分钟",
            },
            days=self.ACTIVITY_TREND_DAYS,
        ) or {}
        workspace_story = self._build_activity_workspace_story(
            activity_history,
            today_summary=today_summary,
            input_stats=input_stats,
        )
        surface_trail = self._build_activity_surface_trail(
            today_history if today_history else activity_history,
            limit=self.ACTIVITY_SURFACE_LIMIT,
        )
        capture_sources = self._summarize_activity_capture_sources(activity_history)

        recent_activities = sorted(
            activity_history,
            key=lambda x: float(x.get("start_time", 0) or 0),
            reverse=True,
        )[:20]

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
                    "app_name": activity.get("app_name", ""),
                    "site_label": activity.get("site_label", ""),
                    "site_domain": activity.get("site_domain", ""),
                    "page_title": activity.get("page_title", ""),
                    "resource_label": activity.get("resource_label", ""),
                    "resource_kind": activity.get("resource_kind", ""),
                    "bucket_key": self._activity_bucket_key(activity.get("type", "")),
                    "capture_source": str(activity.get("capture_source", "") or "screen_analysis"),
                    "capture_source_label": self._capture_source_label(
                        activity.get("capture_source", "") or "screen_analysis"
                    ),
                    "start_time": self._format_datetime(start_ts),
                    "end_time": self._format_datetime(end_ts),
                    "duration": self._format_duration(duration),
                    "duration_seconds": int(duration or 0),
                    "effective_duration": self._format_duration(
                        activity.get("effective_duration", duration)
                    ),
                    "effective_duration_seconds": int(
                        activity.get("effective_duration", duration) or 0
                    ),
                    "idle_trimmed_time": self._format_duration(
                        activity.get("idle_trimmed_seconds", 0)
                    ),
                    "has_input_estimate": bool(activity.get("has_input_estimate", False)),
                }
            )

        return {
            "today": today_summary,
            "total": total_summary,
            "yesterday": yesterday_summary,
            "review": self._build_activity_review(
                today_summary=today_summary,
                total_summary=total_summary,
                yesterday_summary=yesterday_summary,
                activity_history=activity_history,
            ),
            "pulse": workspace_story.get("pulse", {}),
            "sessions": workspace_story.get("sessions", {}),
            "input_stats": input_stats,
            "surface_trail": surface_trail,
            "capture_sources": capture_sources,
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

        try:
            self.plugin._update_config_from_dict(updates)
            return self._ok(
                {
                    "runtime": self._build_runtime_status(),
                    "meta": {
                        "applied_keys": sorted(updates.keys()),
                        "applied_count": len(updates),
                    },
                }
            )
        except Exception as e:
            logger.error(f"更新运行时配置失败: {e}", exc_info=True)
            return self._err(str(e))

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
            reset_away_pause = getattr(self.plugin, "_reset_away_pause_runtime_state", None)
            if callable(reset_away_pause):
                reset_away_pause()

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
                if hasattr(self.plugin, "_save_pending_diary_entries"):
                    self.plugin._save_pending_diary_entries()
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
            logger.error(f"图片分析失败: {e}")
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
                        provider.text_chat(
                            prompt=self.plugin._append_privacy_guard_prompt(interaction_prompt),
                            system_prompt=system_prompt
                        ),
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
