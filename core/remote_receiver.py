# -*- coding: utf-8 -*-
"""WebSocket receiver for remote screen companion mode."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import secrets
import time
from typing import Any

from astrbot.api import logger

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    websockets = None
    ws_serve = None


class RemoteScreenReceiver:
    """Receive screenshots from a remote desktop client over WebSocket."""

    MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
    MAX_VIDEO_BYTES = 100 * 1024 * 1024
    MAX_VIDEO_CHUNK_BYTES = 5 * 1024 * 1024
    MAX_WEBSOCKET_MESSAGE_BYTES = 14 * 1024 * 1024

    def __init__(self, *, port: int = 6315, auth_token: str = ""):
        self.port = min(65535, max(1, int(port or 6315)))
        self.auth_token = str(auth_token or "").strip()
        self._server = None
        self._latest_image_bytes: bytes = b""
        self._latest_window_title: str = ""
        self._latest_meta: dict[str, Any] = {}
        self._latest_timestamp: float = 0.0
        self._latest_video_bytes: bytes = b""
        self._latest_video_meta: dict[str, Any] = {}
        self._video_uploads: dict[str, dict[str, Any]] = {}
        self._connected_clients: set = set()
        self._lock = asyncio.Lock()

    @property
    def has_screenshot(self) -> bool:
        return bool(self._latest_image_bytes) and self._latest_timestamp > 0.0

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def latest_age_seconds(self) -> float:
        if self._latest_timestamp <= 0:
            return float("inf")
        return time.time() - self._latest_timestamp

    @property
    def latest_video_age_seconds(self) -> float:
        completed_at = float(self._latest_video_meta.get("completed_at", 0.0) or 0.0)
        if completed_at <= 0:
            return float("inf")
        return time.time() - completed_at

    async def get_latest_screenshot(self) -> tuple[bytes, str, dict[str, Any]]:
        async with self._lock:
            return (
                self._latest_image_bytes,
                self._latest_window_title,
                dict(self._latest_meta),
            )

    async def get_latest_video(self) -> tuple[bytes, dict[str, Any]]:
        """Return the most recently completed remote video upload."""
        async with self._lock:
            return self._latest_video_bytes, dict(self._latest_video_meta)

    async def start(self) -> None:
        if self.is_running:
            return
        if websockets is None or ws_serve is None:
            logger.error("websockets 库未安装，无法启动远程接收服务")
            return

        self._server = await ws_serve(
            self._handle_client,
            "0.0.0.0",
            self.port,
            max_size=self.MAX_WEBSOCKET_MESSAGE_BYTES,
        )
        if not self.auth_token:
            logger.warning("远程识屏未设置认证令牌，任何可访问该端口的客户端都能推送截图")
        logger.info(f"远程识屏 WebSocket 服务已启动，监听端口 {self.port}")

    async def stop(self) -> None:
        if not self._server:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        logger.info("远程识屏 WebSocket 服务已停止")

    async def _handle_client(self, websocket) -> None:
        client_addr = websocket.remote_address
        logger.info(f"远程识屏客户端连接: {client_addr}")
        self._connected_clients.add(websocket)

        try:
            if self.auth_token:
                try:
                    auth_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    auth_data = json.loads(auth_msg) if isinstance(auth_msg, str) else {}
                    supplied_token = str(auth_data.get("token", "") or "")
                    if not secrets.compare_digest(supplied_token, self.auth_token):
                        await websocket.close(4001, "认证失败")
                        logger.warning(f"客户端认证失败: {client_addr}")
                        return
                    await websocket.send(json.dumps({"status": "authenticated"}))
                except asyncio.TimeoutError:
                    await websocket.close(4002, "认证超时")
                    return
                except Exception as e:
                    await websocket.close(4003, f"认证错误: {e}")
                    return
            else:
                await websocket.send(json.dumps({"status": "ready"}))

            async for message in websocket:
                await self._process_message(message, websocket)

        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"客户端断开: {client_addr}")
        except Exception as e:
            logger.error(f"远程识屏客户端处理异常: {e}")
        finally:
            self._connected_clients.discard(websocket)
            logger.info(
                f"客户端断开: {client_addr}，当前连接数: {len(self._connected_clients)}"
            )

    async def _process_message(self, message, websocket) -> None:
        if isinstance(message, bytes):
            error = self._validate_jpeg(message)
            if error:
                await websocket.send(json.dumps({"error": error}))
                return
            async with self._lock:
                self._latest_image_bytes = message
                self._latest_timestamp = time.time()
            await websocket.send(json.dumps({"status": "binary_screenshot_received"}))
            logger.debug(f"收到截图: {len(message)} bytes")
            return

        if not isinstance(message, str):
            await websocket.send(json.dumps({"error": "不支持的消息类型"}))
            return

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            await websocket.send(json.dumps({"error": "无效 JSON"}))
            return

        if not isinstance(data, dict):
            await websocket.send(json.dumps({"error": "JSON 消息必须是对象"}))
            return

        msg_type = str(data.get("type", "") or "")

        if msg_type == "screenshot_meta":
            async with self._lock:
                self._latest_window_title = str(data.get("window_title", "") or "")
                self._latest_meta = {
                    "window_title": self._latest_window_title,
                    "system_stats": data.get("system_stats", {}),
                    "timestamp": data.get("timestamp", time.time()),
                    "client_id": data.get("client_id", ""),
                }
            await websocket.send(json.dumps({"status": "meta_received"}))
            return

        if msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))
            return

        if msg_type == "video_meta":
            upload_id = str(data.get("upload_id", "") or "").strip()
            try:
                total_size = int(data.get("total_size", 0) or 0)
            except (TypeError, ValueError):
                total_size = 0
            if not upload_id or total_size <= 0:
                await websocket.send(json.dumps({"error": "video_meta 缺少有效 upload_id 或 total_size"}))
                return
            if total_size > self.MAX_VIDEO_BYTES:
                await websocket.send(json.dumps({"error": "视频超过 100 MiB 限制"}))
                return
            async with self._lock:
                now = time.time()
                self._video_uploads = {
                    key: value
                    for key, value in self._video_uploads.items()
                    if now - float(value.get("created_at", now) or now) < 300
                }
                if len(self._video_uploads) >= 4 and upload_id not in self._video_uploads:
                    await websocket.send(json.dumps({"error": "同时进行的视频上传过多"}))
                    return
                self._video_uploads[upload_id] = {
                    "chunks": {},
                    "total_size": total_size,
                    "received_size": 0,
                    "created_at": now,
                    "meta": {
                        "upload_id": upload_id,
                        "mime_type": str(data.get("mime_type", "video/mp4") or "video/mp4"),
                        "window_title": str(data.get("window_title", "") or ""),
                        "client_id": str(data.get("client_id", "") or ""),
                        "timestamp": data.get("timestamp", time.time()),
                    },
                }
            await websocket.send(json.dumps({"status": "video_ready", "upload_id": upload_id}))
            return

        if msg_type == "video_chunk":
            upload_id = str(data.get("upload_id", "") or "").strip()
            try:
                chunk_index = int(data.get("index", 0))
            except (TypeError, ValueError):
                chunk_index = -1
            encoded_chunk = str(data.get("data", "") or "")
            if not upload_id or chunk_index < 0 or not encoded_chunk:
                await websocket.send(json.dumps({"error": "video_chunk 字段无效"}))
                return
            try:
                chunk = base64.b64decode(encoded_chunk, validate=True)
            except (binascii.Error, ValueError, TypeError):
                await websocket.send(json.dumps({"error": "video_chunk 不是有效的 base64"}))
                return
            if not chunk or len(chunk) > self.MAX_VIDEO_CHUNK_BYTES:
                await websocket.send(json.dumps({"error": "视频分块大小无效"}))
                return
            async with self._lock:
                upload = self._video_uploads.get(upload_id)
                if upload is None:
                    await websocket.send(json.dumps({"error": "未知 upload_id"}))
                    return
                if chunk_index not in upload["chunks"]:
                    upload["chunks"][chunk_index] = chunk
                    upload["received_size"] += len(chunk)
                if upload["received_size"] > upload["total_size"]:
                    self._video_uploads.pop(upload_id, None)
                    await websocket.send(json.dumps({"error": "视频分块总大小超出声明值"}))
                    return
            await websocket.send(json.dumps({"status": "video_chunk_received", "index": chunk_index}))
            return

        if msg_type == "video_complete":
            upload_id = str(data.get("upload_id", "") or "").strip()
            async with self._lock:
                upload = self._video_uploads.pop(upload_id, None)
                if upload is None:
                    await websocket.send(json.dumps({"error": "未知 upload_id"}))
                    return
                chunks = upload["chunks"]
                expected_size = upload["total_size"]
                if upload["received_size"] != expected_size or not chunks:
                    await websocket.send(json.dumps({"error": "视频分块不完整"}))
                    return
                video_bytes = b"".join(chunks[index] for index in sorted(chunks))
                if len(video_bytes) != expected_size:
                    await websocket.send(json.dumps({"error": "视频分块顺序或大小不匹配"}))
                    return
                self._latest_video_bytes = video_bytes
                self._latest_video_meta = dict(upload["meta"])
                self._latest_video_meta["completed_at"] = time.time()
            await websocket.send(json.dumps({"status": "video_complete", "upload_id": upload_id}))
            logger.debug(f"收到远程录屏: {len(video_bytes)} bytes")
            return

        if msg_type == "screenshot_bundle":
            jpeg_b64 = str(data.get("image", "") or "")
            if not jpeg_b64:
                await websocket.send(json.dumps({"error": "缺少 image 字段"}))
                return
            max_encoded_length = ((self.MAX_SCREENSHOT_BYTES + 2) // 3) * 4
            if len(jpeg_b64) > max_encoded_length:
                await websocket.send(json.dumps({"error": "截图超过 10 MiB 限制"}))
                return
            try:
                jpeg_bytes = base64.b64decode(jpeg_b64, validate=True)
            except (binascii.Error, ValueError, TypeError):
                await websocket.send(json.dumps({"error": "image 字段不是有效的 base64"}))
                return
            error = self._validate_jpeg(jpeg_bytes)
            if error:
                await websocket.send(json.dumps({"error": error}))
                return

            async with self._lock:
                self._latest_image_bytes = jpeg_bytes
                self._latest_window_title = str(data.get("window_title", "") or "")
                self._latest_meta = {
                    "window_title": self._latest_window_title,
                    "system_stats": data.get("system_stats", {}),
                    "timestamp": data.get("timestamp", time.time()),
                    "client_id": data.get("client_id", ""),
                }
                self._latest_timestamp = time.time()
            await websocket.send(json.dumps({"status": "screenshot_received"}))
            logger.debug(f"收到 bundle 截图: {len(jpeg_bytes)} bytes")
            return

        await websocket.send(json.dumps({"error": f"未知消息类型: {msg_type}"}))

    @classmethod
    def _validate_jpeg(cls, payload: bytes) -> str:
        if not payload:
            return "截图内容为空"
        if len(payload) > cls.MAX_SCREENSHOT_BYTES:
            return "截图超过 10 MiB 限制"
        if len(payload) < 4 or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            return "截图不是有效的 JPEG 数据"
        return ""
