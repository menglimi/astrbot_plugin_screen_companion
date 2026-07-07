# -*- coding: utf-8 -*-
"""WebSocket receiver for remote screen companion mode."""
from __future__ import annotations

import asyncio
import json
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

    def __init__(self, *, port: int = 6315, auth_token: str = ""):
        self.port = max(1, int(port or 6315))
        self.auth_token = str(auth_token or "").strip()
        self._server = None
        self._latest_image_bytes: bytes = b""
        self._latest_window_title: str = ""
        self._latest_meta: dict[str, Any] = {}
        self._latest_timestamp: float = 0.0
        self._connected_clients: set = set()
        self._lock = asyncio.Lock()

        # Remote input stats (received from client)
        self._latest_input_stats: dict[str, Any] = {}
        self._latest_input_stats_timestamp: float = 0.0

        # Remote mic volume (received from client)
        self._latest_mic_volume: int = 0
        self._latest_mic_volume_timestamp: float = 0.0

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

    async def get_latest_screenshot(self) -> tuple[bytes, str, dict[str, Any]]:
        async with self._lock:
            return (
                self._latest_image_bytes,
                self._latest_window_title,
                dict(self._latest_meta),
            )

    async def get_latest_input_stats(self) -> dict[str, Any]:
        async with self._lock:
            return dict(self._latest_input_stats)

    @property
    def latest_input_stats_age_seconds(self) -> float:
        if self._latest_input_stats_timestamp <= 0:
            return float("inf")
        return time.time() - self._latest_input_stats_timestamp

    async def get_latest_mic_volume(self) -> int:
        async with self._lock:
            return self._latest_mic_volume

    @property
    def latest_mic_volume_age_seconds(self) -> float:
        if self._latest_mic_volume_timestamp <= 0:
            return float("inf")
        return time.time() - self._latest_mic_volume_timestamp

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
        )
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
                    if auth_data.get("token") != self.auth_token:
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
            async with self._lock:
                self._latest_image_bytes = message
                self._latest_timestamp = time.time()
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

        msg_type = data.get("type", "")

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

        if msg_type == "screenshot_bundle":
            import base64

            jpeg_b64 = str(data.get("image", "") or "")
            if not jpeg_b64:
                await websocket.send(json.dumps({"error": "缺少 image 字段"}))
                return
            try:
                jpeg_bytes = base64.b64decode(jpeg_b64)
            except Exception:
                await websocket.send(json.dumps({"error": "image 字段不是有效的 base64"}))
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

        if msg_type == "input_stats":
            async with self._lock:
                self._latest_input_stats = {
                    "keys": int(data.get("keys", 0) or 0),
                    "clicks": int(data.get("clicks", 0) or 0),
                    "scroll_steps": int(data.get("scroll_steps", 0) or 0),
                    "moves": int(data.get("moves", 0) or 0),
                    "move_pixels": int(data.get("move_pixels", 0) or 0),
                    "window_title": str(data.get("window_title", "") or ""),
                    "timestamp": data.get("timestamp", time.time()),
                    "client_id": str(data.get("client_id", "") or ""),
                }
                self._latest_input_stats_timestamp = time.time()
            await websocket.send(json.dumps({"status": "input_stats_received"}))
            logger.debug(f"Remote input stats: keys={data.get('keys', 0)}, clicks={data.get('clicks', 0)}")
            return

        if msg_type == "mic_volume":
            volume = max(0, min(100, int(data.get("volume", 0) or 0)))
            async with self._lock:
                self._latest_mic_volume = volume
                self._latest_mic_volume_timestamp = time.time()
            await websocket.send(json.dumps({"status": "mic_volume_received", "volume": volume}))
            logger.debug(f"Remote mic volume: {volume}")
            return

        await websocket.send(json.dumps({"error": f"未知消息类型: {msg_type}"}))
