# -*- coding: utf-8 -*-
"""本机真实 WebSocket 集成测试。

覆盖 PR 方案第 18.3 节的 I01～I08：使用 ``websockets`` 在 ``127.0.0.1`` 的
随机端口上启动真实测试服务端，验证握手、消息序列、认证与断线行为。
只传输假图片字节，不访问真实桌面。
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import unittest

import websockets
from websockets.asyncio.server import serve

from astrbot_plugin_screen_companion.core.remote_receiver import (
    CAPABILITY_CAPTURE_ACTIVE_WINDOW,
    CAPABILITY_REQUEST_SCREENSHOT,
    PROTOCOL_VERSION,
    RemoteScreenReceiver,
    RemoteScreenshotError,
)

JPEG = b"\xff\xd8integration\xff\xd9"
ALT_JPEG = b"\xff\xd8second\xff\xd9"
AUTH_TOKEN = "integration-token"


class _ReceiverHarness:
    """在随机端口启动真实的接收器服务，并把 server 登记给接收器。"""

    def __init__(
        self,
        *,
        request_timeout: float = 5.0,
        auth_token: str = AUTH_TOKEN,
        capture_active_window: bool = False,
    ) -> None:
        self.receiver = RemoteScreenReceiver(
            auth_token=auth_token,
            request_timeout=request_timeout,
            capture_active_window=capture_active_window,
        )
        self.server = None
        self.port = 0

    async def start(self) -> "_ReceiverHarness":
        self.server = await serve(
            self.receiver._handle_client,
            "127.0.0.1",
            0,
            max_size=self.receiver.MAX_WEBSOCKET_MESSAGE_BYTES,
            close_timeout=1.0,
        )
        # 测试服务必须登记给接收器，否则 is_running 仍为 False，stop 也关不掉端口。
        self.receiver._server = self.server
        self.receiver._stopping = False
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    async def connect(self, *, token: str = AUTH_TOKEN, timeout: float = 5.0):
        """连接并完成认证，返回 (websocket, 握手响应)。"""
        websocket = await websockets.connect(self.url, close_timeout=1.0)
        await websocket.send(json.dumps({"token": token}))
        handshake = json.loads(await asyncio.wait_for(websocket.recv(), timeout=timeout))
        return websocket, handshake

    async def stop(self) -> None:
        await self.receiver.stop()


async def _negotiate(websocket, *, capabilities=None, client_id: str = "desktop"):
    """声明客户端能力并等待确认。"""
    await websocket.send(json.dumps({
        "type": "client_capabilities",
        "protocol_version": PROTOCOL_VERSION,
        "client_id": client_id,
        "capabilities": (
            [CAPABILITY_REQUEST_SCREENSHOT] if capabilities is None else capabilities
        ),
    }))
    return json.loads(await asyncio.wait_for(websocket.recv(), timeout=5.0))


async def _recv_json(websocket, timeout: float = 5.0) -> dict:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    return json.loads(raw)


async def _upload_frame(
    websocket,
    *,
    request_id: str = "",
    image: bytes = JPEG,
    title: str = "Editor",
    capture_scope: str = "",
) -> tuple[dict, dict]:
    """上传一整帧并返回两次确认。"""
    payload = {"type": "screenshot_meta", "window_title": title, "client_id": "desktop"}
    if request_id:
        payload["request_id"] = request_id
    if capture_scope:
        payload["capture_scope"] = capture_scope
    await websocket.send(json.dumps(payload))
    meta_ack = await _recv_json(websocket)
    await websocket.send(image)
    binary_ack = await _recv_json(websocket)
    return meta_ack, binary_ack


class RemoteWebSocketIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """I01～I08：真实连接上的协议与生命周期。"""

    async def asyncSetUp(self) -> None:
        self.harness = await _ReceiverHarness().start()
        self.opened: list = []

    async def asyncTearDown(self) -> None:
        for websocket in self.opened:
            try:
                await websocket.close()
            except Exception:
                pass
        self.harness.receiver._server = self.harness.server
        await self.harness.stop()
        # I04 会在测试主体里主动 stop；这里再停一次以验证幂等性。
        await self.harness.stop()

    async def _connect(self, **kwargs):
        websocket, handshake = await self.harness.connect(**kwargs)
        self.opened.append(websocket)
        return websocket, handshake

    async def test_i01_authenticated_idle_then_first_request(self) -> None:
        websocket, handshake = await self._connect()
        self.assertEqual("authenticated", handshake.get("status"))
        self.assertEqual(PROTOCOL_VERSION, handshake.get("protocol_version"))
        self.assertIn(
            CAPABILITY_REQUEST_SCREENSHOT, handshake.get("capabilities", [])
        )

        # 空闲：不推送任何图片，接收器缓存为空。
        await asyncio.sleep(0.2)
        cached, _title, _meta = await self.harness.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        self.assertEqual(
            "capabilities_received", (await _negotiate(websocket)).get("status")
        )

        # 能力确认后立即发起首个请求，核对收到的是本次请求的帧。
        task = asyncio.ensure_future(self.harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertEqual("request_screenshot", command.get("type"))
        request_id = command["request_id"]

        meta_ack, binary_ack = await _upload_frame(websocket, request_id=request_id)
        self.assertEqual("meta_received", meta_ack.get("status"))
        self.assertEqual(request_id, meta_ack.get("request_id"))
        self.assertEqual("binary_screenshot_received", binary_ack.get("status"))
        self.assertEqual(request_id, binary_ack.get("request_id"))

        image, title, meta = await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual(JPEG, image)
        self.assertEqual("Editor", title)
        self.assertEqual(2, meta.get("protocol_version"))

    async def test_i02_wrong_token_is_rejected_and_not_routable(self) -> None:
        # 认证失败时服务端直接以 4001 关闭连接，不会返回握手正文。
        websocket = await websockets.connect(self.harness.url, close_timeout=1.0)
        self.opened.append(websocket)
        await websocket.send(json.dumps({"token": "wrong-token"}))
        with self.assertRaises(websockets.exceptions.ConnectionClosed) as ctx:
            await asyncio.wait_for(websocket.recv(), timeout=5.0)
        self.assertEqual(4001, ctx.exception.rcvd.code)

        await asyncio.sleep(0.2)
        self.assertFalse(self.harness.receiver.has_authenticated_client)
        self.assertFalse(self.harness.receiver.has_request_capable_client)
        with self.assertRaises(RemoteScreenshotError) as err:
            await self.harness.receiver.request_screenshot(timeout=1.0)
        self.assertEqual("no_client", err.exception.code)

    async def test_i03_disconnect_during_request_fails_without_full_timeout(
        self,
    ) -> None:
        harness = await _ReceiverHarness(request_timeout=30.0).start()
        self.harness.receiver._server = None
        self.harness = harness
        websocket, _handshake = await self._connect()
        await _negotiate(websocket)

        started_at = time.monotonic()
        task = asyncio.ensure_future(harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertEqual("request_screenshot", command.get("type"))

        await websocket.close()
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual("disconnected", ctx.exception.code)
        # 断线应立即结束请求，不必等满 30 秒预算。
        self.assertLess(time.monotonic() - started_at, 5.0)

    async def test_i04_stop_during_request_fails_and_closes_port(self) -> None:
        websocket, _handshake = await self._connect()
        await _negotiate(websocket)

        task = asyncio.ensure_future(self.harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertEqual("request_screenshot", command.get("type"))

        await self.harness.receiver.stop()
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual("stopped", ctx.exception.code)

        # 端口已关闭：新的连接尝试会失败。
        with self.assertRaises(OSError):
            await websockets.connect(self.harness.url, close_timeout=1.0)

    async def test_i05_video_upload_then_screenshot_request(self) -> None:
        websocket, _handshake = await self._connect()
        await _negotiate(websocket)

        # 顺序上传一段假视频。
        video = b"x" * 32
        upload_id = "video-int-1"
        await websocket.send(json.dumps({
            "type": "video_meta",
            "upload_id": upload_id,
            "total_size": len(video),
            "window_title": "Player",
        }))
        ready = await _recv_json(websocket)
        self.assertEqual("video_ready", ready.get("status"))

        await websocket.send(json.dumps({
            "type": "video_chunk",
            "upload_id": upload_id,
            "index": 0,
            "data": base64.b64encode(video).decode("ascii"),
        }))
        chunk_ack = await _recv_json(websocket)
        self.assertEqual("video_chunk_received", chunk_ack.get("status"))
        self.assertEqual(0, chunk_ack.get("index"))

        await websocket.send(json.dumps({
            "type": "video_complete", "upload_id": upload_id,
        }))
        complete = await _recv_json(websocket)
        self.assertEqual("video_complete", complete.get("status"))

        stored_video, video_meta = await self.harness.receiver.get_latest_video()
        self.assertEqual(video, stored_video)
        self.assertEqual("Player", video_meta.get("window_title"))

        # 随后仍可完成按需截图。
        task = asyncio.ensure_future(self.harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        await _upload_frame(websocket, request_id=command["request_id"])
        image, _title, _meta = await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual(JPEG, image)

    async def test_i06_legacy_client_protocol_remains_compatible(self) -> None:
        """旧协议客户端：不声明能力，按原有 meta/binary 与 bundle 工作。"""
        websocket, _handshake = await self._connect()

        meta_ack, binary_ack = await _upload_frame(
            websocket, image=JPEG, title="Legacy"
        )
        self.assertEqual("meta_received", meta_ack.get("status"))
        self.assertNotIn("request_id", meta_ack)
        self.assertEqual("binary_screenshot_received", binary_ack.get("status"))
        self.assertNotIn("request_id", binary_ack)

        cached, title, meta = await self.harness.receiver.get_latest_screenshot()
        self.assertEqual(JPEG, cached)
        self.assertEqual("Legacy", title)
        self.assertEqual(1, meta.get("protocol_version"))
        # 旧客户端不进入可请求目标。
        self.assertFalse(self.harness.receiver.has_request_capable_client)

        # bundle 路径同样可用。
        await websocket.send(json.dumps({
            "type": "screenshot_bundle",
            "image": base64.b64encode(ALT_JPEG).decode("ascii"),
            "window_title": "Bundle",
        }))
        bundle_ack = await _recv_json(websocket)
        self.assertEqual("screenshot_received", bundle_ack.get("status"))
        cached, title, _meta = await self.harness.receiver.get_latest_screenshot()
        self.assertEqual(ALT_JPEG, cached)
        self.assertEqual("Bundle", title)

    async def test_i07_busy_arrives_before_delayed_video_chunk_ack(self) -> None:
        """视频分块 ACK 延迟时，按需请求的 busy 仍能先到达。

        接收器本身不等待客户端 ACK，因此这里验证的是：在客户端尚未回复分块
        确认、服务端仍在处理视频事务的情况下，截图请求的 busy 不会被视频阻塞。
        """
        websocket, _handshake = await self._connect()
        await _negotiate(websocket)

        # 一个在途截图请求占住位置（服务端上限为 1）。
        first_task = asyncio.ensure_future(self.harness.receiver.request_screenshot())
        first_command = await _recv_json(websocket)

        # 第二个请求立即 busy，无需等待任何视频消息。
        started_at = time.monotonic()
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.harness.receiver.request_screenshot(timeout=5.0)
        self.assertEqual("busy", ctx.exception.code)
        self.assertLess(time.monotonic() - started_at, 1.0)

        # 视频事务照常完成，不受 busy 影响。
        video = b"y" * 16
        upload_id = "video-int-2"
        await websocket.send(json.dumps({
            "type": "video_meta",
            "upload_id": upload_id,
            "total_size": len(video),
        }))
        await _recv_json(websocket)
        await websocket.send(json.dumps({
            "type": "video_chunk",
            "upload_id": upload_id,
            "index": 0,
            "data": base64.b64encode(video).decode("ascii"),
        }))
        await _recv_json(websocket)
        await websocket.send(json.dumps({
            "type": "video_complete", "upload_id": upload_id,
        }))
        complete = await _recv_json(websocket)
        self.assertEqual("video_complete", complete.get("status"))
        stored_video, _meta = await self.harness.receiver.get_latest_video()
        self.assertEqual(video, stored_video)

        # 首个请求随后正常完成，未被插队或改写。
        await _upload_frame(websocket, request_id=first_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(first_task, timeout=5.0)
        self.assertEqual(JPEG, image)

    async def test_i08_late_jpeg_after_expiry_keeps_session_usable(self) -> None:
        harness = await _ReceiverHarness(request_timeout=0.3).start()
        self.harness.receiver._server = None
        self.harness = harness
        websocket, _handshake = await self._connect()
        await _negotiate(websocket)

        task = asyncio.ensure_future(harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        request_id = command["request_id"]

        # 先确认元数据，再让请求过期。
        await websocket.send(json.dumps({
            "type": "screenshot_meta",
            "window_title": "Late",
            "request_id": request_id,
        }))
        meta_ack = await _recv_json(websocket)
        self.assertEqual("meta_received", meta_ack.get("status"))
        self.assertEqual(request_id, meta_ack.get("request_id"))

        with self.assertRaises(RemoteScreenshotError):
            await asyncio.wait_for(task, timeout=5.0)

        # 迟到的 JPEG 被拒绝，但回显原编号，且不污染缓存。
        await websocket.send(JPEG)
        rejection = await _recv_json(websocket)
        self.assertEqual("expired_request", rejection.get("code"))
        self.assertEqual(request_id, rejection.get("request_id"))
        cached, _title, _meta = await harness.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        # 同一完整会话中，下一次有效请求可以成功。
        next_task = asyncio.ensure_future(harness.receiver.request_screenshot())
        next_command = await _recv_json(websocket)
        await _upload_frame(websocket, request_id=next_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(next_task, timeout=5.0)
        self.assertEqual(JPEG, image)

    async def test_i09_configured_client_token_is_accepted_by_no_auth_server(
        self,
    ) -> None:
        harness = await _ReceiverHarness(auth_token="").start()
        self.harness.receiver._server = None
        self.harness = harness

        websocket, handshake = await self._connect(token="configured-but-not-required")
        self.assertEqual("ready", handshake.get("status"))
        negotiated = await _negotiate(websocket)
        self.assertEqual("capabilities_received", negotiated.get("status"))
        self.assertTrue(harness.receiver.has_request_capable_client)

    async def test_tcp_port_is_bound_to_loopback_only(self) -> None:
        host = self.harness.server.sockets[0].getsockname()[0]
        self.assertEqual("127.0.0.1", host)


class RemoteWebSocketActiveWindowTests(unittest.IsolatedAsyncioTestCase):
    """I09～I11：活动窗口裁剪在真实连接上的协商与上报。"""

    async def asyncSetUp(self) -> None:
        self.opened: list = []

    async def asyncTearDown(self) -> None:
        for websocket in self.opened:
            try:
                await websocket.close()
            except Exception:
                pass
        if getattr(self, "harness", None) is not None:
            await self.harness.stop()

    async def _start(self, *, capture_active_window: bool) -> "_ReceiverHarness":
        harness = await _ReceiverHarness(
            capture_active_window=capture_active_window
        ).start()
        self.harness = harness
        websocket, _handshake = await harness.connect()
        self.opened.append(websocket)
        return harness, websocket

    async def test_i09_crop_flag_and_scope_round_trip(self) -> None:
        harness, websocket = await self._start(capture_active_window=True)
        reply = await _negotiate(
            websocket,
            capabilities=[
                CAPABILITY_REQUEST_SCREENSHOT,
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            ],
        )
        self.assertEqual({"capture_active_window": True}, reply.get("options"))

        task = asyncio.ensure_future(harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertTrue(command.get("capture_active_window"))

        await _upload_frame(
            websocket,
            request_id=command["request_id"],
            capture_scope="window",
        )
        image, title, meta = await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual(JPEG, image)
        self.assertEqual("Editor", title)
        # 实际范围随帧一起入库，便于排查"开关生效"与"回退全屏"两种情况。
        self.assertEqual("window", meta.get("capture_scope"))

    async def test_i10_client_without_capability_gets_no_flag(self) -> None:
        harness, websocket = await self._start(capture_active_window=True)
        await _negotiate(websocket)  # 只声明按需截图能力

        task = asyncio.ensure_future(harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertNotIn("capture_active_window", command)

        await _upload_frame(websocket, request_id=command["request_id"])
        _image, _title, meta = await asyncio.wait_for(task, timeout=5.0)
        self.assertFalse(meta.get("capture_scope"))

    async def test_i11_fullscreen_fallback_is_reported_honestly(self) -> None:
        harness, websocket = await self._start(capture_active_window=True)
        await _negotiate(
            websocket,
            capabilities=[
                CAPABILITY_REQUEST_SCREENSHOT,
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            ],
        )

        task = asyncio.ensure_future(harness.receiver.request_screenshot())
        command = await _recv_json(websocket)
        self.assertTrue(command.get("capture_active_window"))

        # 客户端声明有能力但本次矩形不可用：必须回退全屏并如实标注。
        await _upload_frame(
            websocket,
            request_id=command["request_id"],
            capture_scope="fullscreen",
        )
        _image, _title, meta = await asyncio.wait_for(task, timeout=5.0)
        self.assertEqual("fullscreen", meta.get("capture_scope"))


if __name__ == "__main__":
    unittest.main()
