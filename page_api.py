# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import mimetypes
from typing import Any, Callable

from astrbot.api import logger
from quart import jsonify, request, send_file

from .web_server import WebServer

PLUGIN_NAME = "astrbot_plugin_screen_companion"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}"


class _QuartRequestAdapter:
    """Minimal aiohttp-like request adapter for reused WebServer handlers."""

    def __init__(self, *, match_info: dict[str, Any] | None = None) -> None:
        self.match_info = match_info or {}
        self.query = request.args
        self.cookies = request.cookies
        self.headers = request.headers
        self.method = request.method
        self.path = request.path

    async def json(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}

    async def multipart(self):
        raise RuntimeError("文件上传请使用独立 WebUI 或 Base64 API")


class PluginPageApi:
    """AstrBot plugin Pages API for Screen Companion."""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.backend = WebServer(
            plugin,
            host=getattr(plugin, "webui_host", "127.0.0.1"),
            port=getattr(plugin, "webui_port", 6314),
        )
        self.backend._ok = self._ok
        self.backend._err = self._err

    def register(self, context: Any) -> None:
        routes: list[tuple[str, Callable[..., Any], list[str], dict[str, str]]] = [
            ("/diaries", self._wrap(self.backend.handle_list_diaries), ["GET"], {}),
            ("/diary/<date>", self._wrap(self.backend.handle_get_diary, "date"), ["GET"], {}),
            ("/diary/<date>", self._wrap(self.backend.handle_delete_diary, "date"), ["DELETE", "POST"], {}),
            ("/diaries/batch", self._wrap(self.backend.handle_batch_delete_diaries), ["DELETE", "POST"], {}),
            ("/observations", self._wrap(self.backend.handle_list_observations), ["GET"], {}),
            ("/observations/<index>", self._wrap(self.backend.handle_delete_observation, "index"), ["DELETE", "POST"], {}),
            ("/observations/batch", self._wrap(self.backend.handle_batch_delete_observations), ["DELETE", "POST"], {}),
            ("/data/clear", self._wrap(self.backend.handle_clear_all_data), ["POST"], {}),
            ("/memories", self._wrap(self.backend.handle_list_memories), ["GET"], {}),
            ("/config", self._wrap(self.backend.handle_get_config), ["GET"], {}),
            ("/settings", self._wrap(self.backend.handle_get_settings), ["GET"], {}),
            ("/settings", self._wrap(self.backend.handle_update_settings), ["POST"], {}),
            ("/health", self._wrap(self.backend.handle_health_check), ["GET"], {}),
            ("/runtime", self._wrap(self.backend.handle_get_runtime_status), ["GET"], {}),
            ("/runtime/config", self._wrap(self.backend.handle_update_runtime_config), ["POST"], {}),
            ("/runtime/stop", self._wrap(self.backend.handle_stop_runtime_tasks), ["POST"], {}),
            ("/windows", self._wrap(self.backend.handle_list_windows), ["GET"], {}),
            ("/activity", self._wrap(self.backend.handle_get_activity_stats), ["GET"], {}),
            ("/dashboard", self._wrap(self.backend.handle_get_dashboard_stats), ["GET"], {}),
            ("/media/latest/<kind>", self.handle_get_latest_media, ["GET"], {}),
            ("/media/latest-data/<kind>", self.handle_get_latest_media_data, ["GET"], {}),
            ("/analyze/base64", self._wrap(self.backend.handle_analyze_image_base64), ["POST"], {}),
            ("/auth/info", self.handle_auth_info, ["GET"], {}),
            ("/auth/login", self.handle_auth_login, ["POST"], {}),
            ("/auth/logout", self.handle_auth_logout, ["POST"], {}),
        ]

        for route, handler, methods, _ in routes:
            context.register_web_api(
                f"{PAGE_API_PREFIX}{route}",
                handler,
                methods,
                f"Screen Companion Page: {route}",
            )

    @staticmethod
    def _ok(data: dict | None = None, **kwargs):
        body: dict[str, Any] = {"success": True}
        if data:
            body.update(data)
        if kwargs:
            body.update(kwargs)
        return jsonify(body)

    @staticmethod
    def _err(msg: str, status: int = 500):
        response = jsonify({"success": False, "error": msg})
        response.status_code = int(status or 500)
        return response

    def _wrap(self, handler, *match_keys: str):
        async def wrapped(**path_params):
            match_info = {
                key: str(path_params.get(key, "") or "")
                for key in match_keys
            }
            adapted_request = _QuartRequestAdapter(match_info=match_info)
            return await handler(adapted_request)

        return wrapped

    async def handle_get_latest_media(self, kind: str = ""):
        media_kind = str(kind or "").strip().lower()
        if media_kind not in {"image", "video"}:
            return self._err("Unsupported media kind", 400)
        try:
            path, _ = self.backend._resolve_latest_media_path(media_kind)
            if path is None or not path.is_file():
                return self._err("Latest media is not available", 404)
            response = await send_file(str(path))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response
        except Exception as exc:
            logger.error(f"插件拓展页面读取最新{media_kind}预览失败: {exc}")
            return self._err(str(exc))

    async def handle_get_latest_media_data(self, kind: str = ""):
        media_kind = str(kind or "").strip().lower()
        if media_kind not in {"image", "video"}:
            return self._err("Unsupported media kind", 400)
        try:
            path, source = self.backend._resolve_latest_media_path(media_kind)
            if path is None or not path.is_file():
                return self._err("Latest media is not available", 404)
            stat = path.stat()
            fallback_mime = "video/mp4" if media_kind == "video" else "image/jpeg"
            mime = mimetypes.guess_type(str(path))[0] or fallback_mime
            raw = await asyncio.to_thread(path.read_bytes)
            data = base64.b64encode(raw).decode("ascii")
            return self._ok(
                {
                    "available": True,
                    "kind": media_kind,
                    "mime": mime,
                    "mime_type": mime,
                    "data_url": f"data:{mime};base64,{data}",
                    "updated_at": stat.st_mtime,
                    "size_bytes": int(stat.st_size),
                    "source": source,
                    "filename": path.name,
                }
            )
        except Exception as exc:
            logger.error(f"插件拓展页面读取最新{media_kind}数据失败: {exc}", exc_info=True)
            return self._err(str(exc))

    async def handle_auth_info(self):
        return self._ok(
            {
                "requires_auth": False,
                "authenticated": True,
                "auth_enabled": False,
                "session_timeout": 0,
                "page_auth": "dashboard",
            }
        )

    async def handle_auth_login(self):
        return self._ok({"success": True})

    async def handle_auth_logout(self):
        return self._ok({"success": True})
