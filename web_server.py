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

            path = request.path or "/"
            
            # 检查是否是外部API调用
            if path in ("/api/analyze", "/api/analyze/base64"):
                # 外部API需要特殊处理
                if not self.plugin.webui_allow_external_api:
                    return WebServer._err("外部API未启用", 403)
                
                # 检查API密钥
                expected = self._get_expected_secret()
                if expected:
                    # 从Header获取API密钥
                    api_key = request.headers.get("X-API-Key", "")
                    if not api_key or api_key != expected:
                        return WebServer._err("Unauthorized", 401)
                return await handler(request)
            
            # 其他API需要登录
            expected = self._get_expected_secret()
            if not expected:
                return await handler(request)

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
        self.app.router.add_delete("/api/observations/{index}", self.handle_delete_observation)
        self.app.router.add_delete("/api/observations/batch", self.handle_batch_delete_observations)
        self.app.router.add_get("/api/memories", self.handle_list_memories)
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_get("/api/settings", self.handle_get_settings)
        self.app.router.add_post("/api/settings", self.handle_update_settings)
        self.app.router.add_get("/api/health", self.handle_health_check)
        self.app.router.add_get("/api/runtime", self.handle_get_runtime_status)
        self.app.router.add_post("/api/runtime/config", self.handle_update_runtime_config)
        self.app.router.add_post("/api/runtime/stop", self.handle_stop_runtime_tasks)
        
        # 外部图片分析API
        self.app.router.add_post("/api/analyze", self.handle_analyze_image)
        self.app.router.add_post("/api/analyze/base64", self.handle_analyze_image_base64)
        
        # 认证相关
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
            # 获取查询参数
            page = int(request.query.get('page', 1))
            limit = int(request.query.get('limit', 20))
            sort = request.query.get('sort', 'desc')  # desc 或 asc
            scene = request.query.get('scene', '')
            
            # 复制观察记录以便处理
            observations = []
            for index, obs in enumerate(self.plugin.observations.copy()):
                scene = str(obs.get("scene", "") or "").strip()
                if scene.lower() in {"unknown", "none", "null"} or scene == "未知":
                    scene = ""

                active_window = str(
                    obs.get("active_window")
                    or obs.get("window_title")
                    or ""
                ).strip()
                if active_window.lower() in {"unknown", "none", "null"} or active_window in {"未知", "宿主机截图"}:
                    active_window = ""

                content = str(
                    obs.get("content")
                    or obs.get("description")
                    or obs.get("recognition")
                    or ""
                ).strip()

                observations.append(
                    {
                        "index": index,
                        **obs,
                        "scene": scene,
                        "active_window": active_window,
                        "content": content,
                    }
                )
            
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
        """获取记忆数据"""
        try:
            memories = []
            if hasattr(self.plugin, "_clean_long_term_memory_noise"):
                self.plugin._clean_long_term_memory_noise()
            long_term_memory = getattr(self.plugin, "long_term_memory", {}) or {}

            applications = long_term_memory.get("applications", {})
            for app_name, data in applications.items():
                scenes = data.get("scenes", {}) or {}
                top_scenes = sorted(scenes.items(), key=lambda item: item[1], reverse=True)[:3]
                scene_summary = "、".join(f"{name}({count})" for name, count in top_scenes)
                memories.append(
                    {
                        "category": "applications",
                        "category_label": "常用应用",
                        "title": app_name,
                        "summary": f"累计使用 {data.get('usage_count', 0)} 次，总时长约 {data.get('total_duration', 0)} 秒。",
                        "meta": f"最近使用: {data.get('last_used', '未知')} | 关联场景: {scene_summary or '暂无'}",
                        "priority": data.get("priority", 0),
                    }
                )

            scenes = long_term_memory.get("scenes", {})
            for scene_name, data in scenes.items():
                memories.append(
                    {
                        "category": "scenes",
                        "category_label": "高频场景",
                        "title": scene_name,
                        "summary": f"该场景累计出现 {data.get('usage_count', 0)} 次。",
                        "meta": f"最近出现: {data.get('last_used', '未知')}",
                        "priority": data.get("priority", 0),
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
                            "summary": f"偏好分类: {category}，累计提及 {data.get('count', 0)} 次。",
                            "meta": f"最近提及: {data.get('last_mentioned', '未知')}",
                            "priority": data.get("priority", 0),
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
                        "summary": f"这个组合共出现 {data.get('count', 0)} 次。",
                        "meta": f"最近出现: {data.get('last_occurred', '未知')}",
                        "priority": data.get("count", 0),
                    }
                )

            memories.sort(
                key=lambda item: (item.get("priority", 0), item.get("title", "")),
                reverse=True,
            )
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
                "version": "2.4.0",
                "plugin_version": "2.4.0"
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
            values[key] = getattr(self.plugin, key, None)

        webui_config = getattr(getattr(self.plugin, "plugin_config", None), "webui", None)
        if webui_config:
            values.update(
                {
                    "webui.enabled": bool(getattr(webui_config, "enabled", False)),
                    "webui.host": getattr(webui_config, "host", "0.0.0.0"),
                    "webui.port": int(getattr(webui_config, "port", 8898) or 8898),
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
                "description": "决定 bot 的性格、开场方式、互动风格和提示词语气。",
                "fields": [
                    "bot_name",
                    "system_prompt",
                    "user_preferences",
                    "start_end_mode",
                    "start_preset",
                    "end_preset",
                    "start_llm_prompt",
                    "end_llm_prompt",
                ],
            },
            {
                "id": "runtime",
                "title": "运行节奏",
                "description": "控制自动观察的频率、时间范围、预设与触发强度。",
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
                    "watch_mode",
                    "capture_mode",
                ],
            },
            {
                "id": "vision",
                "title": "识屏与视觉",
                "description": "控制截图理解质量、外部视觉接口和识别提示词。",
                "fields": [
                    "bot_vision_quality",
                    "image_quality",
                    "image_prompt",
                    "use_external_vision",
                    "vision_api_url",
                    "vision_api_key",
                    "vision_api_model",
                ],
            },
            {
                "id": "diary",
                "title": "日记与记忆",
                "description": "控制日记生成、回顾、学习和长期记忆相关参数。",
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
                "description": "麦克风、天气和主动消息目标等附加感知能力。",
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
                "description": "控制 WebUI 自身的访问、端口和外部 API 能力。",
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
                "hint": "关闭后将不会启动浏览器管理界面。",
                "default": False,
            },
            "webui.host": {
                "description": "WebUI 监听地址",
                "type": "string",
                "hint": "通常保留 0.0.0.0 即可，本地访问会自动映射到 127.0.0.1。",
                "default": "0.0.0.0",
            },
            "webui.port": {
                "description": "WebUI 端口",
                "type": "int",
                "hint": "默认 8898，修改后会自动重启 WebUI。",
                "default": 8898,
                "min": 1,
                "max": 65535,
            },
            "webui.auth_enabled": {
                "description": "启用访问密码",
                "type": "bool",
                "hint": "建议保留开启，避免本地管理页被直接访问。",
                "default": True,
            },
            "webui.password": {
                "description": "WebUI 密码",
                "type": "password",
                "hint": "留空时会在需要保护的情况下自动生成密码。",
                "default": "",
            },
            "webui.session_timeout": {
                "description": "会话过期时间",
                "type": "int",
                "hint": "单位为秒。",
                "default": 3600,
                "min": 300,
                "max": 604800,
            },
            "webui.allow_external_api": {
                "description": "允许外部 API 调用",
                "type": "bool",
                "hint": "开启后可通过 WebUI 密码调用图片分析接口。",
                "default": False,
            },
        }

        schema.update(webui_schema)
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
        """获取配置 schema 与当前值。"""
        try:
            return self._ok({"settings": self._build_settings_payload()})
        except Exception as e:
            logger.error(f"Error getting settings: {e}")
            return self._err(str(e))

    async def handle_update_settings(self, request):
        """批量更新配置。"""
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
        """健康检查"""
        return self._ok({"status": "ok", "service": "screen-companion-webui"})

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
            "diary_time": getattr(self.plugin, "diary_time", ""),
            "observation_count": len(getattr(self.plugin, "observations", []) or []),
            "presets": presets,
        }

    async def handle_get_runtime_status(self, request):
        """获取当前运行状态"""
        try:
            return self._ok({"runtime": self._build_runtime_status()})
        except Exception as e:
            logger.error(f"Error getting runtime status: {e}")
            return self._err(str(e))

    async def handle_update_runtime_config(self, request):
        """更新可安全热切换的运行配置"""
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
        """停止当前自动观察任务"""
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
                    logger.info(f"任务 {task_id} 已取消")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

            if hasattr(self.plugin, "auto_tasks"):
                self.plugin.auto_tasks.clear()

            return self._ok({"runtime": self._build_runtime_status()})
        except Exception as e:
            logger.error(f"Error stopping runtime tasks: {e}")
            return self._err(str(e))

    async def handle_delete_observation(self, request):
        """删除单个观察记录"""
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
        """批量删除观察记录"""
        try:
            payload = await request.json()
            indices = payload.get("indices", [])
            # 确保索引是整数且排序（从大到小删除，避免索引移位）
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
                return self._err("未上传图片", 400)
            
            # 调用插件的分析方法
            result = await self._analyze_image_logic(image_bytes, custom_prompt)
            
            # 如果提供了webhook，发送结果
            if webhook_url and result.get("success"):
                asyncio.create_task(self._send_webhook(webhook_url, result))
            
            return self._ok(result)
            
        except Exception as e:
            logger.error(f"图片分析失败: {e}")
            return self._err(str(e))

    async def handle_analyze_image_base64(self, request):
        """通过Base64分析图片"""
        try:
            payload = await request.json()
            
            image_base64 = payload.get("image", "")
            custom_prompt = payload.get("prompt", "")
            webhook_url = payload.get("webhook", "")
            
            if not image_base64:
                return self._err("未提供图片 Base64", 400)
            
            # 解码Base64
            import base64
            try:
                if image_base64.startswith("data:"):
                    # 去除 data:image/xxx;base64, 前缀
                    image_base64 = image_base64.split(",", 1)[1]
                image_bytes = base64.b64decode(image_base64)
            except Exception:
                return self._err("Base64 解码失败", 400)
            
            # 调用插件的分析方法
            result = await self._analyze_image_logic(image_bytes, custom_prompt)
            
            # 如果提供了webhook，发送结果
            if webhook_url and result.get("success"):
                asyncio.create_task(self._send_webhook(webhook_url, result))
            
            return self._ok(result)
            
        except Exception as e:
            logger.error(f"图片分析失败: {e}")
            return self._err(str(e))

    async def _analyze_image_logic(self, image_bytes: bytes, custom_prompt: str = None) -> dict:
        """图片分析逻辑"""
        try:
            # 检查是否有视觉API配置
            if not self.plugin.vision_api_url:
                return {
                    "success": False,
                    "error": "未配置视觉API",
                    "reply": "……好像忘了看什么了……"
                }
            
            # 调用视觉API识别
            recognition_text = await self.plugin._call_external_vision_api(image_bytes)
            
            # 检查识别是否成功
            if "错误" in recognition_text or "无法" in recognition_text:
                return {
                    "success": False,
                    "error": recognition_text,
                    "reply": "……头晕晕的，看不太清……"
                }
            
            # 构建回复
            scene = self.plugin._identify_scene("外部图片")
            interaction_prompt = f"用户的屏幕显示：{recognition_text}。"
            if custom_prompt:
                interaction_prompt += f" {custom_prompt}"
            
            # 获取system prompt
            system_prompt = await self.plugin._get_persona_prompt()
            
            # 调用LLM生成回复
            provider = self.plugin.context.get_using_provider()
            if provider:
                try:
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=interaction_prompt, system_prompt=system_prompt),
                        timeout=60.0
                    )
                    reply_text = ""
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        reply_text = response.completion_text
                    else:
                        reply_text = "……刚才看到什么了？"
                except asyncio.TimeoutError:
                    reply_text = "……刚才好像走神了，再来一次？"
                except Exception as e:
                    logger.error(f"LLM调用失败: {e}")
                    reply_text = "……刚才有点困了，再试一次？"
            else:
                reply_text = "……好像忘了看什么了……"
            
            return {
                "success": True,
                "recognition": recognition_text,
                "scene": scene,
                "reply": reply_text
            }
            
        except Exception as e:
            logger.error(f"图片分析逻辑失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "reply": "……刚才晕了一下，再来？"
            }

    async def _send_webhook(self, url: str, result: dict):
        """发送webhook回调"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=result, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"Webhook发送成功: {url}")
        except Exception as e:
            logger.error(f"Webhook发送失败: {e}")

    async def handle_auth_info(self, request):
        """获取认证信息"""
        expected = self._get_expected_secret()
        authenticated = False
        if expected:
            sid = str(request.cookies.get(self._cookie_name, "") or "").strip()
            exp = self._sessions.get(sid)
            authenticated = bool(exp and exp >= time.time())
        return self._ok(
            {
                "requires_auth": bool(expected),
                "authenticated": authenticated,
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
