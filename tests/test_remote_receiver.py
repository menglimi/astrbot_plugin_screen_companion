# -*- coding: utf-8 -*-
"""远程接收器协议、来源匹配、缓存一致性与路由回归测试。

覆盖 PR 方案第 18.1 节的 R01～R26；编号仅用于追踪行为覆盖，用例可合并或参数化。
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from astrbot_plugin_screen_companion.core.media import ScreenCompanionMediaMixin
from astrbot_plugin_screen_companion.core.remote_receiver import (
    CAPABILITY_CAPTURE_ACTIVE_WINDOW,
    CAPABILITY_REQUEST_SCREENSHOT,
    DEFAULT_REQUEST_TIMEOUT,
    META_TRANSACTION_TTL,
    PROTOCOL_VERSION,
    RemoteScreenReceiver,
    RemoteScreenshotError,
)

JPEG = b"\xff\xd8test\xff\xd9"


class FakeWebSocket:
    """测试替身：发送记录同时进入 asyncio 队列，便于确定性等待。"""

    def __init__(self, *, remote_address=("127.0.0.1", 12345)) -> None:
        self.sent: list[dict] = []
        self.raw: list = []
        self.remote_address = remote_address
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.close_code = None
        self.block_send = False
        self.send_calls = 0
        self.send_started = asyncio.Event()
        self._release_send = asyncio.Event()

    async def send(self, payload) -> None:
        self.send_calls += 1
        self.send_started.set()
        if self.block_send:
            await self._release_send.wait()
        self.raw.append(payload)
        if isinstance(payload, (bytes, bytearray)):
            await self.queue.put({"raw_bytes": bytes(payload)})
            return
        data = json.loads(payload)
        self.sent.append(data)
        await self.queue.put(data)

    async def recv(self):
        await asyncio.sleep(3600)

    def release_send(self) -> None:
        self._release_send.set()

    def reset_send_tracking(self) -> None:
        """重置发送计数与事件，使后续断言只观察本次动作。"""
        self.send_calls = 0
        self.send_started.clear()

    async def wait_for_send_calls(self, count: int, timeout: float = 1.0) -> None:
        """等待第 count 次发送开始，避免依赖固定 sleep。"""
        deadline = time.monotonic() + timeout
        while self.send_calls < count:
            if time.monotonic() >= deadline:
                raise AssertionError(f"等待第 {count} 次发送超时")
            await asyncio.sleep(0.005)

    async def close(self, code=1000, reason="") -> None:
        self.closed = True
        self.close_code = code

    async def next_message(self, timeout: float = 1.0) -> dict:
        return await asyncio.wait_for(self.queue.get(), timeout=timeout)

    def statuses(self) -> list[str]:
        return [item.get("status", "") for item in self.sent]


class ScriptedWebSocket(FakeWebSocket):
    """按脚本产出入站消息的测试替身。

    首条消息供认证阶段的一次 ``recv()`` 使用，其余消息供 ``async for`` 读取；
    脚本读完后保持连接，便于观察服务端的断开行为。
    """

    def __init__(self, messages, *, keep_open_seconds: float = 0.05, **kwargs):
        super().__init__(**kwargs)
        messages = list(messages)
        self._auth_message = messages[0] if messages else None
        self._stream_messages = messages[1:]
        self._keep_open_seconds = keep_open_seconds
        self._auth_consumed = False

    async def recv(self):
        if not self._auth_consumed:
            self._auth_consumed = True
            return self._auth_message
        await asyncio.sleep(3600)

    async def __aiter__(self):
        for message in self._stream_messages:
            yield message
        await asyncio.sleep(self._keep_open_seconds)


async def _authenticate(
    receiver: RemoteScreenReceiver,
    websocket: FakeWebSocket,
    *,
    capabilities=None,
) -> dict:
    """以 v2 客户端身份完成认证与能力协商，返回确认消息。"""
    receiver._connected_clients.add(websocket)
    declared = (
        [CAPABILITY_REQUEST_SCREENSHOT] if capabilities is None else list(capabilities)
    )
    await receiver._process_message(
        json.dumps({
            "type": "client_capabilities",
            "protocol_version": PROTOCOL_VERSION,
            "client_id": "desktop",
            "capabilities": declared,
        }),
        websocket,
    )
    reply = await websocket.next_message(timeout=1.0)  # capabilities_received
    # 清空握手痕迹，使后续断言只观察被测动作。
    websocket.sent.clear()
    websocket.reset_send_tracking()
    return reply


async def _start_request(
    receiver: RemoteScreenReceiver,
    websocket: FakeWebSocket,
    *,
    timeout: float | None = None,
):
    """发起一个按需请求任务，并等待服务端真的发出命令。"""
    if timeout is None:
        task = asyncio.ensure_future(receiver.request_screenshot())
    else:
        task = asyncio.ensure_future(receiver.request_screenshot(timeout=timeout))
    message = await websocket.next_message(timeout=1.0)
    return task, message


async def _wait_until_closed(websocket: FakeWebSocket, timeout: float = 1.0) -> None:
    """等待异步关闭收尾完成；关闭是有界的后台任务，不阻塞请求协程。"""
    deadline = time.monotonic() + timeout
    while not websocket.closed:
        if time.monotonic() >= deadline:
            raise AssertionError("等待连接关闭超时")
        await asyncio.sleep(0.005)


async def _send_binary_frame(
    receiver: RemoteScreenReceiver,
    websocket: FakeWebSocket,
    *,
    request_id: str = "",
    image: bytes = JPEG,
    title: str = "Editor",
    capture_scope: str = "",
) -> tuple[dict, dict]:
    """发送一帧「元数据 + 二进制」，返回两次确认消息。"""
    payload = {"type": "screenshot_meta", "window_title": title, "client_id": "desktop"}
    if request_id:
        payload["request_id"] = request_id
    if capture_scope:
        payload["capture_scope"] = capture_scope
    await receiver._process_message(json.dumps(payload), websocket)
    meta_ack = await websocket.next_message(timeout=1.0)
    await receiver._process_message(image, websocket)
    binary_ack = await websocket.next_message(timeout=1.0)
    return meta_ack, binary_ack


class RemoteReceiverRequestTests(unittest.IsolatedAsyncioTestCase):
    """R01～R18：请求生命周期、来源匹配与失败处理。"""

    def setUp(self) -> None:
        self.receiver = RemoteScreenReceiver(request_timeout=1.0)

    async def test_r01_returns_frame_bound_to_request_not_cached_image(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        # 先写入一张旧图。
        await _send_binary_frame(self.receiver, websocket, image=b"\xff\xd8old\xff\xd9")

        task, command = await _start_request(self.receiver, websocket)
        self.assertEqual("request_screenshot", command["type"])
        request_id = command["request_id"]

        # 结果尚未到达前不能提前返回旧图。
        await asyncio.sleep(0)
        self.assertFalse(task.done())

        meta_ack, binary_ack = await _send_binary_frame(
            self.receiver, websocket, request_id=request_id,
            image=b"\xff\xd8new\xff\xd9",
        )
        self.assertEqual(request_id, meta_ack.get("request_id"))
        self.assertEqual(request_id, binary_ack.get("request_id"))

        image, title, _meta = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(b"\xff\xd8new\xff\xd9", image)
        self.assertEqual("Editor", title)

    async def test_r02_first_request_without_warm_cache(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        self.assertFalse(self.receiver.has_screenshot)

        task, command = await _start_request(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=command["request_id"])
        image, _title, _meta = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r03_cache_stays_on_previous_frame_until_binary_arrives(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 image=b"\xff\xd8first\xff\xd9", title="First")

        task, command = await _start_request(self.receiver, websocket)
        # 只发送新元数据，尚未发送 JPEG。
        await self.receiver._process_message(
            json.dumps({
                "type": "screenshot_meta",
                "window_title": "Second",
                "request_id": command["request_id"],
            }),
            websocket,
        )
        await websocket.next_message(timeout=1.0)

        cached, title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"\xff\xd8first\xff\xd9", cached)
        self.assertEqual("First", title)
        self.assertFalse(task.done())

        await self.receiver._process_message(JPEG, websocket)
        await asyncio.wait_for(task, timeout=2.0)
        cached, title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(JPEG, cached)
        self.assertEqual("Second", title)

    async def test_r04_interleaved_connections_keep_own_metadata(self) -> None:
        first = FakeWebSocket()
        second = FakeWebSocket(remote_address=("127.0.0.1", 23456))
        await _authenticate(self.receiver, first)
        await _authenticate(self.receiver, second)

        await self.receiver._process_message(
            json.dumps({"type": "screenshot_meta", "window_title": "A"}), first
        )
        await self.receiver._process_message(
            json.dumps({"type": "screenshot_meta", "window_title": "B"}), second
        )
        await self.receiver._process_message(b"\xff\xd8A\xff\xd9", first)
        await self.receiver._process_message(b"\xff\xd8B\xff\xd9", second)

        cached, title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"\xff\xd8B\xff\xd9", cached)
        self.assertEqual("B", title)

    async def test_r05_response_from_wrong_connection_does_not_complete(self) -> None:
        target = FakeWebSocket()
        other = FakeWebSocket(remote_address=("127.0.0.1", 23456))
        await _authenticate(self.receiver, target)
        await _authenticate(self.receiver, other)
        # 另一端不具备截图能力，避免选目标时产生歧义。
        self.receiver._client_capabilities[other] = set()

        task, command = await _start_request(self.receiver, target)
        request_id = command["request_id"]
        # 另一条连接用同一个编号回帧：必须被拒绝。
        await _send_binary_frame(self.receiver, other, request_id=request_id,
                                 image=b"\xff\xd8evil\xff\xd9")
        self.assertFalse(task.done())

        cached, _title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        await _send_binary_frame(self.receiver, target, request_id=request_id)
        image, _title, _meta = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r06_second_request_is_busy_and_next_request_gets_new_id(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        first_task, first_command = await _start_request(self.receiver, websocket)
        websocket.reset_send_tracking()
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=5.0)
        self.assertEqual("busy", ctx.exception.code)
        # 繁忙时不发网络命令。
        self.assertEqual(0, websocket.send_calls)

        await _send_binary_frame(self.receiver, websocket,
                                 request_id=first_command["request_id"],
                                 image=b"\xff\xd8one\xff\xd9")
        await asyncio.wait_for(first_task, timeout=2.0)

        second_task, second_command = await _start_request(self.receiver, websocket)
        self.assertNotEqual(first_command["request_id"], second_command["request_id"])
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=second_command["request_id"],
                                 image=b"\xff\xd8two\xff\xd9")
        image, _title, _meta = await asyncio.wait_for(second_task, timeout=2.0)
        self.assertEqual(b"\xff\xd8two\xff\xd9", image)

    async def test_r07_plain_push_does_not_complete_pending_request(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        task, command = await _start_request(self.receiver, websocket)
        # 无编号的普通推送只更新缓存。
        await _send_binary_frame(self.receiver, websocket, image=b"\xff\xd8push\xff\xd9")
        self.assertFalse(task.done())
        cached, _title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"\xff\xd8push\xff\xd9", cached)

        await _send_binary_frame(self.receiver, websocket,
                                 request_id=command["request_id"],
                                 image=b"\xff\xd8answer\xff\xd9")
        image, _title, _meta = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(b"\xff\xd8answer\xff\xd9", image)

    async def test_r08_timeout_then_late_response_is_rejected(self) -> None:
        receiver = RemoteScreenReceiver(request_timeout=0.15)
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)

        task, command = await _start_request(receiver, websocket)
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("timeout", ctx.exception.code)
        self.assertEqual({}, receiver._pending_requests)

        await _send_binary_frame(receiver, websocket, request_id=command["request_id"],
                                 image=b"\xff\xd8late\xff\xd9")
        cached, _title, _meta = await receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

    async def test_r09_caller_cancel_propagates_and_next_request_succeeds(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        task, _command = await _start_request(self.receiver, websocket)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual({}, self.receiver._pending_requests)

        second_task, second_command = await _start_request(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=second_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(second_task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r10_capture_error_fails_request_without_cache_write(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        task, command = await _start_request(self.receiver, websocket)
        await self.receiver._process_message(
            json.dumps({
                "type": "capture_error",
                "request_id": command["request_id"],
                "code": "busy",
                "error": "已有任务",
            }),
            websocket,
        )
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("busy", ctx.exception.code)

        cached, _title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        # 后续请求仍可正常完成。
        next_task, next_command = await _start_request(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=next_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(next_task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r10b_unknown_capture_error_code_degrades_to_capture_failed(
        self,
    ) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        task, command = await _start_request(self.receiver, websocket)
        await self.receiver._process_message(
            json.dumps({
                "type": "capture_error",
                "request_id": command["request_id"],
                "code": "totally_unknown",
                "error": "x",
            }),
            websocket,
        )
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("capture_failed", ctx.exception.code)

    async def test_r11_invalid_jpeg_and_invalid_bundle_fail_immediately(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        task, command = await _start_request(self.receiver, websocket)
        # 无效 JPEG 只回一条错误，不会再有二进制确认。
        await self.receiver._process_message(
            json.dumps({
                "type": "screenshot_meta",
                "window_title": "Bad",
                "request_id": command["request_id"],
            }),
            websocket,
        )
        await websocket.next_message(timeout=1.0)
        await self.receiver._process_message(b"not-a-jpeg", websocket)
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("invalid_frame", ctx.exception.code)
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("invalid_frame", reply.get("code"))
        self.assertEqual(command["request_id"], reply.get("request_id"))
        cached, _title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)
        self.assertEqual({}, self.receiver._pending_screenshot_meta)

        # 无效 Base64 bundle。
        bundle_task, bundle_command = await _start_request(self.receiver, websocket)
        await self.receiver._process_message(
            json.dumps({
                "type": "screenshot_bundle",
                "request_id": bundle_command["request_id"],
                "image": "!!!not-base64!!!",
            }),
            websocket,
        )
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(bundle_task, timeout=2.0)
        self.assertEqual("invalid_frame", ctx.exception.code)
        bundle_reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("invalid_frame", bundle_reply.get("code"))
        self.assertEqual(bundle_command["request_id"], bundle_reply.get("request_id"))

        # 下一请求正常。
        final_task, final_command = await _start_request(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=final_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(final_task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r12_v2_bare_jpeg_rejected_while_legacy_bare_jpeg_keeps_title_empty(
        self,
    ) -> None:
        v2_socket = FakeWebSocket()
        await _authenticate(self.receiver, v2_socket)
        await self.receiver._process_message(JPEG, v2_socket)
        reply = await v2_socket.next_message(timeout=1.0)
        self.assertEqual("invalid_frame", reply.get("code"))
        cached, _title, _meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        # 旧客户端（未声明能力）的裸 JPEG 兼容路径仍然成立，标题为空。
        legacy_socket = FakeWebSocket(remote_address=("127.0.0.1", 34567))
        self.receiver._connected_clients.add(legacy_socket)
        await self.receiver._process_message(JPEG, legacy_socket)
        await legacy_socket.next_message(timeout=1.0)
        cached, title, meta = await self.receiver.get_latest_screenshot()
        self.assertEqual(JPEG, cached)
        self.assertEqual("", title)
        self.assertEqual(1, meta.get("protocol_version"))
        self.assertEqual(1, self.receiver.latest_protocol_version)

    async def test_r13_binary_and_bundle_share_request_binding(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        binary_task, binary_command = await _start_request(self.receiver, websocket)
        await _send_binary_frame(self.receiver, websocket,
                                 request_id=binary_command["request_id"],
                                 image=b"\xff\xd8bin\xff\xd9")
        image, _title, _meta = await asyncio.wait_for(binary_task, timeout=2.0)
        self.assertEqual(b"\xff\xd8bin\xff\xd9", image)

        bundle_task, bundle_command = await _start_request(self.receiver, websocket)
        await self.receiver._process_message(
            json.dumps({
                "type": "screenshot_bundle",
                "request_id": bundle_command["request_id"],
                "window_title": "Bundle",
                "image": base64.b64encode(b"\xff\xd8bundle\xff\xd9").decode("ascii"),
            }),
            websocket,
        )
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("screenshot_received", reply.get("status"))
        self.assertEqual(bundle_command["request_id"], reply.get("request_id"))
        image, title, _meta = await asyncio.wait_for(bundle_task, timeout=2.0)
        self.assertEqual(b"\xff\xd8bundle\xff\xd9", image)
        self.assertEqual("Bundle", title)

    async def test_r14_multiple_capable_clients_are_ambiguous_without_broadcast(
        self,
    ) -> None:
        first = FakeWebSocket()
        second = FakeWebSocket(remote_address=("127.0.0.1", 23456))
        await _authenticate(self.receiver, first)
        await _authenticate(self.receiver, second)

        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=5.0)
        self.assertEqual("ambiguous_client", ctx.exception.code)
        # 没有向任意连接发送命令。
        self.assertEqual([], first.sent)
        self.assertEqual([], second.sent)

    async def test_r15_video_only_client_is_not_a_capture_target(self) -> None:
        capture = FakeWebSocket()
        video_only = FakeWebSocket(remote_address=("127.0.0.1", 23456))
        await _authenticate(self.receiver, capture)
        self.receiver._connected_clients.add(video_only)
        self.receiver._client_capabilities[video_only] = set()

        task, command = await _start_request(self.receiver, capture)
        self.assertEqual("request_screenshot", command["type"])
        self.assertEqual([], video_only.sent)
        await _send_binary_frame(self.receiver, capture, request_id=command["request_id"])
        image, _title, _meta = await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r16_unauthenticated_capability_declaration_is_rejected(self) -> None:
        websocket = FakeWebSocket()
        await self.receiver._process_message(
            json.dumps({
                "type": "client_capabilities",
                "protocol_version": PROTOCOL_VERSION,
                "capabilities": [CAPABILITY_REQUEST_SCREENSHOT],
            }),
            websocket,
        )
        self.assertFalse(self.receiver.has_request_capable_client)
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=1.0)
        self.assertEqual("no_client", ctx.exception.code)

    async def test_r16b_authenticated_client_without_capability_is_unsupported(
        self,
    ) -> None:
        websocket = FakeWebSocket()
        self.receiver._connected_clients.add(websocket)
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=1.0)
        self.assertEqual("unsupported_client", ctx.exception.code)

    async def test_r17_send_backpressure_ends_request_early_on_stop(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        websocket.block_send = True

        task = asyncio.ensure_future(self.receiver.request_screenshot(timeout=10.0))
        await asyncio.wait_for(websocket.send_started.wait(), timeout=1.0)
        await self.receiver.stop()

        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("stopped", ctx.exception.code)

    async def test_r17b_disconnect_ends_request_early(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        websocket.block_send = True

        task = asyncio.ensure_future(self.receiver.request_screenshot(timeout=10.0))
        await asyncio.wait_for(websocket.send_started.wait(), timeout=1.0)
        self.receiver._cleanup_client(websocket)

        with self.assertRaises(RemoteScreenshotError) as ctx:
            await asyncio.wait_for(task, timeout=2.0)
        self.assertEqual("disconnected", ctx.exception.code)
        self.assertEqual({}, self.receiver._pending_requests)

    async def test_r17c_send_failure_maps_to_dedicated_error(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        async def failing_send(_payload):
            raise ConnectionResetError("boom")

        websocket.send = failing_send
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=2.0)
        self.assertEqual("disconnected", ctx.exception.code)
        self.assertEqual({}, self.receiver._pending_requests)

    async def test_r18_stop_rejects_new_requests_and_is_idempotent(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)

        await self.receiver.stop()
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await self.receiver.request_screenshot(timeout=1.0)
        self.assertEqual("stopped", ctx.exception.code)
        # 重复 stop 安全。
        await self.receiver.stop()
        self.assertFalse(self.receiver.has_request_capable_client)

    async def test_r18b_capability_registration_after_stop_is_rejected(self) -> None:
        websocket = FakeWebSocket()
        self.receiver._connected_clients.add(websocket)
        await self.receiver.stop()
        await self.receiver._process_message(
            json.dumps({
                "type": "client_capabilities",
                "capabilities": [CAPABILITY_REQUEST_SCREENSHOT],
            }),
            websocket,
        )
        self.assertFalse(self.receiver.has_request_capable_client)

    async def test_duplicate_meta_for_same_connection_is_protocol_error(self) -> None:
        websocket = FakeWebSocket()
        await _authenticate(self.receiver, websocket)
        await self.receiver._process_message(
            json.dumps({"type": "screenshot_meta", "window_title": "One"}), websocket
        )
        await websocket.next_message(timeout=1.0)
        await self.receiver._process_message(
            json.dumps({"type": "screenshot_meta", "window_title": "Two"}), websocket
        )
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("protocol_error", reply.get("code"))
        self.assertEqual({}, self.receiver._pending_screenshot_meta)
        await _wait_until_closed(websocket)


class RemoteReceiverActiveWindowTests(unittest.IsolatedAsyncioTestCase):
    """活动窗口裁剪的协议协商、命令下发与实际范围记录。"""

    async def test_request_carries_flag_for_capable_client(self) -> None:
        receiver = RemoteScreenReceiver(capture_active_window=True)
        websocket = FakeWebSocket()
        await _authenticate(
            receiver,
            websocket,
            capabilities=[
                CAPABILITY_REQUEST_SCREENSHOT,
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            ],
        )

        task, command = await _start_request(receiver, websocket)

        self.assertTrue(command.get("capture_active_window"))
        self.assertTrue(receiver.has_active_window_capable_client)
        await _send_binary_frame(
            receiver,
            websocket,
            request_id=command["request_id"],
            capture_scope="window",
        )
        await asyncio.wait_for(task, timeout=2.0)

    async def test_request_omits_flag_for_client_without_capability(self) -> None:
        receiver = RemoteScreenReceiver(capture_active_window=True)
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)  # 只声明按需截图能力

        task, command = await _start_request(receiver, websocket)

        # 不能向不支持的客户端下发范围要求，否则它只能忽略或报错。
        self.assertNotIn("capture_active_window", command)
        self.assertFalse(receiver.has_active_window_capable_client)
        await _send_binary_frame(receiver, websocket, request_id=command["request_id"])
        await asyncio.wait_for(task, timeout=2.0)

    async def test_request_omits_flag_when_server_setting_is_off(self) -> None:
        receiver = RemoteScreenReceiver(capture_active_window=False)
        websocket = FakeWebSocket()
        await _authenticate(
            receiver,
            websocket,
            capabilities=[
                CAPABILITY_REQUEST_SCREENSHOT,
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            ],
        )

        task, command = await _start_request(receiver, websocket)

        self.assertNotIn("capture_active_window", command)
        await _send_binary_frame(receiver, websocket, request_id=command["request_id"])
        await asyncio.wait_for(task, timeout=2.0)

    async def test_capabilities_reply_carries_server_option(self) -> None:
        receiver = RemoteScreenReceiver(capture_active_window=True)
        websocket = FakeWebSocket()
        reply = await _authenticate(
            receiver,
            websocket,
            capabilities=[
                CAPABILITY_REQUEST_SCREENSHOT,
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            ],
        )

        self.assertEqual(
            {"capture_active_window": True}, reply.get("options")
        )

    async def test_capabilities_reply_reports_disabled_option(self) -> None:
        receiver = RemoteScreenReceiver(capture_active_window=False)
        websocket = FakeWebSocket()
        reply = await _authenticate(receiver, websocket)

        self.assertEqual(
            {"capture_active_window": False}, reply.get("options")
        )

    async def test_capture_scope_is_recorded_in_cached_meta(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)

        await _send_binary_frame(
            receiver,
            websocket,
            title="Editor",
            capture_scope="window",
        )

        _image, _title, meta = await receiver.get_latest_screenshot()
        self.assertEqual("window", meta.get("capture_scope"))

    async def test_capture_scope_is_recorded_for_bundle(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)

        await receiver._process_message(
            json.dumps({
                "type": "screenshot_bundle",
                "window_title": "Bundle",
                "capture_scope": "fullscreen",
                "image": base64.b64encode(JPEG).decode("ascii"),
            }),
            websocket,
        )
        await websocket.next_message(timeout=1.0)

        _image, _title, meta = await receiver.get_latest_screenshot()
        self.assertEqual("fullscreen", meta.get("capture_scope"))

    async def test_legacy_bare_jpeg_has_no_scope(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        receiver._connected_clients.add(websocket)

        await receiver._process_message(JPEG, websocket)
        await websocket.next_message(timeout=1.0)

        _image, _title, meta = await receiver.get_latest_screenshot()
        # 旧客户端不声明范围，不能替它编造一个值。
        self.assertFalse(meta.get("capture_scope"))


class RemoteReceiverCropWarningTests(unittest.IsolatedAsyncioTestCase):
    """插件承诺窗口裁剪但客户端回退全屏时必须留下可排查记录。"""

    @staticmethod
    def _make_plugin(receiver) -> ScreenCompanionMediaMixin:
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.capture_active_window = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0
        return plugin

    async def test_fullscreen_fallback_is_warned_and_rate_limited(self) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(
                return_value=(JPEG, "Editor", {"capture_scope": "fullscreen"})
            ),
        )
        plugin = self._make_plugin(receiver)

        with patch(
            "astrbot_plugin_screen_companion.core.media.logger.warning"
        ) as warn_mock:
            await plugin._capture_screen_bytes()
            await plugin._capture_screen_bytes()

        # 降级要可见，但不能每次识屏都刷屏。
        self.assertEqual(1, warn_mock.call_count)
        self.assertIn("全屏截图", warn_mock.call_args.args[0])

    async def test_window_scope_does_not_warn(self) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(
                return_value=(JPEG, "Editor", {"capture_scope": "window"})
            ),
        )
        plugin = self._make_plugin(receiver)

        with patch(
            "astrbot_plugin_screen_companion.core.media.logger.warning"
        ) as warn_mock:
            await plugin._capture_screen_bytes()

        warn_mock.assert_not_called()

    async def test_warning_skipped_when_setting_is_off(self) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(
                return_value=(JPEG, "Editor", {"capture_scope": "fullscreen"})
            ),
        )
        plugin = self._make_plugin(receiver)
        plugin.capture_active_window = False

        with patch(
            "astrbot_plugin_screen_companion.core.media.logger.warning"
        ) as warn_mock:
            await plugin._capture_screen_bytes()

        # 用户没要求裁剪时全屏是正常结果，不该报警告。
        warn_mock.assert_not_called()


class RemoteReceiverCacheCompatTests(unittest.IsolatedAsyncioTestCase):
    """R19～R21、R25、R26：缓存兼容、时钟与事务保留。"""

    async def test_r19_legacy_force_and_expired_cache_paths(self) -> None:
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0

        legacy_receiver = SimpleNamespace(
            has_request_capable_client=False,
            has_authenticated_client=True,
            get_latest_screenshot=AsyncMock(
                return_value=(JPEG, "Legacy", {"protocol_version": 1})
            ),
            latest_age_seconds=0.5,
        )
        plugin._remote_receiver = legacy_receiver
        image, title = await plugin._capture_screen_bytes()
        self.assertEqual(JPEG, image)
        self.assertEqual("Legacy", title)
        self.assertEqual(
            60, legacy_receiver.get_latest_screenshot.await_args.kwargs.get("max_age")
        )

        # 强制重拍：旧客户端必须明确提示升级，而不是回退缓存。
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await plugin._capture_screen_bytes(force_fresh_capture=True)
        self.assertEqual("unsupported_client", ctx.exception.code)

        # 过期缓存被拒绝。
        legacy_receiver.get_latest_screenshot = AsyncMock(
            side_effect=RemoteScreenshotError("stale_cache", "stale")
        )
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await plugin._capture_screen_bytes()
        self.assertEqual("stale_cache", ctx.exception.code)

    async def test_r19b_force_capture_without_client_reports_no_client(self) -> None:
        receiver = RemoteScreenReceiver()
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0

        with self.assertRaises(RemoteScreenshotError) as ctx:
            await plugin._capture_screen_bytes(force_fresh_capture=True)

        self.assertEqual("no_client", ctx.exception.code)

    async def test_r20_v2_cache_is_not_reusable_as_legacy_push(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)
        await _send_binary_frame(receiver, websocket)
        # 新版客户端断开。
        receiver._cleanup_client(websocket)

        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await plugin._capture_screen_bytes()
        self.assertEqual("no_client", ctx.exception.code)
        # 缓存本身仍然可读（只读语义保持）。
        cached, _title, _meta = await receiver.get_latest_screenshot()
        self.assertEqual(JPEG, cached)

    async def test_r21_cache_age_uses_monotonic_clock(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)
        await _send_binary_frame(receiver, websocket)

        self.assertLess(receiver.latest_age_seconds, 1.0)
        # 模拟墙钟大幅回退：单调时钟年龄不受影响，也不会突然过期。
        receiver._latest_timestamp = time.time() - 10_000
        self.assertLess(receiver.latest_age_seconds, 1.0)

    async def test_r21b_get_latest_screenshot_enforces_max_age(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)
        await _send_binary_frame(receiver, websocket)

        image, _title, _meta = await receiver.get_latest_screenshot(max_age=60)
        self.assertEqual(JPEG, image)

        # 把接收时刻推到过去：读取与过期检查必须在同一把锁内完成。
        receiver._latest_received_monotonic -= 120.0
        with self.assertRaises(RemoteScreenshotError) as ctx:
            await receiver.get_latest_screenshot(max_age=60)
        self.assertEqual("stale_cache", ctx.exception.code)

    async def test_r25_late_jpeg_after_meta_ack_is_rejected_with_original_id(
        self,
    ) -> None:
        receiver = RemoteScreenReceiver(request_timeout=0.15)
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)

        task, command = await _start_request(receiver, websocket)
        request_id = command["request_id"]
        await receiver._process_message(
            json.dumps({
                "type": "screenshot_meta",
                "window_title": "Late",
                "request_id": request_id,
            }),
            websocket,
        )
        await websocket.next_message(timeout=1.0)

        with self.assertRaises(RemoteScreenshotError):
            await asyncio.wait_for(task, timeout=2.0)

        await receiver._process_message(JPEG, websocket)
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("expired_request", reply.get("code"))
        self.assertEqual(request_id, reply.get("request_id"))
        cached, _title, _meta = await receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        # 同一完整会话中仍可恢复处理下一次请求。
        next_task, next_command = await _start_request(receiver, websocket)
        await _send_binary_frame(receiver, websocket,
                                 request_id=next_command["request_id"])
        image, _title, _meta = await asyncio.wait_for(next_task, timeout=2.0)
        self.assertEqual(JPEG, image)

    async def test_r26_expired_deadline_rejects_frame_even_if_future_pending(
        self,
    ) -> None:
        receiver = RemoteScreenReceiver(request_timeout=5.0)
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)

        task, command = await _start_request(receiver, websocket)
        request_id = command["request_id"]
        # 人为把 deadline 推到过去：模拟事件循环繁忙、超时回调尚未执行的状态。
        pending = receiver._pending_requests[request_id]
        pending.deadline = time.monotonic() - 0.01
        self.assertFalse(pending.future.done())
        self.assertIsNone(receiver._active_pending(request_id))

        # 帧头直接被判定为过期，不写入暂存区。
        await receiver._process_message(
            json.dumps({
                "type": "screenshot_meta",
                "window_title": "Expired",
                "request_id": request_id,
            }),
            websocket,
        )
        meta_reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("expired_request", meta_reply.get("code"))
        self.assertEqual(request_id, meta_reply.get("request_id"))
        self.assertEqual({}, receiver._pending_screenshot_meta)

        # 随后的二进制图也不能提交缓存。
        await receiver._process_message(b"\xff\xd8expired\xff\xd9", websocket)
        binary_reply = await websocket.next_message(timeout=1.0)
        self.assertIn(binary_reply.get("code"), {"expired_request", "invalid_frame"})
        cached, _title, _meta = await receiver.get_latest_screenshot()
        self.assertEqual(b"", cached)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual({}, receiver._pending_requests)

    async def test_stale_v2_meta_header_closes_transaction(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await _authenticate(receiver, websocket)
        await receiver._process_message(
            json.dumps({"type": "screenshot_meta", "window_title": "Stale"}),
            websocket,
        )
        await websocket.next_message(timeout=1.0)
        stored = receiver._pending_screenshot_meta[websocket]
        stored.received_monotonic = time.monotonic() - (META_TRANSACTION_TTL + 1)

        await receiver._process_message(JPEG, websocket)
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("expired_request", reply.get("code"))
        await _wait_until_closed(websocket)


class RemoteReceiverRoutingTests(unittest.IsolatedAsyncioTestCase):
    """R22～R24：媒体入口接线与录屏锚点。"""

    @staticmethod
    def _make_plugin(receiver) -> ScreenCompanionMediaMixin:
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0
        return plugin

    async def test_r22_remote_image_entry_requests_fresh_frame_without_cache(
        self,
    ) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(return_value=(JPEG, "Editor", {})),
            get_latest_screenshot=AsyncMock(),
        )
        plugin = self._make_plugin(receiver)

        image, title = await plugin._capture_screen_bytes(force_fresh_capture=True)

        self.assertEqual(JPEG, image)
        self.assertEqual("Editor", title)
        receiver.request_screenshot.assert_awaited_once()
        receiver.get_latest_screenshot.assert_not_called()
        budget = receiver.request_screenshot.await_args.kwargs.get("timeout")
        self.assertIsNotNone(budget)
        self.assertLess(float(budget), 20.0)

    async def test_r22b_capable_client_is_used_even_without_force(self) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(return_value=(JPEG, "Editor", {})),
        )
        plugin = self._make_plugin(receiver)

        await plugin._capture_screen_bytes(force_fresh_capture=False)

        receiver.request_screenshot.assert_awaited_once()

    async def test_r22c_request_failure_does_not_fall_back_to_cache(self) -> None:
        receiver = SimpleNamespace(
            has_request_capable_client=True,
            request_screenshot=AsyncMock(
                side_effect=RemoteScreenshotError("timeout", "timeout")
            ),
            get_latest_screenshot=AsyncMock(return_value=(JPEG, "Cached", {})),
        )
        plugin = self._make_plugin(receiver)

        with self.assertRaises(RemoteScreenshotError):
            await plugin._capture_screen_bytes(force_fresh_capture=True)
        receiver.get_latest_screenshot.assert_not_called()

    async def test_r22d_timeout_budget_stays_below_outer_capture_timeout(self) -> None:
        plugin = ScreenCompanionMediaMixin()
        plugin._get_capture_context_timeout = lambda media_kind=None: 20.0
        self.assertEqual(DEFAULT_REQUEST_TIMEOUT, plugin._get_remote_screenshot_timeout())

        plugin._get_capture_context_timeout = lambda media_kind=None: 6.0
        self.assertLessEqual(plugin._get_remote_screenshot_timeout(), 5.0)

    async def test_r23_prepared_capture_context_is_not_re_captured(self) -> None:
        plugin = ScreenCompanionMediaMixin()
        capture_calls = []

        async def fail_capture(**kwargs):
            capture_calls.append(kwargs)
            raise AssertionError("不应再次采集")

        plugin._capture_recognition_context = fail_capture
        plugin.debug = False
        plugin._get_screen_analysis_timeout = lambda media_kind: 5.0
        plugin._save_screen_capture_debug_files = lambda *a, **k: []
        plugin._analyze_screen = AsyncMock(return_value=[])
        plugin._remember_recent_assistant_reply = lambda *a, **k: None
        plugin._remember_recent_companion_message = lambda *a, **k: None
        plugin._remember_screen_analysis_trace = lambda *a, **k: None
        plugin.context = SimpleNamespace()

        result = await plugin._run_screen_assist(
            SimpleNamespace(unified_msg_origin="test:1"),
            capture_context={"media_kind": "image", "media_bytes": JPEG},
        )

        self.assertIsNone(result)
        self.assertEqual([], capture_calls)

    async def test_r24_remote_video_context_drops_stale_image_anchor(self) -> None:
        receiver = SimpleNamespace(
            is_running=True,
            latest_video_age_seconds=0.1,
            get_latest_video=AsyncMock(
                return_value=(b"mp4", {"mime_type": "video/mp4", "window_title": "Player"})
            ),
            get_latest_screenshot=AsyncMock(
                return_value=(b"\xff\xd8other-window\xff\xd9", "Other Window", {})
            ),
        )
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.screen_recognition_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )

        result = await plugin._capture_recording_context()

        self.assertEqual("video", result["media_kind"])
        self.assertEqual(b"mp4", result["media_bytes"])
        self.assertEqual("Player", result["active_window_title"])
        # 不把另一窗口的旧截图当成"现在"的实时锚点。
        self.assertEqual(b"", result["latest_image_bytes"])
        self.assertNotIn("Other Window", repr(result))
        receiver.get_latest_screenshot.assert_not_called()

    async def test_r24b_remote_video_without_title_uses_generic_label(self) -> None:
        receiver = SimpleNamespace(
            is_running=True,
            latest_video_age_seconds=0.1,
            get_latest_video=AsyncMock(return_value=(b"mp4", {"mime_type": "video/mp4"})),
        )
        plugin = ScreenCompanionMediaMixin()
        plugin.remote_mode = True
        plugin.screen_recognition_mode = True
        plugin.remote_screenshot_max_age = 60
        plugin._remote_receiver = receiver
        plugin._get_runtime_flag = lambda name, default=False: bool(
            getattr(plugin, name, default)
        )

        result = await plugin._capture_recording_context()

        self.assertEqual("远程客户端录屏", result["active_window_title"])
        self.assertEqual(b"", result["latest_image_bytes"])


class RemoteReceiverBackwardCompatTests(unittest.IsolatedAsyncioTestCase):
    """原有服务端行为回归：旧推送、视频分块、bundle 与握手。"""

    async def test_binary_screenshot_updates_timestamp_and_ack(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        image = b"\xff\xd8test\xff\xd9"

        await receiver._process_message(
            json.dumps(
                {
                    "type": "screenshot_meta",
                    "window_title": "Editor",
                    "client_id": "desktop",
                }
            ),
            websocket,
        )
        await receiver._process_message(image, websocket)

        latest, title, _meta = await receiver.get_latest_screenshot()
        self.assertEqual(image, latest)
        self.assertEqual("Editor", title)
        self.assertEqual(
            ["meta_received", "binary_screenshot_received"], websocket.statuses()
        )
        self.assertLess(receiver.latest_age_seconds, 1)

    async def test_video_chunks_are_reassembled_only_after_complete(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        video = b"video-payload"
        upload_id = "upload-1"

        await receiver._process_message(
            json.dumps(
                {
                    "type": "video_meta",
                    "upload_id": upload_id,
                    "total_size": len(video),
                    "window_title": "Player",
                }
            ),
            websocket,
        )
        midpoint = len(video) // 2
        for index, chunk in ((1, video[midpoint:]), (0, video[:midpoint])):
            await receiver._process_message(
                json.dumps(
                    {
                        "type": "video_chunk",
                        "upload_id": upload_id,
                        "index": index,
                        "data": base64.b64encode(chunk).decode("ascii"),
                    }
                ),
                websocket,
            )

        before_complete, _ = await receiver.get_latest_video()
        self.assertEqual(b"", before_complete)
        await receiver._process_message(
            json.dumps({"type": "video_complete", "upload_id": upload_id}),
            websocket,
        )
        latest, meta = await receiver.get_latest_video()
        self.assertEqual(video, latest)
        self.assertEqual("Player", meta["window_title"])
        self.assertEqual("video_complete", websocket.sent[-1]["status"])

    async def test_legacy_bundle_updates_cache_and_meta(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await receiver._process_message(
            json.dumps(
                {
                    "type": "screenshot_bundle",
                    "image": base64.b64encode(JPEG).decode("ascii"),
                    "window_title": "Bundle",
                }
            ),
            websocket,
        )
        image, title, meta = await receiver.get_latest_screenshot()
        self.assertEqual(JPEG, image)
        self.assertEqual("Bundle", title)
        self.assertEqual("screenshot_received", websocket.sent[-1]["status"])
        self.assertEqual(1, meta.get("protocol_version"))

    async def test_authentication_handshake_announces_protocol(self) -> None:
        receiver = RemoteScreenReceiver(auth_token="secret")
        websocket = ScriptedWebSocket([json.dumps({"token": "secret"})])

        await receiver._handle_client(websocket)

        self.assertEqual("authenticated", websocket.sent[0]["status"])
        self.assertEqual(PROTOCOL_VERSION, websocket.sent[0]["protocol_version"])
        self.assertIn(
            CAPABILITY_REQUEST_SCREENSHOT, websocket.sent[0]["capabilities"]
        )

    async def test_failed_authentication_is_not_routable(self) -> None:
        receiver = RemoteScreenReceiver(auth_token="secret")
        websocket = ScriptedWebSocket([json.dumps({"token": "wrong"})])

        await receiver._handle_client(websocket)

        self.assertEqual(4001, websocket.close_code)
        self.assertFalse(receiver.has_authenticated_client)
        self.assertFalse(receiver.has_request_capable_client)

    async def test_ping_still_returns_pong(self) -> None:
        receiver = RemoteScreenReceiver()
        websocket = FakeWebSocket()
        await receiver._process_message(json.dumps({"type": "ping"}), websocket)
        reply = await websocket.next_message(timeout=1.0)
        self.assertEqual("pong", reply.get("type"))


class MediaRoutingTests(unittest.IsolatedAsyncioTestCase):
    """原有媒体路由回归。"""

    async def test_remote_environment_check_does_not_probe_local_display(self) -> None:
        plugin = ScreenCompanionMediaMixin()
        plugin._get_runtime_flag = lambda name, default=False: name == "remote_mode"
        plugin._use_screen_recording_mode = lambda: False
        plugin._check_screenshot_env = lambda check_mic=False: (True, "")

        self.assertEqual((True, ""), plugin._check_env())

    async def test_configured_vision_provider_precedes_global_caption_provider(self) -> None:
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(completion_text="识别结果")
            )
        )
        plugin = ScreenCompanionMediaMixin()
        plugin.vision_provider_id = "configured-vision"
        get_provider_by_id = Mock(return_value=provider)
        plugin.context = SimpleNamespace(get_provider_by_id=get_provider_by_id)
        plugin._get_astrbot_image_caption_settings = lambda: {
            "provider_id": "global-caption"
        }
        plugin._build_vision_prompt = lambda scene, active_window_title: "描述画面"

        result = await plugin._call_astrbot_image_caption_provider(
            media_bytes=b"jpeg",
            mime_type="image/jpeg",
            scene="编程",
            active_window_title="Editor",
        )

        self.assertEqual("识别结果", result)
        get_provider_by_id.assert_called_once_with("configured-vision")
        provider.text_chat.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
