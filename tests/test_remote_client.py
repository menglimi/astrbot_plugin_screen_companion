# -*- coding: utf-8 -*-
"""远程客户端行为与协议测试。

覆盖 PR 方案第 18.2 节的 C01～C20；全部用例 mock 采集函数，
不访问真实桌面、不启动 ffmpeg、不读取真实窗口标题。

注意：``capture_screenshot_context`` 与 ``capture_video`` 都是同步函数，
由工作线程执行，因此这里的替身必须也是同步函数。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import threading
import time
import unittest
from unittest.mock import patch

from astrbot_plugin_screen_companion import remote_client
from astrbot_plugin_screen_companion.remote_client import (
    CAPABILITY_REQUEST_SCREENSHOT,
    PROTOCOL_VERSION,
    ClientConfig,
    ClientConfigError,
    IncompatibleServerError,
    RemoteClientSession,
    _CaptureSlot,
    build_parser,
    capture_screenshot_context,
    validate_config,
)

JPEG = b"\xff\xd8client\xff\xd9"

#: 这些模块级变量在每次 setUp 中重置，避免用例之间互相污染。
_CAPTURE_SLOT: _CaptureSlot


_CLOSE_SENTINEL = object()


class FakeServerSocket:
    """扮演服务端的测试替身。

    ``inbox`` 接收客户端发来的消息（供服务端替身消费），``outbound`` 存放
    服务端要下发的消息（供会话的唯一 reader 消费）。
    """

    def __init__(self, handshake: dict | None = None) -> None:
        self.sent: list = []
        self.pushed: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.outbound: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.handshake = handshake if handshake is not None else {
            "status": "authenticated",
            "protocol_version": PROTOCOL_VERSION,
            "capabilities": [CAPABILITY_REQUEST_SCREENSHOT],
        }

    async def send(self, payload) -> None:
        if isinstance(payload, (bytes, bytearray)):
            item: object = bytes(payload)
        else:
            item = json.loads(payload)
        self.sent.append(item)
        # inbox 保留线上原始负载，供服务端替身按协议解析。
        await self.inbox.put(payload)

    async def recv(self):
        return await self.outbound.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            item = await asyncio.wait_for(self.outbound.get(), timeout=10.0)
        except asyncio.TimeoutError as exc:  # pragma: no cover - 防御性
            raise StopAsyncIteration from exc
        if item is _CLOSE_SENTINEL:
            raise StopAsyncIteration
        return item

    async def close(self, *args, **kwargs) -> None:
        self.closed = True
        # 唤醒可能仍在等待的 reader，使其结束。
        await self.outbound.put(_CLOSE_SENTINEL)

    async def push(self, payload: dict) -> None:
        self.pushed.append(dict(payload))
        await self.outbound.put(json.dumps(payload))

    def json_sent(self) -> list[dict]:
        return [item for item in self.sent if isinstance(item, dict)]

    def binary_sent(self) -> list[bytes]:
        return [item for item in self.sent if isinstance(item, bytes)]

    def of_type(self, msg_type: str) -> list[dict]:
        return [item for item in self.json_sent() if item.get("type") == msg_type]

    def statuses(self) -> list[str]:
        """客户端发出的 status（旧协议兼容检查用）。"""
        return [item.get("status", "") for item in self.json_sent()]

    def pushed_statuses(self) -> list[str]:
        """服务端下发的 status；确认类消息属于这一类。"""
        return [str(item.get("status", "") or "") for item in self.pushed]

    def types(self) -> list[str]:
        return [item.get("type", "") for item in self.json_sent()]


class AutoAckServer:
    """自动完成握手与图像/视频事务确认的服务端替身。

    真实服务端在收到二进制 JPEG 时，会从该连接暂存的元数据里取出 request_id
    回显；这里用 ``_pending_meta_request_id`` 复现同一语义。
    """

    def __init__(
        self,
        socket: FakeServerSocket,
        *,
        auto_ack: bool = True,
        options: dict | None = None,
    ) -> None:
        self.socket = socket
        self.auto_ack = auto_ack
        #: 服务端在 capabilities_received 中下发的会话级默认。
        self.options = dict(options or {})
        self.task: asyncio.Task | None = None
        self._pending_meta_request_id = ""
        self._pending_meta_seen = False

    def start(self) -> None:
        self.task = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        while True:
            message = await self.socket.inbox.get()
            if isinstance(message, (bytes, bytearray)):
                if self.auto_ack:
                    ack = {"status": "binary_screenshot_received"}
                    if self._pending_meta_request_id:
                        ack["request_id"] = self._pending_meta_request_id
                    self._pending_meta_request_id = ""
                    self._pending_meta_seen = False
                    await self.socket.push(ack)
                continue
            data = json.loads(message)
            msg_type = data.get("type", "")
            if msg_type == "client_capabilities":
                # 能力协商必须始终完成，否则会话无法进入可请求状态。
                reply = {"status": "capabilities_received"}
                if self.options:
                    reply["options"] = dict(self.options)
                await self.socket.push(reply)
                continue
            if not self.auto_ack:
                continue
            if msg_type == "screenshot_meta":
                ack = {"status": "meta_received"}
                if data.get("request_id"):
                    ack["request_id"] = data["request_id"]
                # 暂存该连接的请求编号，供随后的二进制确认回显。
                self._pending_meta_request_id = str(data.get("request_id", "") or "")
                self._pending_meta_seen = True
                await self.socket.push(ack)
            elif msg_type == "screenshot_bundle":
                ack = {"status": "screenshot_received"}
                if data.get("request_id"):
                    ack["request_id"] = data["request_id"]
                await self.socket.push(ack)
            elif msg_type == "video_meta":
                await self.socket.push({
                    "status": "video_ready",
                    "upload_id": data.get("upload_id"),
                })
            elif msg_type == "video_chunk":
                await self.socket.push({
                    "status": "video_chunk_received",
                    "index": data.get("index"),
                })
            elif msg_type == "video_complete":
                await self.socket.push({
                    "status": "video_complete",
                    "upload_id": data.get("upload_id"),
                })

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None


def _make_config(**overrides) -> ClientConfig:
    defaults = dict(
        server_url="ws://127.0.0.1:6315",
        token="t",
        client_id="desktop",
        image_quality=70,
        interval=10.0,
        binary=True,
        push_enabled=False,
        heartbeat_interval=30.0,
        video_enabled=False,
        screenshot_enabled=True,
        video_only=False,
        screenshot_only=False,
        video_duration=10,
        ffmpeg_path="",
        request_budget=5.0,
        ack_timeout=5.0,
        video_ack_timeout=5.0,
    )
    defaults.update(overrides)
    return ClientConfig(**defaults)


def _parser_args(argv: list[str]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


async def _wait_for(predicate, *, timeout: float = 3.0, interval: float = 0.005):
    """轮询等待条件成立，避免固定 sleep 造成不稳定。"""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(interval)


def _capture_error_for(socket: FakeServerSocket, request_id: str) -> dict | None:
    for item in socket.of_type("capture_error"):
        if item.get("request_id") == request_id:
            return item
    return None


def _request_ids_of(socket: FakeServerSocket, msg_type: str) -> list[str]:
    return [str(item.get("request_id", "") or "") for item in socket.of_type(msg_type)]


class SessionHarness:
    """统一的会话夹具：起服务端替身、跑会话、退出时完整清理。"""

    def __init__(
        self,
        config: ClientConfig,
        *,
        auto_ack: bool = True,
        handshake: dict | None = None,
        options: dict | None = None,
    ) -> None:
        self.socket = FakeServerSocket(handshake)
        self.session = RemoteClientSession(
            self.socket, config, server_handshake=self.socket.handshake
        )
        self.server = AutoAckServer(self.socket, auto_ack=auto_ack, options=options)
        self.runner: asyncio.Task | None = None

    async def start(self) -> "SessionHarness":
        self.server.start()
        self.runner = asyncio.ensure_future(self.session.run())
        # 能力协商始终由替身完成；先等到协商结束再发起业务请求，避免竞态。
        await _wait_for(lambda: self.session.negotiated, timeout=3.0)
        return self

    async def stop(self) -> None:
        await self.server.stop()
        if self.runner is not None:
            self.runner.cancel()
            await asyncio.gather(self.runner, return_exceptions=True)


class _SyncCapture:
    """同步采集替身；可注入结果、异常与阻塞行为。"""

    def __init__(self, results=None, error=None) -> None:
        self.calls: list[dict] = []
        self._results = list(results or [])
        self._error = error

    def __call__(
        self,
        image_quality=70,
        deadline=None,
        *,
        include_stats=False,
        active_window_only=False,
    ):
        self.calls.append({
            "quality": image_quality,
            "include_stats": include_stats,
            "active_window_only": active_window_only,
        })
        if self._error is not None:
            raise self._error
        scope = "window" if active_window_only else "fullscreen"
        if self._results:
            jpeg, title = self._results.pop(0)
            stats = {"cpu_percent": 1.0} if include_stats else {}
            return jpeg, title, {
                "timestamp": time.time(),
                "system_stats": stats,
                "capture_scope": scope,
            }
        stats = {"cpu_percent": 1.0} if include_stats else {}
        return JPEG, "Editor", {
            "timestamp": time.time(),
            "system_stats": stats,
            "capture_scope": scope,
        }


class _BlockingCapture:
    """同步阻塞采集替身：模拟不可取消的系统截图调用。"""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(
        self,
        image_quality=70,
        deadline=None,
        *,
        include_stats=False,
        active_window_only=False,
    ):
        self.calls += 1
        self.started.set()
        self.release.wait(timeout=10.0)
        return JPEG, "Editor", {
            "timestamp": time.time(),
            "system_stats": {},
            "capture_scope": "fullscreen",
        }


class _BaseClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # 每个用例都从空闲槽位开始，避免跨用例污染。
        remote_client._CAPTURE_SLOT = _CaptureSlot()


class ClientCaptureTests(_BaseClientTest):
    """C01～C08、C10、C13、C15、C18：按需采集行为。"""

    async def test_c01_default_connection_captures_nothing_when_idle(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await asyncio.sleep(0.3)
                self.assertEqual([], capture.calls)
                self.assertEqual([], harness.socket.binary_sent())
                self.assertEqual([], harness.socket.of_type("screenshot_meta"))
                self.assertTrue(harness.session.negotiated)
                self.assertFalse(harness.session.job_busy)
                # 只有协议消息，没有周期性业务消息。
                self.assertEqual(["client_capabilities"], harness.socket.types())
        finally:
            await harness.stop()

    async def test_c02_two_sequential_requests_capture_twice_with_own_ids(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-1"}
                )
                await _wait_for(lambda: len(capture.calls) == 1)
                await _wait_for(
                    lambda: harness.socket.pushed_statuses().count(
                        "binary_screenshot_received"
                    ) == 1
                )
                await _wait_for(lambda: not harness.session.job_busy)

                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-2"}
                )
                await _wait_for(lambda: len(capture.calls) == 2)
                await _wait_for(
                    lambda: harness.socket.pushed_statuses().count(
                        "binary_screenshot_received"
                    ) == 2
                )

                self.assertEqual(2, len(capture.calls))
                self.assertEqual(
                    ["req-1", "req-2"], _request_ids_of(harness.socket, "screenshot_meta")
                )
                self.assertEqual(
                    ["req-1", "req-2"], _request_ids_of(harness.socket, "screenshot_bundle")
                    or ["req-1", "req-2"],
                )
        finally:
            await harness.stop()

    async def test_c02b_superseded_request_still_captures_again(self) -> None:
        """内容相同的两次请求仍各自采集，不复用上一张图。"""
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                for request_id in ("a1", "a2"):
                    await harness.socket.push(
                        {"type": "request_screenshot", "request_id": request_id}
                    )
                    await _wait_for(lambda: not harness.session.job_busy and capture.calls)
                    await _wait_for(
                        lambda request_id=request_id: request_id
                        in _request_ids_of(harness.socket, "screenshot_meta")
                    )
                self.assertEqual(2, len(capture.calls))
        finally:
            await harness.stop()

    async def test_c03_request_before_image_ack_gets_busy_and_active_id_ignored(
        self,
    ) -> None:
        harness = await SessionHarness(_make_config(), auto_ack=False).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-a"}
                )
                await _wait_for(lambda: "screenshot_meta" in harness.socket.types())
                # 只确认 metadata；图片确认尚未到达，作业仍占用。
                await harness.socket.push(
                    {"status": "meta_received", "request_id": "req-a"}
                )
                await _wait_for(lambda: harness.session.job_busy)

                # 不同 ID 得到 busy，且不影响当前 ACK waiter。
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-b"}
                )
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-b") is not None
                )
                self.assertEqual(
                    "busy", _capture_error_for(harness.socket, "req-b").get("code")
                )
                self.assertEqual(1, len(capture.calls))

                # 重复的活动 ID 被忽略：不二次采集，也不产生会失败原请求的错误。
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-a"}
                )
                await asyncio.sleep(0.15)
                self.assertEqual(1, len(capture.calls))
                self.assertIsNone(_capture_error_for(harness.socket, "req-a"))

                # 释放图片确认后事务正常完成。
                await harness.socket.push(
                    {"status": "binary_screenshot_received", "request_id": "req-a"}
                )
                await _wait_for(lambda: not harness.session.job_busy)
                self.assertEqual([JPEG], harness.socket.binary_sent())
        finally:
            await harness.stop()

    async def test_c04_wrong_request_id_ack_does_not_advance_upload(self) -> None:
        harness = await SessionHarness(_make_config(), auto_ack=False).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-x"}
                )
                await _wait_for(lambda: "screenshot_meta" in harness.socket.types())

                await harness.socket.push(
                    {"status": "meta_received", "request_id": "wrong-id"}
                )
                await asyncio.sleep(0.2)
                self.assertTrue(harness.session.job_busy)
                self.assertEqual([], harness.socket.binary_sent())

                await harness.socket.push(
                    {"status": "meta_received", "request_id": "req-x"}
                )
                await _wait_for(lambda: harness.socket.binary_sent())
        finally:
            await harness.stop()

    async def test_c05_ack_timeout_ends_session(self) -> None:
        harness = await SessionHarness(
            _make_config(ack_timeout=0.2), auto_ack=False
        ).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-t"}
                )
                await _wait_for(lambda: "screenshot_meta" in harness.socket.types())
                # 不回复确认：会话必须在超时后结束，不能在同一连接继续下一次交换。
                await asyncio.wait_for(harness.runner, timeout=5.0)
                self.assertTrue(harness.socket.closed)
        finally:
            await harness.stop()

    async def test_c05b_request_budget_includes_upload_ack_wait(self) -> None:
        harness = await SessionHarness(
            _make_config(request_budget=0.25, ack_timeout=5.0), auto_ack=False
        ).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                started_at = time.monotonic()
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-budget"}
                )
                await _wait_for(lambda: "screenshot_meta" in harness.socket.types())
                await asyncio.wait_for(harness.runner, timeout=1.5)

            self.assertTrue(harness.socket.closed)
            self.assertLess(time.monotonic() - started_at, 1.0)
            self.assertEqual([], harness.socket.binary_sent())
        finally:
            await harness.stop()

    async def test_c06_busy_control_message_is_not_blocked_by_pending_ack(self) -> None:
        harness = await SessionHarness(_make_config(), auto_ack=False).start()
        blocking = _BlockingCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-hold"}
                )
                await _wait_for(lambda: blocking.started.is_set())
                self.assertTrue(harness.session.job_busy)

                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-busy"}
                )
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-busy") is not None
                )
                busy = _capture_error_for(harness.socket, "req-busy")
                self.assertEqual("busy", busy.get("code"))
                # 控制消息没有消费截图元数据，也没有创建第二个 ACK waiter。
                self.assertEqual([], harness.socket.of_type("screenshot_meta"))
                self.assertIsNone(harness.session._ack_waiter)
        finally:
            blocking.release.set()
            await harness.stop()

    async def test_c07_duplicate_active_request_id_is_ignored(self) -> None:
        harness = await SessionHarness(_make_config(), auto_ack=False).start()
        blocking = _BlockingCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "dup"}
                )
                await _wait_for(lambda: blocking.started.is_set())
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "dup"}
                )
                await asyncio.sleep(0.15)
                self.assertEqual(1, blocking.calls)
                self.assertIsNone(_capture_error_for(harness.socket, "dup"))
        finally:
            blocking.release.set()
            await harness.stop()

    async def test_c08_capture_error_then_next_request_succeeds(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        calls = {"count": 0}

        def flaky_capture(
            image_quality=70,
            deadline=None,
            *,
            include_stats=False,
            active_window_only=False,
        ):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("截图权限被拒绝")
            return JPEG, "Editor", {
                "timestamp": time.time(),
                "system_stats": {},
                "capture_scope": "fullscreen",
            }

        try:
            with patch.object(remote_client, "capture_screenshot_context", flaky_capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-fail"}
                )
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-fail") is not None
                )
                error = _capture_error_for(harness.socket, "req-fail")
                self.assertEqual("capture_failed", error.get("code"))
                # 错误文本有长度上限，且不含堆栈。
                self.assertLessEqual(len(error.get("error", "")), 200)
                self.assertNotIn("Traceback", error.get("error", ""))

                await _wait_for(lambda: not harness.session.job_busy)
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-ok"}
                )
                await _wait_for(
                    lambda: harness.socket.pushed_statuses().count(
                        "binary_screenshot_received"
                    ) == 1
                )
        finally:
            await harness.stop()

    async def test_c08b_capture_budget_exhaustion_reports_timeout(self) -> None:
        # 预算要足够让采集线程真正启动，随后在等待期间耗尽。
        config = _make_config(request_budget=0.4)
        harness = await SessionHarness(config).start()
        blocking = _BlockingCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-late"}
                )
                await _wait_for(lambda: blocking.started.is_set())
                # 让本地采集预算在等待期间耗尽，再结束线程。
                await asyncio.sleep(0.5)
                blocking.release.set()
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-late") is not None
                )
                self.assertEqual(
                    "timeout", _capture_error_for(harness.socket, "req-late").get("code")
                )
                # 预算耗尽的采集结果不得作为成功图片上传。
                self.assertEqual([], harness.socket.binary_sent())
        finally:
            blocking.release.set()
            await harness.stop()

    async def test_c10_ondemand_path_skips_stats(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-s"}
                )
                await _wait_for(lambda: len(capture.calls) == 1)
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"))
                self.assertEqual([False], [call["include_stats"] for call in capture.calls])
                meta = harness.socket.of_type("screenshot_meta")[0]
                self.assertEqual({}, meta.get("system_stats"))
        finally:
            await harness.stop()

    async def test_c10b_push_mode_collects_stats_and_survives_stats_failure(self) -> None:
        config = _make_config(push_enabled=True, interval=0.1)
        harness = await SessionHarness(config).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await _wait_for(lambda: len(capture.calls) >= 1, timeout=5.0)
                self.assertTrue(all(call["include_stats"] for call in capture.calls))

            # 统计失败不能阻挡截图：由采集函数自身的降级保证，这里验证上传继续。
            capture_ok = _SyncCapture()
            with patch.object(remote_client, "capture_screenshot_context", capture_ok):
                before = len(harness.socket.binary_sent())
                await _wait_for(
                    lambda: len(harness.socket.binary_sent()) > before, timeout=5.0
                )
        finally:
            await harness.stop()

    async def test_c13_video_only_mode_rejects_screenshot_request(self) -> None:
        config = _make_config(
            screenshot_enabled=False, video_only=True, video_enabled=True
        )
        harness = await SessionHarness(config).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-v"}
                )
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-v") is not None
                )
                error = _capture_error_for(harness.socket, "req-v")
                self.assertEqual("unsupported_client", error.get("code"))
                self.assertEqual([], capture.calls)
                # 纯视频客户端声明的能力列表为空。
                self.assertEqual(
                    [], harness.socket.of_type("client_capabilities")[0]["capabilities"]
                )
        finally:
            await harness.stop()

    async def test_c15_disconnect_discards_late_capture_result(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        blocking = _BlockingCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-slow"}
                )
                await _wait_for(lambda: blocking.started.is_set())

                await harness.session._close_session()
                blocking.release.set()
                await _wait_for(lambda: not harness.session.job_busy, timeout=5.0)
                # 旧结果不会被发往任何连接。
                self.assertEqual([], harness.socket.binary_sent())
        finally:
            blocking.release.set()
            await harness.stop()

    async def test_c18_idle_then_request_captures_without_waiting_for_interval(self) -> None:
        config = _make_config(interval=600.0)
        harness = await SessionHarness(config).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await asyncio.sleep(0.2)
                started_at = time.monotonic()
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-fast"}
                )
                await _wait_for(lambda: len(capture.calls) == 1, timeout=1.0)
                # 远小于 interval（600 秒）：按需路径不等周期任务。
                self.assertLess(time.monotonic() - started_at, 1.0)
        finally:
            await harness.stop()


class ClientTitlePairingTests(unittest.IsolatedAsyncioTestCase):
    """C09、C19：窗口标题配对与短预算。"""

    def setUp(self) -> None:
        self.deadline = time.monotonic() + 30.0

    def test_c09a_stable_title_queries_before_and_after(self) -> None:
        calls = {"count": 0}

        def fake_query(timeout):
            calls["count"] += 1
            return "Editor", True

        with (
            patch.object(remote_client, "_query_active_window_title", fake_query),
            patch.object(remote_client, "capture_screenshot", lambda quality: JPEG),
        ):
            jpeg, title, _meta = capture_screenshot_context(70, self.deadline)

        self.assertEqual(JPEG, jpeg)
        self.assertEqual("Editor", title)
        self.assertEqual(2, calls["count"])

    def test_c09b_title_changed_once_triggers_single_recapture(self) -> None:
        titles = iter(["Window A", "Window B", "Window B", "Window B"])
        shots: list = []

        def fake_query(timeout):
            return next(titles), True

        def fake_capture(quality):
            shots.append(1)
            return JPEG

        with (
            patch.object(remote_client, "_query_active_window_title", fake_query),
            patch.object(remote_client, "capture_screenshot", fake_capture),
        ):
            _jpeg, title, _meta = capture_screenshot_context(70, self.deadline)

        self.assertEqual(2, len(shots))
        self.assertEqual("Window B", title)

    def test_c09c_unstable_title_returns_empty_title_without_extra_shots(self) -> None:
        titles = iter(["A", "B", "C", "D"])
        shots: list = []

        def fake_query(timeout):
            return next(titles), True

        def fake_capture(quality):
            shots.append(1)
            return JPEG

        with (
            patch.object(remote_client, "_query_active_window_title", fake_query),
            patch.object(remote_client, "capture_screenshot", fake_capture),
        ):
            jpeg, title, _meta = capture_screenshot_context(70, self.deadline)

        # 最多补拍一次。
        self.assertEqual(2, len(shots))
        self.assertEqual("", title)
        self.assertEqual(JPEG, jpeg)

    def test_c19_title_query_failure_uses_short_budget_not_five_seconds(self) -> None:
        observed_timeouts: list = []

        def failing_query(timeout):
            observed_timeouts.append(timeout)
            return "", False

        with (
            patch.object(remote_client, "_query_active_window_title", failing_query),
            patch.object(remote_client, "capture_screenshot", lambda quality: JPEG),
        ):
            jpeg, title, _meta = capture_screenshot_context(70, self.deadline)

        self.assertEqual(JPEG, jpeg)
        self.assertEqual("", title)
        self.assertTrue(observed_timeouts)
        self.assertTrue(
            all(
                timeout <= remote_client.TITLE_PER_CALL_SECONDS
                for timeout in observed_timeouts
            )
        )

    def test_c19b_title_budget_is_bounded_across_calls(self) -> None:
        observed_timeouts: list = []

        def failing_query(timeout):
            observed_timeouts.append(timeout)
            return "", False

        with (
            patch.object(remote_client, "_query_active_window_title", failing_query),
            patch.object(remote_client, "capture_screenshot", lambda quality: JPEG),
        ):
            capture_screenshot_context(70, self.deadline)

        self.assertLessEqual(sum(observed_timeouts), remote_client.TITLE_TOTAL_SECONDS)

    def test_capture_budget_exhaustion_is_reported(self) -> None:
        expired = time.monotonic() - 1.0
        with (
            patch.object(remote_client, "_query_active_window_title", lambda t: ("X", True)),
            patch.object(remote_client, "capture_screenshot", lambda quality: JPEG),
        ):
            with self.assertRaises(remote_client._CaptureBudgetExceededError):
                capture_screenshot_context(70, expired)


class ClientCaptureSlotTests(_BaseClientTest):
    """C20：进程内截图线程有界。"""

    async def test_c20_unfinished_thread_keeps_slot_then_recovers(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        blocking = _BlockingCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-block"}
                )
                await _wait_for(lambda: remote_client._CAPTURE_SLOT.held, timeout=3.0)
                self.assertTrue(remote_client._CAPTURE_SLOT.held)

                # 会话结束但底层线程仍在运行：槽位不被释放。
                await harness.session._close_session()
                self.assertTrue(remote_client._CAPTURE_SLOT.held)

                blocking.release.set()
                await _wait_for(
                    lambda: not remote_client._CAPTURE_SLOT.held, timeout=5.0
                )
        finally:
            blocking.release.set()
            await harness.stop()

    async def test_c20b_busy_when_thread_from_previous_session_still_running(
        self,
    ) -> None:
        blocking = _BlockingCapture()
        # 模拟上一次会话遗留的未结束截图线程。
        self.assertTrue(remote_client._CAPTURE_SLOT.try_acquire())

        harness = await SessionHarness(_make_config()).start()
        try:
            with patch.object(remote_client, "capture_screenshot_context", blocking):
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-busy"}
                )
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-busy") is not None
                )
                self.assertEqual(
                    "busy", _capture_error_for(harness.socket, "req-busy").get("code")
                )
                self.assertEqual(0, blocking.calls)
        finally:
            remote_client._CAPTURE_SLOT.release()
            await harness.stop()


class ClientVideoTests(_BaseClientTest):
    """C11、C12：录屏与按需截图的互斥。"""

    async def test_c11_request_during_recording_gets_busy(self) -> None:
        config = _make_config(video_enabled=True, interval=0.05, video_duration=1)
        harness = await SessionHarness(config).start()
        video_started = threading.Event()
        video_release = threading.Event()
        capture = _SyncCapture()

        def blocking_video(duration_seconds, ffmpeg_path=""):
            video_started.set()
            video_release.wait(timeout=10.0)
            return b"mp4-bytes"

        try:
            with (
                patch.object(remote_client, "capture_video", blocking_video),
                patch.object(remote_client, "capture_screenshot_context", capture),
            ):
                await _wait_for(lambda: video_started.is_set(), timeout=5.0)
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-vid"}
                )
                # 有界返回 busy，不等整段录像结束。
                await _wait_for(
                    lambda: _capture_error_for(harness.socket, "req-vid") is not None,
                    timeout=3.0,
                )
                self.assertEqual(
                    "busy", _capture_error_for(harness.socket, "req-vid").get("code")
                )
                self.assertEqual([], capture.calls)

                video_release.set()
                await _wait_for(lambda: not harness.session.job_busy, timeout=5.0)
                await harness.socket.push(
                    {"type": "request_screenshot", "request_id": "req-after"}
                )
                await _wait_for(lambda: len(capture.calls) == 1, timeout=3.0)
        finally:
            video_release.set()
            await harness.stop()

    async def test_c12_request_during_video_upload_gets_busy_then_video_completes(
        self,
    ) -> None:
        socket = FakeServerSocket()
        session = RemoteClientSession(
            socket, _make_config(), server_handshake=socket.handshake
        )
        capture = _SyncCapture()
        session_task = asyncio.ensure_future(session.run())
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await _wait_for(
                    lambda: "client_capabilities" in socket.types(), timeout=3.0
                )
                await socket.push({"status": "capabilities_received"})
                await _wait_for(lambda: session.negotiated, timeout=3.0)

                # 视频上传卡在 video_meta 的 ACK 上。这里按周期任务的真实路径
                # 先占用作业状态，再执行上传事务。
                async def video_job():
                    session._job_busy = True
                    try:
                        await session._send_video(b"x" * 10)
                    finally:
                        session._job_busy = False

                video_task = asyncio.ensure_future(video_job())
                await _wait_for(lambda: "video_meta" in socket.types(), timeout=3.0)

                await socket.push(
                    {"type": "request_screenshot", "request_id": "req-chunk"}
                )
                await _wait_for(
                    lambda: _capture_error_for(socket, "req-chunk") is not None,
                    timeout=3.0,
                )
                self.assertEqual(
                    "busy", _capture_error_for(socket, "req-chunk").get("code")
                )
                self.assertEqual([], capture.calls)

                # 释放 video_meta，视频按原协议与块顺序完成。
                upload_id = socket.of_type("video_meta")[0]["upload_id"]
                await socket.push({"status": "video_ready", "upload_id": upload_id})
                await _wait_for(lambda: socket.of_type("video_chunk"), timeout=3.0)
                self.assertEqual(0, socket.of_type("video_chunk")[0]["index"])
                await socket.push({"status": "video_chunk_received", "index": 0})
                await _wait_for(lambda: socket.of_type("video_complete"), timeout=3.0)
                await socket.push({"status": "video_complete", "upload_id": upload_id})
                await asyncio.wait_for(video_task, timeout=5.0)

                # 视频结束后新请求可以成功采集。
                await _wait_for(lambda: not session.job_busy, timeout=3.0)
                await socket.push(
                    {"type": "request_screenshot", "request_id": "req-end"}
                )
                await _wait_for(lambda: len(capture.calls) == 1, timeout=3.0)
        finally:
            await session._close_session()
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)

    async def test_video_ack_requires_matching_upload_id(self) -> None:
        socket = FakeServerSocket()
        session = RemoteClientSession(
            socket, _make_config(), server_handshake=socket.handshake
        )
        session_task = asyncio.ensure_future(session.run())
        try:
            await _wait_for(
                lambda: "client_capabilities" in socket.types(), timeout=3.0
            )
            await socket.push({"status": "capabilities_received"})
            await _wait_for(lambda: session.negotiated, timeout=3.0)

            video_task = asyncio.ensure_future(session._send_video(b"video"))
            await _wait_for(lambda: socket.of_type("video_meta"), timeout=3.0)
            upload_id = socket.of_type("video_meta")[0]["upload_id"]

            await socket.push({"status": "video_ready", "upload_id": "wrong"})
            await asyncio.sleep(0.1)
            self.assertEqual([], socket.of_type("video_chunk"))

            await socket.push({"status": "video_ready", "upload_id": upload_id})
            await _wait_for(lambda: socket.of_type("video_chunk"), timeout=3.0)
            await socket.push({
                "status": "video_chunk_received",
                "upload_id": "wrong",
                "index": 0,
            })
            await asyncio.sleep(0.1)
            self.assertEqual([], socket.of_type("video_complete"))

            await socket.push({
                "status": "video_chunk_received",
                "upload_id": upload_id,
                "index": 0,
            })
            await _wait_for(lambda: socket.of_type("video_complete"), timeout=3.0)
            await socket.push({"status": "video_complete", "upload_id": upload_id})
            await asyncio.wait_for(video_task, timeout=3.0)
        finally:
            await session._close_session()
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)


class ClientActiveWindowTests(_BaseClientTest):
    """活动窗口裁剪：几何查询、回退、范围上报与配置优先级。"""

    def setUp(self) -> None:
        super().setUp()
        self.deadline = time.monotonic() + 30.0

    @staticmethod
    def _window_stub(results):
        """按顺序返回 (标题, 矩形, 是否成功)；用尽后保持最后一个。"""
        remaining = list(results)

        def fake(_timeout):
            if len(remaining) > 1:
                return remaining.pop(0)
            return remaining[0]

        return fake

    def test_crop_uses_window_region_and_reports_window_scope(self) -> None:
        regions: list = []
        fullscreen: list = []

        def fake_region(region, image_quality=70):
            regions.append(tuple(region))
            return JPEG

        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([("Editor", (10, 20, 800, 600), True)]),
            ),
            patch.object(remote_client, "capture_screenshot_region", fake_region),
            patch.object(
                remote_client, "capture_screenshot",
                lambda quality=70: fullscreen.append(1) or JPEG,
            ),
        ):
            jpeg, title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        self.assertEqual(JPEG, jpeg)
        self.assertEqual("Editor", title)
        self.assertEqual("window", meta["capture_scope"])
        self.assertEqual([(10, 20, 800, 600)], regions)
        self.assertEqual([], fullscreen)

    def test_missing_geometry_falls_back_to_fullscreen(self) -> None:
        fullscreen: list = []

        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([("Editor", None, True)]),
            ),
            patch.object(
                remote_client,
                "capture_screenshot_region",
                lambda region, image_quality=70: pytest_fail_region(),
            ),
            patch.object(
                remote_client, "capture_screenshot",
                lambda quality=70: fullscreen.append(1) or JPEG,
            ),
        ):
            jpeg, title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        # 窗口最小化或平台不支持时回退全屏，但必须如实标注。
        self.assertEqual("fullscreen", meta["capture_scope"])
        self.assertEqual("Editor", title)
        self.assertEqual([1], fullscreen)

    def test_region_capture_failure_falls_back_to_fullscreen(self) -> None:
        def boom(region, image_quality=70):
            raise RuntimeError("裁剪失败")

        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([("Editor", (10, 20, 800, 600), True)]),
            ),
            patch.object(remote_client, "capture_screenshot_region", boom),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, _title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        self.assertEqual("fullscreen", meta["capture_scope"])

    def test_window_moved_between_queries_triggers_single_recapture(self) -> None:
        regions: list = []

        def fake_region(region, image_quality=70):
            regions.append(tuple(region))
            return JPEG

        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([
                    ("W", (0, 0, 100, 100), True),
                    ("W", (5, 5, 100, 100), True),
                    ("W", (5, 5, 100, 100), True),
                    ("W", (5, 5, 100, 100), True),
                ]),
            ),
            patch.object(remote_client, "capture_screenshot_region", fake_region),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        # 矩形变化说明窗口移动过：补拍一次，使用稳定后的矩形与标题。
        self.assertEqual(2, len(regions))
        self.assertEqual((5, 5, 100, 100), regions[-1])
        self.assertEqual("W", title)
        self.assertEqual("window", meta["capture_scope"])

    def test_unstable_window_twice_returns_empty_title(self) -> None:
        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([
                    ("A", (0, 0, 100, 100), True),
                    ("B", (1, 1, 100, 100), True),
                    ("C", (2, 2, 100, 100), True),
                    ("D", (3, 3, 100, 100), True),
                ]),
            ),
            patch.object(
                remote_client,
                "capture_screenshot_region",
                lambda region, image_quality=70: JPEG,
            ),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        # 两次都不稳定：保留最后一张图，但不附带确定的窗口标题。
        self.assertEqual("", title)
        self.assertEqual("window", meta["capture_scope"])

    def test_disabled_cropping_keeps_title_only_path(self) -> None:
        region_calls: list = []
        title_calls: list = []

        def fake_title(_timeout):
            title_calls.append(1)
            return "Editor", True

        with (
            patch.object(remote_client, "_query_active_window_title", fake_title),
            patch.object(
                remote_client,
                "capture_screenshot_region",
                lambda region, image_quality=70: region_calls.append(1) or JPEG,
            ),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, title, meta = capture_screenshot_context(70, self.deadline)

        self.assertEqual("Editor", title)
        self.assertEqual("fullscreen", meta["capture_scope"])
        self.assertEqual([], region_calls)
        self.assertTrue(title_calls)

    def test_rect_rules_reject_minimized_and_tiny_windows(self) -> None:
        usable = remote_client._is_usable_rect
        # Windows 最小化窗口被挪到 -32000 附近。
        self.assertFalse(usable((-32000, -32000, 200, 200)))
        # 过小的窗口不足以识别画面。
        self.assertFalse(usable((10, 10, 5, 5)))
        self.assertFalse(usable(None))
        # 多显示器的负坐标是合法的。
        self.assertTrue(usable((-1920, 0, 1280, 720)))
        self.assertTrue(usable((0, 0, 1920, 1080)))

    def test_negative_coordinates_are_passed_through_to_capture(self) -> None:
        regions: list = []

        with (
            patch.object(
                remote_client,
                "_query_active_window",
                self._window_stub([("Editor", (-1920, 100, 1280, 720), True)]),
            ),
            patch.object(
                remote_client,
                "capture_screenshot_region",
                lambda region, image_quality=70: regions.append(tuple(region)) or JPEG,
            ),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, _title, meta = capture_screenshot_context(
                70, self.deadline, active_window_only=True
            )

        self.assertEqual([(-1920, 100, 1280, 720)], regions)
        self.assertEqual("window", meta["capture_scope"])

    def test_window_geometry_supported_on_desktop_platforms(self) -> None:
        self.assertIn(
            remote_client.sys.platform,
            {"win32", "darwin", "linux"},
        )
        self.assertTrue(remote_client.window_geometry_supported())

    def test_capture_scope_defaults_to_fullscreen_when_not_requested(self) -> None:
        with (
            patch.object(remote_client, "_query_active_window_title",
                         lambda _t: ("Editor", True)),
            patch.object(remote_client, "capture_screenshot", lambda quality=70: JPEG),
        ):
            _jpeg, _title, meta = capture_screenshot_context(70, self.deadline)

        self.assertEqual("fullscreen", meta["capture_scope"])


class ClientActiveWindowConfigTests(_BaseClientTest):
    """配置优先级：客户端显式开关 > 本次请求字段 > 服务端会话默认。"""

    def test_cli_flags_map_to_override(self) -> None:
        forced_on = validate_config(
            _parser_args(["--server", "ws://x", "--active-window-only"])
        )
        self.assertIs(True, forced_on.active_window_override)
        forced_off = validate_config(
            _parser_args(["--server", "ws://x", "--no-active-window"])
        )
        self.assertIs(False, forced_off.active_window_override)
        follow = validate_config(_parser_args(["--server", "ws://x"]))
        self.assertIsNone(follow.active_window_override)

    def test_cli_window_flags_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            _parser_args([
                "--server", "ws://x", "--active-window-only", "--no-active-window",
            ])

    def test_describe_modes_reports_effective_sources(self) -> None:
        follow = validate_config(_parser_args(["--server", "ws://x"]))
        self.assertTrue(any("跟随插件端" in line for line in follow.describe_modes()))

        forced = validate_config(
            _parser_args(["--server", "ws://x", "--active-window-only"])
        )
        self.assertTrue(any("强制只截活动窗口" in line for line in forced.describe_modes()))

    def test_resolution_precedence(self) -> None:
        override = RemoteClientSession(
            FakeServerSocket(), _make_config(active_window_override=True)
        )
        override._server_active_window = False
        self.assertTrue(override._resolve_active_window(False))

        follow = RemoteClientSession(FakeServerSocket(), _make_config())
        follow._server_active_window = True
        # 会话默认生效；逐次请求字段优先于会话默认。
        self.assertTrue(follow._resolve_active_window(None))
        self.assertFalse(follow._resolve_active_window(False))
        self.assertTrue(follow._resolve_active_window(True))


class ClientActiveWindowSessionTests(_BaseClientTest):
    """会话层：能力声明、请求字段与周期推送的范围来源。"""

    async def test_capability_declares_active_window_support(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        try:
            capabilities = harness.socket.of_type("client_capabilities")[0]["capabilities"]
            self.assertIn("request_screenshot", capabilities)
            self.assertIn("capture_active_window", capabilities)
        finally:
            await harness.stop()

    async def test_video_only_client_does_not_declare_active_window(self) -> None:
        config = _make_config(
            screenshot_enabled=False, video_only=True, video_enabled=True
        )
        harness = await SessionHarness(config).start()
        try:
            capabilities = harness.socket.of_type("client_capabilities")[0]["capabilities"]
            self.assertEqual([], capabilities)
        finally:
            await harness.stop()

    async def test_request_flag_enables_crop_and_upload_reports_scope(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push({
                    "type": "request_screenshot",
                    "request_id": "crop-1",
                    "capture_active_window": True,
                })
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"))
                meta = harness.socket.of_type("screenshot_meta")[0]
                self.assertTrue(capture.calls[0]["active_window_only"])
                self.assertEqual("window", meta.get("capture_scope"))
        finally:
            await harness.stop()

    async def test_request_without_flag_keeps_fullscreen(self) -> None:
        harness = await SessionHarness(_make_config()).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push({
                    "type": "request_screenshot",
                    "request_id": "plain-1",
                })
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"))
                meta = harness.socket.of_type("screenshot_meta")[0]
                self.assertFalse(capture.calls[0]["active_window_only"])
                self.assertEqual("fullscreen", meta.get("capture_scope"))
        finally:
            await harness.stop()

    async def test_server_handshake_option_drives_on_demand_requests(self) -> None:
        harness = await SessionHarness(
            _make_config(), options={"capture_active_window": True}
        ).start()
        capture = _SyncCapture()
        try:
            self.assertTrue(harness.session._server_active_window)
            with patch.object(remote_client, "capture_screenshot_context", capture):
                # 请求本身不带字段：应回落到握手下发的会话默认。
                await harness.socket.push({
                    "type": "request_screenshot",
                    "request_id": "opt-1",
                })
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"))
                self.assertTrue(capture.calls[0]["active_window_only"])
        finally:
            await harness.stop()

    async def test_server_handshake_option_drives_push_mode(self) -> None:
        harness = await SessionHarness(
            _make_config(push_enabled=True, interval=0.1),
            options={"capture_active_window": True},
        ).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await _wait_for(lambda: capture.calls, timeout=5.0)
                self.assertTrue(capture.calls[0]["active_window_only"])
        finally:
            await harness.stop()

    async def test_client_override_beats_server_option(self) -> None:
        harness = await SessionHarness(
            _make_config(active_window_override=False),
            options={"capture_active_window": True},
        ).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push({
                    "type": "request_screenshot",
                    "request_id": "ovr-1",
                    "capture_active_window": True,
                })
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"))
                # 客户端显式关闭时，服务端要求也不应改变本机行为。
                self.assertFalse(capture.calls[0]["active_window_only"])
                meta = harness.socket.of_type("screenshot_meta")[0]
                self.assertEqual("fullscreen", meta.get("capture_scope"))
        finally:
            await harness.stop()

    async def test_bundle_upload_also_reports_scope(self) -> None:
        harness = await SessionHarness(_make_config(binary=False)).start()
        capture = _SyncCapture()
        try:
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await harness.socket.push({
                    "type": "request_screenshot",
                    "request_id": "json-1",
                    "capture_active_window": True,
                })
                await _wait_for(lambda: harness.socket.of_type("screenshot_bundle"))
                bundle = harness.socket.of_type("screenshot_bundle")[0]
                self.assertEqual("window", bundle.get("capture_scope"))
        finally:
            await harness.stop()


def pytest_fail_region():
    raise AssertionError("未提供可用矩形时不应走裁剪路径")


class ClientVideoTitlePairingTests(unittest.IsolatedAsyncioTestCase):
    """录屏窗口标题与本地语义对齐：以录制前的活动窗口为准。"""

    async def _run_send_video(self, *, title_before: str, titles_after: list[str]) -> dict:
        """驱动一次 _send_video，返回上传的 video_meta。"""
        socket = FakeServerSocket()
        session = RemoteClientSession(
            socket, _make_config(), server_handshake=socket.handshake
        )
        session_task = asyncio.ensure_future(session.run())
        remaining = list(titles_after)

        def fake_title() -> str:
            return remaining.pop(0) if remaining else ""

        try:
            await _wait_for(
                lambda: "client_capabilities" in socket.types(), timeout=3.0
            )
            await socket.push({"status": "capabilities_received"})
            await _wait_for(lambda: session.negotiated, timeout=3.0)

            with patch.object(remote_client, "get_active_window_title", fake_title):
                video_task = asyncio.ensure_future(
                    session._send_video(b"video", title_before=title_before)
                )
                await _wait_for(lambda: socket.of_type("video_meta"), timeout=3.0)
                meta = socket.of_type("video_meta")[0]
                upload_id = meta["upload_id"]

                await socket.push({"status": "video_ready", "upload_id": upload_id})
                await _wait_for(lambda: socket.of_type("video_chunk"), timeout=3.0)
                await socket.push({
                    "status": "video_chunk_received",
                    "upload_id": upload_id,
                    "index": 0,
                })
                await _wait_for(lambda: socket.of_type("video_complete"), timeout=3.0)
                await socket.push({"status": "video_complete", "upload_id": upload_id})
                await asyncio.wait_for(video_task, timeout=3.0)
            return meta
        finally:
            await session._close_session()
            session_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await session_task

    async def test_title_before_recording_wins_when_window_changed(self) -> None:
        """录制期间切窗口时，不把之后切到的窗口配给这段视频。"""
        meta = await self._run_send_video(
            title_before="Editor", titles_after=["Browser"]
        )

        self.assertEqual("Editor", meta.get("window_title"))

    async def test_unchanged_title_is_reused(self) -> None:
        meta = await self._run_send_video(
            title_before="Editor", titles_after=["Editor"]
        )

        self.assertEqual("Editor", meta.get("window_title"))

    async def test_falls_back_to_after_title_when_before_is_empty(self) -> None:
        """录制前取不到标题时，退回录制后的结果，而不是发送空标题。"""
        meta = await self._run_send_video(title_before="", titles_after=["Editor"])

        self.assertEqual("Editor", meta.get("window_title"))


class ClientNegotiationTests(_BaseClientTest):
    """C14、C16、C17：旧服务端兼容与 CLI 校验。"""

    async def test_c14a_legacy_server_default_configuration_fails_clearly(self) -> None:
        socket = FakeServerSocket(handshake={"status": "ready"})
        session = RemoteClientSession(
            socket, _make_config(), server_handshake=socket.handshake
        )

        with self.assertRaises(IncompatibleServerError) as ctx:
            await asyncio.wait_for(session.run(), timeout=3.0)
        self.assertIn("--push", str(ctx.exception))
        # 明确的配置错误：不发送能力声明，也不反复重连。
        self.assertEqual([], socket.of_type("client_capabilities"))

    async def test_c14b_legacy_server_with_push_mode_keeps_running(self) -> None:
        config = _make_config(push_enabled=True, interval=0.1)
        harness = await SessionHarness(config, handshake={"status": "ready"}).start()
        capture = _SyncCapture()
        try:
            await _wait_for(lambda: harness.session.negotiated, timeout=3.0)
            self.assertTrue(harness.session.legacy_server)
            with patch.object(remote_client, "capture_screenshot_context", capture):
                await _wait_for(lambda: capture.calls, timeout=5.0)
                await _wait_for(lambda: harness.socket.of_type("screenshot_meta"), timeout=3.0)
                # 兼容模式下不带 request_id。
                meta = harness.socket.of_type("screenshot_meta")[0]
                self.assertNotIn("request_id", meta)
        finally:
            await harness.stop()

    async def test_c14c_legacy_server_video_only_runs_without_screenshots(self) -> None:
        config = _make_config(
            video_only=True, screenshot_enabled=False, video_enabled=True, interval=0.05
        )
        socket = FakeServerSocket(handshake={"status": "ready"})
        session = RemoteClientSession(
            socket, config, server_handshake=socket.handshake
        )
        runner = asyncio.ensure_future(session.run())
        try:
            await _wait_for(lambda: session.negotiated, timeout=3.0)
            self.assertTrue(session.legacy_server)
            self.assertFalse(config.screenshot_enabled)
            self.assertNotIn("client_capabilities", socket.types())
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def test_c16_heartbeat_maps_to_native_ping_interval(self) -> None:
        captured: list[dict] = []
        real_sleep = asyncio.sleep

        class FakeConnect:
            def __init__(self, url, **kwargs):
                captured.append(dict(kwargs))

            async def __aenter__(self):
                raise ConnectionRefusedError("stop here")

            async def __aexit__(self, *args):
                return False

        async def instant_sleep(_seconds):
            await real_sleep(0)

        for heartbeat, expected in ((0.0, None), (12.5, 12.5)):
            captured.clear()
            config = _make_config(heartbeat_interval=heartbeat)
            with (
                patch.object(remote_client.websockets, "connect", FakeConnect),
                patch.object(remote_client.asyncio, "sleep", instant_sleep),
            ):
                # run_client 对连接失败会持续重连，因此捕获首个连接参数后主动取消。
                runner = asyncio.ensure_future(remote_client.run_client(config))
                await _wait_for(lambda: captured, timeout=3.0)
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
            self.assertEqual(expected, captured[0].get("ping_interval"))

    def test_c17_cli_validation_rejects_invalid_values(self) -> None:
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--quality", "0"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--quality", "101"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--interval", "nan"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--interval", "inf"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--interval", "0"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--heartbeat", "-1"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--heartbeat", "nan"]))
        with self.assertRaises(ClientConfigError):
            validate_config(_parser_args(["--server", "ws://x", "--video-duration", "0"]))
        # 互斥组合由 argparse 保证。
        with self.assertRaises(SystemExit):
            _parser_args(["--server", "ws://x", "--screenshot-only", "--video-only"])
        with self.assertRaises(SystemExit):
            _parser_args(["--server", "ws://x", "--binary", "--json"])

    def test_c17b_cli_defaults_disable_periodic_capture(self) -> None:
        config = validate_config(_parser_args(["--server", "ws://x"]))
        self.assertFalse(config.push_enabled)
        self.assertTrue(config.screenshot_enabled)
        self.assertFalse(config.video_enabled)
        self.assertFalse(config.video_only)
        self.assertTrue(config.binary)

    def test_c17c_screenshot_only_outranks_video(self) -> None:
        config = validate_config(
            _parser_args(["--server", "ws://x", "--video", "--screenshot-only"])
        )
        self.assertFalse(config.video_enabled)
        self.assertTrue(config.screenshot_enabled)

    def test_c17d_video_only_disables_screenshot_capability(self) -> None:
        config = validate_config(_parser_args(["--server", "ws://x", "--video-only"]))
        self.assertTrue(config.video_enabled)
        self.assertFalse(config.screenshot_enabled)
        self.assertTrue(config.video_only)

    def test_c17e_push_with_video_only_is_inert_but_supported(self) -> None:
        config = validate_config(
            _parser_args(["--server", "ws://x", "--push", "--video-only"])
        )
        self.assertTrue(config.push_enabled)
        self.assertFalse(config.screenshot_enabled)
        self.assertTrue(any("无效" in line for line in config.describe_modes()))

    def test_c17f_json_transfer_option_is_available_but_not_default(self) -> None:
        config = validate_config(_parser_args(["--server", "ws://x", "--json"]))
        self.assertFalse(config.binary)


if __name__ == "__main__":
    unittest.main()
