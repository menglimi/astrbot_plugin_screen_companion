# -*- coding: utf-8 -*-
"""WebSocket receiver for remote screen companion mode.

Clients connect and push screenshot JPEG + metadata JSON.
The receiver stores the latest screenshot for the plugin to consume.
"""
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
    """WebSocket server that receives screenshots from remote clients."""

    def __init__(self, *, port: int = 6315, auth_token: str = ""):
        self.port = port
        self.auth_token = auth_token.strip()
        self._server = None
        self._latest_image_bytes: bytes = b""
        self._latest_window_title: str = ""
        self._latest_meta: dict[str, Any] = {}
        self._latest_timestamp: float = 0.0
        self._connected_clients: set = set()
        self._lock = asyncio.Lock()

    @property
    def has_screenshot(self) -> bool:
        return bool(self._latest_image_bytes) and self._latest_timestamp > 0.0

    @property
    def latest_age_seconds(self) -> float:
        if self._latest_timestamp <= 0:
            return float("inf")
        return time.time() - self._latest_timestamp

    async def get_latest_screenshot(self) -> tuple[bytes, str, dict[str, Any]]:
        """Return (jpeg_bytes, window_title, meta_dict)."""
        async with self._lock:
            return self._latest_image_bytes, self._latest_window_title, dict(self._latest_meta)

    async def start(self) -> None:
        if websockets is None:
            logger.error("websockets 库未安装，无法启动远程接收服务")
            return

        self._server = await ws_serve(
            self._handle_client,
            "0.0.0.0",
            self.port,
        )
        logger.info(f"远程识屏 WebSocket 服务已启动，监听端口 {self.port}")

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("远程识屏 WebSocket 服务已停止")

    async def _handle_client(self, websocket) -> None:
        client_addr = websocket.remote_address
        logger.info(f"远程识屏客户端连接: {client_addr}")
        self._connected_clients.add(websocket)

        try:
            # First message should be auth if token is set
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
                # No auth required, send ready signal
                await websocket.send(json.dumps({"status": "ready"}))

            # Main loop: receive screenshots
            async for message in websocket:
                await self._process_message(message, websocket)

        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"客户端断开: {client_addr}")
        except Exception as e:
            logger.error(f"远程识屏客户端处理异常: {e}")
        finally:
            self._connected_clients.discard(websocket)
            logger.info(f"客户端断开: {client_addr}，当前连接数: {len(self._connected_clients)}")

    async def _process_message(self, message, websocket) -> None:
        """Process incoming message: either binary (JPEG) or text (JSON metadata)."""
        if isinstance(message, bytes):
            # Binary: raw JPEG screenshot data
            async with self._lock:
                self._latest_image_bytes = message
                self._latest_timestamp = time.time()
            logger.debug(f"收到截图: {len(message)} bytes")

        elif isinstance(message, str):
            # Text: JSON metadata
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"error": "无效 JSON"}))
                return

            msg_type = data.get("type", "")

            if msg_type == "screenshot_meta":
                # Metadata for the next/previous screenshot
                async with self._lock:
                    self._latest_window_title = str(data.get("window_title", "") or "")
                    self._latest_meta = {
                        "window_title": self._latest_window_title,
                        "system_stats": data.get("system_stats", {}),
                        "timestamp": data.get("timestamp", time.time()),
                        "client_id": data.get("client_id", ""),
                    }
                await websocket.send(json.dumps({"status": "meta_received"}))

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))

            elif msg_type == "screenshot_bundle":
                # Combined: base64 JPEG + metadata in one message
                import base64
                jpeg_b64 = data.get("image", "")
                if jpeg_b64:
                    jpeg_bytes = base64.b64decode(jpeg_b64)
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
                else:
                    await websocket.send(json.dumps({"error": "缺少 image 字段"}))

            else:
                await websocket.send(json.dumps({"error": f"未知消息类型: {msg_type}"}))
