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
    MAX_WEBSOCKET_MESSAGE_BYTES = 14 * 1024 * 1024

    def __init__(
        self,
        *,
        port: int = 6315,
        auth_token: str = "",
        on_input_stats=None,
        on_mic_volume=None,
    ):
        self.port = min(65535, max(1, int(port or 6315)))
        self.auth_token = str(auth_token or "").strip()
        self._on_input_stats = on_input_stats
        self._on_mic_volume = on_mic_volume
        self._server = None
        self._latest_image_bytes: bytes = b""
        self._latest_window_title: str = ""
        self._latest_meta: dict[str, Any] = {}
        self._latest_timestamp: float = 0.0
        self._latest_mic_volume: int = 0
        self._latest_mic_timestamp: float = 0.0
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

    async def get_latest_screenshot(self) -> tuple[bytes, str, dict[str, Any]]:
        async with self._lock:
            return (
                self._latest_image_bytes,
                self._latest_window_title,
                dict(self._latest_meta),
            )

    def get_latest_mic_volume(self) -> tuple[int, float]:
        return int(self._latest_mic_volume or 0), float(self._latest_mic_timestamp or 0.0)

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

        if msg_type in {"input_stats", "input"}:
            payload = {
                "keys": max(0, int(data.get("keys", 0) or 0)),
                "clicks": max(0, int(data.get("clicks", 0) or 0)),
                "scroll_steps": max(0, int(data.get("scroll_steps", 0) or 0)),
                "moves": max(0, int(data.get("moves", 0) or 0)),
                "move_pixels": max(0, int(data.get("move_pixels", 0) or 0)),
                "window_title": str(data.get("window_title", "") or ""),
                "timestamp": data.get("timestamp", time.time()),
                "client_id": str(data.get("client_id", "") or ""),
            }
            handler = self._on_input_stats
            if callable(handler):
                try:
                    result = handler(payload)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning(f"处理远程 input_stats 失败: {e}")
                    await websocket.send(json.dumps({"error": f"input_stats 处理失败: {e}"}))
                    return
            await websocket.send(json.dumps({"status": "input_stats_received"}))
            logger.debug(
                "收到远程 input_stats: keys=%s clicks=%s scroll=%s moves=%s",
                payload["keys"],
                payload["clicks"],
                payload["scroll_steps"],
                payload["moves"],
            )
            return

        if msg_type in {"mic_volume", "mic"}:
            try:
                volume = int(float(data.get("volume", 0) or 0))
            except Exception:
                volume = 0
            volume = min(100, max(0, volume))
            async with self._lock:
                self._latest_mic_volume = volume
                self._latest_mic_timestamp = time.time()
            handler = self._on_mic_volume
            if callable(handler):
                try:
                    result = handler(volume, data if isinstance(data, dict) else {})
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.warning(f"处理远程 mic_volume 失败: {e}")
                    await websocket.send(json.dumps({"error": f"mic_volume 处理失败: {e}"}))
                    return
            await websocket.send(json.dumps({"status": "mic_volume_received", "volume": volume}))
            logger.debug("收到远程 mic_volume: %s", volume)
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
