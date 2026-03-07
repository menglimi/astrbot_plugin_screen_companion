import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web

from astrbot.api import logger


class WebServer:
    """Web UI 服务器类，提供屏幕伴侣观察记录和日记管理界面。"""

    # 常量定义
    CLIENT_MAX_SIZE = 50 * 1024 * 1024  # 50MB 最大请求大小
    SESSION_CLEANUP_INTERVAL = 300  # Session 清理间隔（秒）
    SESSION_MAX_COUNT = 1000  # 最大 Session 数量

    def __init__(self, plugin: Any, host: str = "0.0.0.0", port: int = 8898):
        self.plugin = plugin
        self.host: str = host
        self.port: int = port
        self.app: web.Application = web.Application(
            client_max_size=self.CLIENT_MAX_SIZE,
            middlewares=[self._error_middleware, self._auth_middleware],
        )
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self._started: bool = False

        # Web UI 静态文件目录 (插件目录下的 web 文件夹)
        self.static_dir: Path = Path(__file__).resolve().parent / "web"

        # 数据目录
        self.data_dir: Path = self.plugin.diary_storage

        self._cookie_name: str = "screen_companion_webui_session"
        self._sessions: dict[str, float] = {}
        self._last_session_cleanup: float = 0.0  # 上次 session 清理时间
        self._session_cleanup_interval: int = self.SESSION_CLEANUP_INTERVAL

        self._setup_routes()

    # ── 响应快捷方法 ──────────────────────────────────────────

    @staticmethod
    def _ok(data: dict | None = None, **kwargs) -> web.Response:
        """返回成功 JSON 响应。"""
        body: dict = {"success": True}
        if data:
            body.update(data)
        if kwargs:
            body.update(kwargs)
        return web.json_response(body)

    @staticmethod
    def _err(msg: str, status: int = 500) -> web.Response:
        """返回失败 JSON 响应。"""
        return web.json_response({"success": False, "error": msg}, status=status)

    # ── 中间件 ────────────────────────────────────────────────

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
                return web.Response(text="500 Internal Server Error", status=500)

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

        # 如果密码为空，即使认证启用，也视为未启用认证
        if not password:
            return ""

        # 检查认证是否启用
        if not self._is_auth_enabled():
            return ""

        return password

    def _get_session_timeout(self) -> int:
        timeout = 3600
        # 尝试从配置获取
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

            expected = self._get_expected_secret()
            if not expected:
                return await handler(request)

            path = request.path or "/"
            if (
                path in ("/", "/index.html")
                or path.startswith("/web")
                or path in ("/auth/info", "/auth/login", "/auth/logout")
            ):
                return await handler(request)

            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            now = time.time()

            # 定期清理所有过期 session，防止内存泄漏
            if now - self._last_session_cleanup > self._session_cleanup_interval:
                expired = [k for k, v in self._sessions.items() if v < now]
                for k in expired:
                    self._sessions.pop(k, None)
                self._last_session_cleanup = now

                # 额外检查：如果 session 数量超过上限，清理最旧的一半
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
        self.app.router.add_get("/api/memories", self.handle_list_memories)
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_get("/api/health", self.handle_health_check)
        self.app.router.add_get("/auth/info", self.handle_auth_info)
        self.app.router.add_post("/auth/login", self.handle_auth_login)
        self.app.router.add_post("/auth/logout", self.handle_auth_logout)

        # 静态文件路由
        # 1. 前端页面 - 首页
        self.app.router.add_get("/", self.handle_index)
        # 某些客户端/代理在遇到 FileResponse 异常时会报 "HTTP/0.9"，提供显式入口便于排障
        self.app.router.add_get("/index.html", self.handle_index)

        # 2. 静态资源
        # 插件 web/index.html 如果引用了本地资源（js/css/img），这里提供静态托管。
        # 兼容直接打包在 web/ 目录下的资源结构。
        self.app.router.add_get("/web/{path:.*}", self.handle_web_static)

    def _resolve_safe_path(
        self, raw: str, base_dir: Path
    ) -> tuple[Path | None, str | None]:
        """安全解析请求路径，防止路径遍历攻击。"""
        raw = str(raw or "").lstrip("/")
        if not raw:
            return None, "not_found"

        # 安全检查：禁止路径遍历和绝对路径
        if (
            ".." in raw
            or raw.startswith(("/", "\\"))
            or ":" in raw  # Windows 驱动器字母
            or "\x00" in raw  # 空字节注入
        ):
            logger.warning(f"可疑路径请求被拒绝: {raw!r}")
            return None, "bad_request"

        # Windows 特殊设备名检查
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
            # 标准化路径并验证是否在基础目录内
            abs_path = (base_dir / raw).resolve()

            # 双重检查：确保解析后的路径确实在基础目录内
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

        # 改用手动读取并构造 Response，避免 Windows 下 FileResponse 可能的协议问题
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
                    return web.Response(text=content, content_type=content_type)
                except UnicodeDecodeError:
                    # 如果不是 UTF-8，尝试二进制
                    pass

            content = await asyncio.to_thread(abs_path.read_bytes)
            return web.Response(body=content, content_type=content_type)

        except Exception as e:
            logger.error(f"Failed to serve static file {abs_path}: {e}")
            raise web.HTTPNotFound()

    async def start(self) -> bool:
        """启动 Web 服务器

        Returns:
            bool: 是否启动成功
        """
        try:
            # 检查静态文件目录
            if not self.static_dir.exists():
                logger.warning(f"WebUI static directory not found: {self.static_dir}")

            # 创建并启动服务器
            # access_log=None 防止日志系统冲突
            self.runner = web.AppRunner(self.app, access_log=None)
            await self.runner.setup()

            # 标准绑定
            self.site = web.TCPSite(self.runner, str(self.host), int(self.port))
            await self.site.start()

            self._started = True

            # 显示实际监听地址
            protocol = "http"
            if self.host == "0.0.0.0":
                logger.info(
                    f"Screen Companion WebUI started - listening on all interfaces (0.0.0.0:{self.port})"
                )
                logger.info(f"  → Local access: {protocol}://127.0.0.1:{self.port}")
            else:
                logger.info(
                    f"Screen Companion WebUI started at {protocol}://{self.host}:{self.port}"
                )

            return True

        except OSError as e:
            if "Address already in use" in str(e) or e.errno == 98 or e.errno == 10048:
                logger.error(
                    f"WebUI 端口 {self.port} 已被占用，请更换端口或关闭占用该端口的程序"
                )
            else:
                logger.error(f"Failed to start WebUI (OS error): {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to start WebUI: {e}", exc_info=True)
            return False

    async def stop(self):
        """停止 Web 服务器"""
        if not self._started:
            return
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        self._started = False
        logger.info("Screen Companion WebUI stopped")

    async def handle_index(self, request):
        """返回首页"""
        try:
            index_file = self.static_dir / "index.html"
            if not index_file.exists():
                return web.Response(
                    text="<h1>Screen Companion WebUI</h1><p>index.html not found</p>",
                    content_type="text/html",
                    status=404,
                )
            # 这里不直接使用 FileResponse：
            # - 在部分环境/代理下，如果传输过程中异常中断，curl 可能会报 Received HTTP/0.9
            # - 显式构造 Response 能确保状态行和头部稳定输出
            try:
                content = await asyncio.to_thread(
                    index_file.read_text, encoding="utf-8"
                )
            except UnicodeDecodeError:
                # 兼容被意外写入非 UTF-8 的情况（尽量仍返回合法 HTTP 响应）
                content = await asyncio.to_thread(
                    index_file.read_text, encoding="utf-8", errors="replace"
                )
                logger.warning(
                    "WebUI index.html is not valid UTF-8, returned with replacement characters.",
                )
            return web.Response(text=content, content_type="text/html", status=200)
        except Exception as e:
            logger.error(f"Error serving index.html: {e}")
            return web.Response(text=f"Error: {e}", status=500)

    async def handle_list_diaries(self, request):
        """获取日记列表"""
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
        """获取日记详情"""
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

    async def handle_list_observations(self, request):
        """获取观察记录"""
        try:
            observations = self.plugin.observations
            return self._ok({
                'observations': observations
            })
        except Exception as e:
            logger.error(f"Error listing observations: {e}")
            return self._err(str(e))

    async def handle_list_memories(self, request):
        """获取记忆数据"""
        try:
            memories = []
            # 这里需要根据插件的记忆存储结构来实现
            return self._ok({
                'memories': memories
            })
        except Exception as e:
            logger.error(f"Error listing memories: {e}")
            return self._err(str(e))

    async def handle_get_config(self, request):
        """获取配置信息"""
        try:
            return self._ok({
                "version": "1.0.0",
                "plugin_version": "2.2.0"
            })
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return self._err(str(e))

    async def handle_health_check(self, request):
        """健康检查"""
        return self._ok({"status": "ok", "service": "screen-companion-webui"})

    async def handle_auth_info(self, request):
        """获取认证信息"""
        expected = self._get_expected_secret()
        return self._ok(
            {
                "requires_auth": bool(expected),
                "session_timeout": self._get_session_timeout(),
            }
        )

    async def handle_auth_login(self, request):
        """登录认证"""
        expected = self._get_expected_secret()
        if not expected:
            return self._ok(requires_auth=False)

        try:
            payload = await request.json()
        except Exception:
            return self._err("Invalid JSON", 400)

        provided = str((payload or {}).get("password", "") or "").strip()
        if not provided or provided != expected:
            return self._err("Unauthorized", 401)

        timeout = self._get_session_timeout()
        sid = uuid.uuid4().hex
        exp = time.time() + float(timeout)
        self._sessions[sid] = exp

        resp = self._ok(expires_at=int(exp))
        resp.set_cookie(
            self._cookie_name,
            sid,
            max_age=timeout,
            httponly=True,
            samesite="Lax",
            path="/",
        )
        return resp

    async def handle_auth_logout(self, request):
        """登出"""
        sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
        if sid:
            self._sessions.pop(sid, None)
        resp = self._ok()
        resp.del_cookie(self._cookie_name, path="/")
        return resp


import os