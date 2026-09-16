# -*- coding: utf-8 -*-
"""WebSocket receiver for remote screen companion mode.

协议概览（v2 新增按需截图）：

- 服务端在 ``authenticated`` / ``ready`` 消息中声明 ``protocol_version`` 与
  ``capabilities``；客户端随后用 ``client_capabilities`` 声明自身能力。
- 只有认证完成且声明了 ``request_screenshot`` 能力的连接才会收到截图命令。
- 一次截图事务的顺序是：``request_screenshot`` → ``screenshot_meta``（或
  ``screenshot_bundle``）→ ``meta_received`` → 二进制 JPEG →
  ``binary_screenshot_received``。
- 图片与窗口元数据按连接暂存，只有整帧完整到达后才一次性提交到缓存，
  因此读取缓存永远不会看到「新标题 + 旧图片」的组合。
- 旧客户端仍可按原有周期推送协议工作：无 ``request_id`` 的推送只更新缓存，
  不会完成任何按需等待者。

锁的使用约定：``self._lock`` 只保护短暂的状态读取与提交，绝不在持锁期间
等待网络发送、Future 或连接关闭，否则一次慢速客户端会阻塞整条接收链路。
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    websockets = None
    ws_serve = None


# --------------------------------------------------------------------------
# 协议常量
# --------------------------------------------------------------------------

#: 当前服务端协议版本；v2 引入按需截图能力协商。
PROTOCOL_VERSION = 2
#: 客户端能力名称：支持在收到请求后重新采集截图。
CAPABILITY_REQUEST_SCREENSHOT = "request_screenshot"
#: 客户端能力名称：支持把截图裁剪到活动窗口。
CAPABILITY_CAPTURE_ACTIVE_WINDOW = "capture_active_window"
#: 单次按需截图的默认等待预算（秒）。必须小于图像外层 20 秒采集超时。
DEFAULT_REQUEST_TIMEOUT = 10.0
#: 控制消息（无需 ACK 的回复）发送预算（秒）。
CONTROL_SEND_TIMEOUT = 1.0
#: 元数据确认后，整帧事务的保留上限（秒）。超时则关闭该连接。
META_TRANSACTION_TTL = 10.0
#: 请求编号允许的最大长度。
MAX_REQUEST_ID_LENGTH = 64
#: 客户端错误文本允许的最大长度。
MAX_ERROR_TEXT_LENGTH = 200
#: 请求编号允许的字符集合。
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: 客户端返回的失败 code → 服务端公开错误码。
_CLIENT_ERROR_CODE_MAP = {
    "busy": "busy",
    "timeout": "timeout",
    "expired_request": "timeout",
    "unsupported_client": "unsupported_client",
    "capture_failed": "capture_failed",
}

# 面向用户的公开提示，统一在此定义，避免各处文案漂移。
PUBLIC_NO_CLIENT_MESSAGE = "远程客户端未连接，请启动客户端后重试。"
PUBLIC_UNSUPPORTED_CLIENT_MESSAGE = (
    "当前客户端不支持即时重拍，请升级 remote_client.py 后重试。"
)
PUBLIC_AMBIGUOUS_CLIENT_MESSAGE = "已连接多个可截图客户端，请只保留目标设备后重试。"
PUBLIC_BUSY_MESSAGE = "远程客户端正在处理其他采集任务，请稍后重试。"
PUBLIC_TIMEOUT_MESSAGE = "远程截图超时，请检查网络或客户端截图权限。"
PUBLIC_DISCONNECTED_MESSAGE = "远程客户端已断开，本次截图未完成。"
PUBLIC_STOPPED_MESSAGE = "远程识屏服务已停止，请稍后重试。"
PUBLIC_CAPTURE_FAILED_MESSAGE = "远程客户端未能截图，请检查客户端日志和截图权限。"
PUBLIC_INVALID_FRAME_MESSAGE = "远程客户端返回了无效截图。"
PUBLIC_STALE_CACHE_MESSAGE = "远程截图已过期，请检查旧客户端推送状态。"

#: 错误码 → 公开提示。
_ERROR_PUBLIC_MESSAGES = {
    "no_client": PUBLIC_NO_CLIENT_MESSAGE,
    "unsupported_client": PUBLIC_UNSUPPORTED_CLIENT_MESSAGE,
    "ambiguous_client": PUBLIC_AMBIGUOUS_CLIENT_MESSAGE,
    "busy": PUBLIC_BUSY_MESSAGE,
    "timeout": PUBLIC_TIMEOUT_MESSAGE,
    "disconnected": PUBLIC_DISCONNECTED_MESSAGE,
    "stopped": PUBLIC_STOPPED_MESSAGE,
    "capture_failed": PUBLIC_CAPTURE_FAILED_MESSAGE,
    "invalid_frame": PUBLIC_INVALID_FRAME_MESSAGE,
    "stale_cache": PUBLIC_STALE_CACHE_MESSAGE,
}


class RemoteScreenshotError(RuntimeError):
    """按需远程截图的可解释失败。

    ``code`` 用于程序判断与日志，``public_message`` 是可直接展示给聊天用户的
    安全文案；更详细的技术原因只写日志，避免把服务器地址、认证令牌或客户端
    堆栈暴露给用户。
    """

    def __init__(self, code: str, public_message: str, *, detail: str = ""):
        super().__init__(detail or public_message)
        self.code = str(code or "capture_failed")
        self.public_message = str(public_message or PUBLIC_CAPTURE_FAILED_MESSAGE)
        self.detail = str(detail or "")


def public_message_for_code(code: str) -> str:
    """返回错误码对应的公开提示，未知代码降级为采集失败文案。"""
    return _ERROR_PUBLIC_MESSAGES.get(str(code or ""), PUBLIC_CAPTURE_FAILED_MESSAGE)


def make_screenshot_error(code: str, *, detail: str = "") -> RemoteScreenshotError:
    """按错误码构造 ``RemoteScreenshotError``。"""
    return RemoteScreenshotError(code, public_message_for_code(code), detail=detail)


@dataclass
class _PendingCapture:
    """一次在途的按需截图请求。"""

    request_id: str
    websocket: Any
    future: "asyncio.Future[tuple[bytes, str, dict[str, Any]]]"
    deadline: float


@dataclass
class _PendingMetadata:
    """某个连接暂存的一组截图元数据，等待二进制图片到达后整帧提交。"""

    meta: dict[str, Any]
    request_id: str = ""
    received_monotonic: float = 0.0


@dataclass
class _FrameDecision:
    """锁内决策结果：锁外据此发送响应，避免持锁等待网络。"""

    #: 需要发送的控制消息；``None`` 表示不发。
    reply: dict[str, Any] | None = None
    #: 发送失败或协议错误时是否需要关闭该连接。
    close_client: bool = False


class RemoteScreenReceiver:
    """Receive screenshots from a remote desktop client over WebSocket."""

    MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
    MAX_VIDEO_BYTES = 100 * 1024 * 1024
    MAX_VIDEO_CHUNK_BYTES = 5 * 1024 * 1024
    MAX_WEBSOCKET_MESSAGE_BYTES = 14 * 1024 * 1024

    PROTOCOL_VERSION = PROTOCOL_VERSION
    CAPABILITY_REQUEST_SCREENSHOT = CAPABILITY_REQUEST_SCREENSHOT
    DEFAULT_REQUEST_TIMEOUT = DEFAULT_REQUEST_TIMEOUT

    def __init__(
        self,
        *,
        port: int = 6315,
        auth_token: str = "",
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
        capture_active_window: bool = False,
    ):
        self.port = min(65535, max(1, int(port or 6315)))
        self.auth_token = str(auth_token or "").strip()
        #: 插件端「只截取活动窗口」配置；远程模式下由支持的客户端执行裁剪。
        self.capture_active_window = bool(capture_active_window)
        try:
            resolved_timeout = float(request_timeout)
        except (TypeError, ValueError):
            resolved_timeout = DEFAULT_REQUEST_TIMEOUT
        if not (resolved_timeout > 0) or resolved_timeout in (
            float("inf"),
            float("-inf"),
        ):
            resolved_timeout = DEFAULT_REQUEST_TIMEOUT
        #: 单次按需截图的等待预算；由插件侧按外层采集超时收紧。
        self.request_timeout = resolved_timeout
        self._server = None
        self._latest_image_bytes: bytes = b""
        self._latest_window_title: str = ""
        self._latest_meta: dict[str, Any] = {}
        self._latest_timestamp: float = 0.0
        #: 最近一次完整帧的单调时钟接收时间，时效判断不受墙钟跳变影响。
        self._latest_received_monotonic: float = 0.0
        #: 最近一次完整帧的来源协议版本：1 表示旧推送，2 表示 v2 连接，0 表示无帧。
        self._latest_protocol_version: int = 0
        self._latest_video_bytes: bytes = b""
        self._latest_video_meta: dict[str, Any] = {}
        self._video_uploads: dict[str, dict[str, Any]] = {}
        #: 仅包含认证完成、可接收命令的连接。
        self._connected_clients: set = set()
        #: 连接 → 已确认的能力集合。
        self._client_capabilities: dict[Any, set[str]] = {}
        #: 请求编号 → 在途请求；首版最多一个。
        self._pending_requests: dict[str, _PendingCapture] = {}
        #: 连接 → 暂存的截图元数据（每连接最多一组）。
        self._pending_screenshot_meta: dict[Any, _PendingMetadata] = {}
        #: 连接 → 客户端自报标识，仅用于诊断，不作为认证凭据。
        self._client_ids: dict[Any, str] = {}
        self._stopping = False
        #: 有界的后台清理任务集合（发送任务取消、连接关闭收尾）。
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def has_screenshot(self) -> bool:
        return bool(self._latest_image_bytes) and self._latest_timestamp > 0.0

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def latest_age_seconds(self) -> float:
        if self._latest_received_monotonic <= 0:
            return float("inf")
        return time.monotonic() - self._latest_received_monotonic

    @property
    def latest_video_age_seconds(self) -> float:
        completed_at = float(self._latest_video_meta.get("completed_at", 0.0) or 0.0)
        if completed_at <= 0:
            return float("inf")
        return time.time() - completed_at

    @property
    def latest_protocol_version(self) -> int:
        """最近一帧的来源协议版本；0 表示还没有可用帧。"""
        return int(self._latest_protocol_version or 0)

    @property
    def latest_window_title(self) -> str:
        """最近一次完整帧的窗口标题；没有可用帧时返回空字符串。

        只读探测，不发送网络请求。远程模式下这是活动窗口信息的唯一可信来源，
        调用方不得在它为空时回落到服务器本机的窗口查询。
        """
        if not self.has_screenshot:
            return ""
        return str(self._latest_window_title or "")

    @property
    def latest_system_stats(self) -> dict[str, Any]:
        """最近一次完整帧随帧上报的客户端系统统计。

        只读探测，不发送网络请求。按需截图默认不采样统计，因此正常情况可能是
        空字典；调用方必须把「没有数据」当作不产生提示，而不是回落到服务器
        本机的 psutil 采样。
        """
        if not self.has_screenshot:
            return {}
        stats = self._latest_meta.get("system_stats")
        return dict(stats) if isinstance(stats, dict) else {}

    @property
    def has_request_capable_client(self) -> bool:
        """是否存在声明了按需截图能力的已认证连接（只读探测，不发送消息）。"""
        if self._stopping:
            return False
        return len(self._live_clients(capable_only=True)) > 0

    @property
    def has_active_window_capable_client(self) -> bool:
        """是否存在声明了活动窗口裁剪能力的已认证连接。"""
        if self._stopping:
            return False
        return any(
            CAPABILITY_CAPTURE_ACTIVE_WINDOW
            in (self._client_capabilities.get(websocket) or set())
            for websocket in self._live_clients(capable_only=True)
        )

    @property
    def has_authenticated_client(self) -> bool:
        """是否存在任意已认证连接（含纯视频客户端）。"""
        if self._stopping:
            return False
        return len(self._live_clients()) > 0

    @staticmethod
    def _is_closed(websocket) -> bool:
        """连接是否已关闭；测试替身没有 ``state`` 属性时视为未关闭。"""
        try:
            state = getattr(websocket, "state", None)
        except Exception:
            return False
        if state is None:
            return False
        name = getattr(state, "name", None)
        if isinstance(name, str):
            return name.upper() in {"CLOSED", "CLOSING"}
        return False

    def _live_clients(self, *, capable_only: bool = False) -> list:
        """返回仍然存活的已认证连接；``capable_only`` 时额外要求截图能力。"""
        live = []
        for websocket in self._connected_clients:
            if self._is_closed(websocket):
                continue
            if capable_only:
                caps = self._client_capabilities.get(websocket) or set()
                if CAPABILITY_REQUEST_SCREENSHOT not in caps:
                    continue
            live.append(websocket)
        return live

    async def get_latest_screenshot(
        self,
        *,
        max_age: float | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        """只读返回最近一次完整接收的图片及其元数据。

        传入 ``max_age`` 时在同一把锁内完成读取与时效检查，避免检查通过后又
        被新帧替换造成判断与内容不一致。本方法从不发起网络请求。
        """
        async with self._lock:
            if max_age is not None:
                age = (
                    float("inf")
                    if self._latest_received_monotonic <= 0
                    else time.monotonic() - self._latest_received_monotonic
                )
                if not self._latest_image_bytes or age > float(max_age):
                    raise make_screenshot_error(
                        "stale_cache",
                        detail=f"远程缓存不可用或已过期: age={age:.1f}s",
                    )
            return (
                self._latest_image_bytes,
                self._latest_window_title,
                dict(self._latest_meta),
            )

    async def get_latest_video(self) -> tuple[bytes, dict[str, Any]]:
        """Return the most recently completed remote video upload."""
        async with self._lock:
            return self._latest_video_bytes, dict(self._latest_video_meta)

    # ------------------------------------------------------------------
    # 服务生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self.is_running:
            return
        if websockets is None or ws_serve is None:
            logger.error("websockets 库未安装，无法启动远程接收服务")
            return

        # 重新 start 前重置停止标志，避免旧实例状态带入新实例。
        self._stopping = False
        self._server = await ws_serve(
            self._handle_client,
            "0.0.0.0",
            self.port,
            max_size=self.MAX_WEBSOCKET_MESSAGE_BYTES,
            close_timeout=1.0,
        )
        if not self.auth_token:
            logger.warning("远程识屏未设置认证令牌，任何可访问该端口的客户端都能推送截图")
        logger.info(f"远程识屏 WebSocket 服务已启动，监听端口 {self.port}")

    async def stop(self) -> None:
        """停止服务；可重复调用，且无需依赖已启动的 server 对象。"""
        self._stopping = True
        # 先唤醒所有等待者，再关连接，避免请求协程等满超时。
        self._fail_all_pending("stopped", "接收服务已停止")
        async with self._lock:
            self._pending_screenshot_meta.clear()
            self._client_capabilities.clear()
            self._client_ids.clear()
            self._connected_clients.clear()
            self._video_uploads.clear()

        server = self._server
        self._server = None
        if server is not None:
            try:
                server.close()
                await server.wait_closed()
            except Exception as e:
                logger.debug(f"关闭远程接收服务失败: {e}")
        await self._reap_cleanup_tasks()
        logger.info("远程识屏 WebSocket 服务已停止")

    # ------------------------------------------------------------------
    # 连接处理
    # ------------------------------------------------------------------

    async def _handle_client(self, websocket) -> None:
        client_addr = websocket.remote_address
        logger.info(f"远程识屏客户端连接: {client_addr}")
        registered = False

        try:
            if self._stopping:
                await websocket.close(4004, "服务正在停止")
                return

            if self.auth_token:
                try:
                    auth_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    auth_data = json.loads(auth_msg) if isinstance(auth_msg, str) else {}
                    supplied_token = str(auth_data.get("token", "") or "")
                    if not secrets.compare_digest(supplied_token, self.auth_token):
                        await websocket.close(4001, "认证失败")
                        logger.warning(f"客户端认证失败: {client_addr}")
                        return
                    await websocket.send(json.dumps({
                        "status": "authenticated",
                        "protocol_version": PROTOCOL_VERSION,
                        "capabilities": [CAPABILITY_REQUEST_SCREENSHOT],
                    }))
                except asyncio.TimeoutError:
                    await websocket.close(4002, "认证超时")
                    return
                except Exception as e:
                    await websocket.close(4003, f"认证错误: {e}")
                    return
            else:
                await websocket.send(json.dumps({
                    "status": "ready",
                    "protocol_version": PROTOCOL_VERSION,
                    "capabilities": [CAPABILITY_REQUEST_SCREENSHOT],
                }))

            # 认证完成后才登记为可路由连接。
            self._connected_clients.add(websocket)
            registered = True
            logger.info(
                f"客户端认证通过: {client_addr}，当前连接数: {len(self._connected_clients)}"
            )

            async for message in websocket:
                await self._process_message(message, websocket)

        except websockets.exceptions.ConnectionClosed:
            logger.debug(f"客户端断开: {client_addr}")
        except Exception as e:
            logger.error(f"远程识屏客户端处理异常: {e}")
        finally:
            if registered:
                self._cleanup_client(websocket)
            logger.info(
                f"客户端断开: {client_addr}，当前连接数: {len(self._connected_clients)}"
            )

    def _cleanup_client(self, websocket) -> None:
        """连接断开后的幂等清理：能力、暂存元数据、对应等待者。"""
        self._connected_clients.discard(websocket)
        self._client_capabilities.pop(websocket, None)
        self._client_ids.pop(websocket, None)
        self._pending_screenshot_meta.pop(websocket, None)
        self._fail_pending_for_client(websocket, "disconnected", "客户端连接已断开")

    # ------------------------------------------------------------------
    # 请求生命周期
    # ------------------------------------------------------------------

    def _select_capture_client(self):
        """选择唯一的按需截图目标连接。"""
        if self._stopping:
            raise make_screenshot_error("stopped", detail="接收服务正在停止")
        capable = self._live_clients(capable_only=True)
        if len(capable) == 1:
            return capable[0]
        if len(capable) > 1:
            raise make_screenshot_error(
                "ambiguous_client",
                detail=f"存在 {len(capable)} 个可截图客户端，无法唯一确定目标",
            )
        if self._live_clients():
            raise make_screenshot_error(
                "unsupported_client",
                detail="已连接客户端均未声明 request_screenshot 能力",
            )
        raise make_screenshot_error("no_client", detail="没有可用的远程客户端连接")

    def _active_pending(self, request_id: str) -> _PendingCapture | None:
        """返回仍然有效（未超时、未完成）的等待者。"""
        pending = self._pending_requests.get(request_id)
        if pending is None:
            return None
        if pending.future.done():
            return None
        if time.monotonic() >= pending.deadline:
            return None
        return pending

    def _fail_pending(self, pending: _PendingCapture, code: str, detail: str = "") -> None:
        """以权威错误结束一个等待者；已完成或已取消时安全跳过。"""
        future = pending.future
        if future.done():
            return
        try:
            future.set_exception(make_screenshot_error(code, detail=detail))
        except (asyncio.InvalidStateError, RuntimeError):  # pragma: no cover - 竞态保护
            return

    def _fail_pending_for_client(self, websocket, code: str, detail: str = "") -> None:
        for pending in list(self._pending_requests.values()):
            if pending.websocket is websocket:
                self._fail_pending(pending, code, detail)

    def _fail_all_pending(self, code: str, detail: str = "") -> None:
        for pending in list(self._pending_requests.values()):
            self._fail_pending(pending, code, detail)

    def _fail_and_build_error(
        self,
        pending: _PendingCapture | None,
        code: str,
        error_text: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        """锁内调用：失败对应等待者并构造错误响应负载。"""
        if pending is not None:
            self._fail_pending(pending, code, error_text)
        payload: dict[str, Any] = {"error": error_text}
        if request_id:
            payload["request_id"] = request_id
        if code:
            payload["code"] = code
        return payload

    def _finish_request_future(self, future) -> None:
        """请求收尾：取消仍未完成的 Future 并消费未读取的异常。"""
        if not future.done():
            future.cancel()
        try:
            future.exception()
        except (asyncio.CancelledError, asyncio.InvalidStateError):
            pass
        except Exception:
            pass

    def _track_cleanup_task(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._consume_cleanup_task)

    def _consume_cleanup_task(self, task: asyncio.Task) -> None:
        self._cleanup_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.exception()
        except Exception:
            pass

    async def _reap_cleanup_tasks(self, timeout: float = 2.0) -> None:
        """有界回收遗留的发送/关闭任务。"""
        tasks = [task for task in self._cleanup_tasks if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            try:
                await asyncio.wait(tasks, timeout=timeout)
            except Exception:  # pragma: no cover - 防御性
                pass
        for task in list(self._cleanup_tasks):
            self._consume_cleanup_task(task)

    def _reap_send_task(self, websocket, send_task: asyncio.Task) -> None:
        """回收发送任务：已完成取出异常，仍阻塞则关闭连接并取消。"""
        if send_task.done():
            if not send_task.cancelled():
                try:
                    send_task.exception()
                except Exception:
                    pass
            return
        send_task.cancel()

        async def _close_after_send() -> None:
            try:
                await websocket.close(code=1011, reason="screenshot request aborted")
            except Exception:
                pass

        self._track_cleanup_task(_close_after_send())

    def _map_send_failure(self, exc: Exception) -> RemoteScreenshotError:
        """把发送阶段异常映射为专用错误，避免 ConnectionClosed 泄漏到用户入口。"""
        if self._stopping:
            return make_screenshot_error("stopped", detail=f"发送命令失败: {exc}")
        if websockets is not None:
            closed_errors = (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.ConnectionClosedError,
                websockets.exceptions.ConnectionClosedOK,
            )
            if isinstance(exc, closed_errors):
                return make_screenshot_error("disconnected", detail=f"连接已关闭: {exc}")
        return make_screenshot_error("disconnected", detail=f"发送截图命令失败: {exc}")

    async def request_screenshot(
        self,
        timeout: float | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        """请求目标客户端在收到命令后重新采集一张截图。

        成功时返回与该请求绑定的完整帧，不会在完成后再读取全局缓存，因此并发
        请求或其他客户端的推送不会覆盖本次结果。失败时抛出可解释的运行错误。
        """
        try:
            budget = float(timeout) if timeout is not None else float(self.request_timeout)
        except (TypeError, ValueError):
            budget = float(self.request_timeout)
        if not (budget > 0) or budget in (float("inf"), float("-inf")):
            budget = float(self.request_timeout)

        websocket = self._select_capture_client()
        if self._pending_requests:
            raise make_screenshot_error("busy", detail="已有在途截图请求")

        request_id = secrets.token_hex(16)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + budget
        future: asyncio.Future = loop.create_future()
        # 必须先登记再发送：本机或低延迟网络可能在 send() 返回前就回包。
        self._pending_requests[request_id] = _PendingCapture(
            request_id=request_id,
            websocket=websocket,
            future=future,
            deadline=deadline,
        )

        async def send_request() -> None:
            if loop.time() >= deadline:
                raise asyncio.TimeoutError()
            await websocket.send(json.dumps(self._build_request_command(request_id, websocket)))

        send_task = asyncio.ensure_future(send_request())
        try:
            done, _ = await asyncio.wait(
                {send_task, future},
                timeout=max(0.0, deadline - loop.time()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise make_screenshot_error("timeout", detail="等待截图超时")
            if future.done():
                # 包括 stopped / disconnected；不能继续卡在 ws.send() 上。
                return self._resolve_future_result(future)
            # 发送先完成：把发送异常映射成专用错误，再继续等待结果。
            try:
                await send_task
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as exc:
                raise make_screenshot_error("timeout", detail="发送命令超时") from exc
            except Exception as exc:
                raise self._map_send_failure(exc) from exc
            try:
                return await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=max(0.0, deadline - loop.time()),
                )
            except asyncio.TimeoutError as exc:
                raise make_screenshot_error("timeout", detail="等待截图超时") from exc
        except asyncio.CancelledError:
            raise
        finally:
            self._pending_requests.pop(request_id, None)
            self._finish_request_future(future)
            self._reap_send_task(websocket, send_task)

    def _build_request_command(self, request_id: str, websocket) -> dict[str, Any]:
        """构造截图命令。

        只有目标客户端声明了对应能力时才下发范围要求；否则客户端会忽略未知
        字段并继续全屏，服务端据此在日志里如实记录降级原因。
        """
        command: dict[str, Any] = {
            "type": "request_screenshot",
            "request_id": request_id,
        }
        if not self.capture_active_window:
            return command
        capabilities = self._client_capabilities.get(websocket) or set()
        if CAPABILITY_CAPTURE_ACTIVE_WINDOW in capabilities:
            command["capture_active_window"] = True
        else:
            logger.debug(
                "客户端未声明 %s 能力，本次仍请求整屏截图",
                CAPABILITY_CAPTURE_ACTIVE_WINDOW,
            )
        return command

    def _resolve_future_result(self, future) -> tuple[bytes, str, dict[str, Any]]:
        """取出等待者结果并把异常统一为 ``RemoteScreenshotError``。"""
        try:
            return future.result()
        except RemoteScreenshotError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise make_screenshot_error(
                "capture_failed", detail=f"截图请求失败: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # 收帧事务
    # ------------------------------------------------------------------

    def _commit_screenshot(
        self,
        *,
        jpeg_bytes: bytes,
        title: str,
        meta: dict[str, Any],
        protocol_version: int,
        pending: _PendingCapture | None = None,
    ) -> None:
        """原子提交一整帧。调用方必须已持有 ``self._lock``，且不得在此 await。

        带请求编号的按需响应会在锁内再次校验请求是否仍然有效，防止等待期间
        已经超时或取消的请求靠事件循环调度延迟「偷跑」成功——只检查 Future
        未完成是不够的，事件循环繁忙时超时回调可能尚未执行。
        """
        now_monotonic = time.monotonic()
        if pending is not None and now_monotonic >= pending.deadline:
            self._fail_pending(pending, "timeout", "整帧到达时请求已超时")
            return

        self._latest_image_bytes = jpeg_bytes
        self._latest_window_title = str(title or "")
        self._latest_meta = dict(meta)
        self._latest_timestamp = time.time()
        self._latest_received_monotonic = now_monotonic
        self._latest_protocol_version = int(protocol_version or 1)

        if pending is not None and not pending.future.done():
            try:
                pending.future.set_result(
                    (jpeg_bytes, self._latest_window_title, dict(meta))
                )
            except (asyncio.InvalidStateError, RuntimeError):  # pragma: no cover
                pass

    @staticmethod
    def _validate_request_id(value: Any) -> tuple[str, str]:
        """校验请求编号；返回 ``(编号, 错误码)``，空编号表示旧协议推送。"""
        if value is None or value == "":
            return "", ""
        if not isinstance(value, str):
            return "", "invalid_request"
        if len(value) > MAX_REQUEST_ID_LENGTH or not _REQUEST_ID_PATTERN.match(value):
            return "", "invalid_request"
        return value, ""

    def _validate_pending_for_frame(
        self, websocket, request_id: str
    ) -> tuple[_PendingCapture | None, str]:
        """按连接与编号校验等待者，返回 ``(等待者, 错误码)``。"""
        if not request_id:
            return None, ""
        pending = self._active_pending(request_id)
        if pending is None:
            return None, "expired_request"
        if pending.websocket is not websocket:
            return None, "invalid_request"
        return pending, ""

    async def _send_control(self, websocket, payload: dict[str, Any]) -> bool:
        """有界发送一条无需 ACK 的控制消息；返回是否发送成功。"""
        try:
            await asyncio.wait_for(
                websocket.send(json.dumps(payload)),
                timeout=CONTROL_SEND_TIMEOUT,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning("远程客户端控制消息发送超时，准备关闭连接")
            self._schedule_client_close(websocket)
            return False
        except Exception as e:
            logger.debug(f"远程客户端控制消息发送失败: {e}")
            return False

    def _schedule_client_close(self, websocket) -> None:
        """有界关闭一个失效连接，不阻塞请求协程。"""

        async def _close() -> None:
            try:
                await websocket.close(code=1011, reason="control message timeout")
            except Exception:
                pass

        self._track_cleanup_task(_close())

    # ------------------------------------------------------------------
    # 消息分发
    # ------------------------------------------------------------------

    async def _process_message(self, message, websocket) -> None:
        if isinstance(message, bytes):
            decision = await self._handle_binary_frame(message, websocket)
            await self._apply_frame_decision(websocket, decision)
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

        if not msg_type and "token" in data and not self.auth_token:
            # 客户端无法在连接前知道服务端是否启用了认证。允许它在无认证服务端
            # 仍发送已配置的令牌前言，并静默消费，避免该消息干扰随后的能力 ACK。
            logger.debug("忽略无认证模式下多余的客户端令牌前言")
            return

        if msg_type == "client_capabilities":
            await self._handle_client_capabilities(data, websocket)
            return

        if msg_type == "screenshot_meta":
            decision = await self._handle_screenshot_meta(data, websocket)
            await self._apply_frame_decision(websocket, decision)
            return

        if msg_type == "capture_error":
            await self._handle_capture_error(data, websocket)
            return

        if msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))
            return

        if msg_type == "video_meta":
            await self._handle_video_meta(data, websocket)
            return

        if msg_type == "video_chunk":
            await self._handle_video_chunk(data, websocket)
            return

        if msg_type == "video_complete":
            await self._handle_video_complete(data, websocket)
            return

        if msg_type == "screenshot_bundle":
            decision = await self._handle_screenshot_bundle(data, websocket)
            await self._apply_frame_decision(websocket, decision)
            return

        await websocket.send(json.dumps({"error": f"未知消息类型: {msg_type}"}))

    async def _apply_frame_decision(
        self, websocket, decision: _FrameDecision
    ) -> None:
        """锁外执行锁内做出的收帧决策。"""
        if decision.reply is not None:
            sent = await self._send_control(websocket, decision.reply)
            if not sent:
                decision.close_client = True
        if decision.close_client:
            self._schedule_client_close(websocket)

    async def _handle_client_capabilities(self, data: dict[str, Any], websocket) -> None:
        """处理客户端能力声明；未认证连接不能进入可选目标。"""
        if self._stopping:
            await self._send_control(websocket, {
                "error": "服务正在停止",
                "code": "stopped",
            })
            return
        if websocket not in self._connected_clients:
            await websocket.send(json.dumps({"error": "尚未完成认证，无法声明能力"}))
            return

        raw_caps = data.get("capabilities", [])
        if isinstance(raw_caps, str):
            raw_caps = [raw_caps]
        capabilities = {
            str(item).strip()
            for item in (raw_caps if isinstance(raw_caps, (list, tuple, set)) else [])
            if str(item).strip()
        }
        client_id = str(data.get("client_id", "") or "").strip()
        if client_id:
            self._client_ids[websocket] = client_id[:128]
        self._client_capabilities[websocket] = capabilities
        await websocket.send(json.dumps({
            "status": "capabilities_received",
            "protocol_version": PROTOCOL_VERSION,
            # 会话级默认：显式周期推送没有逐次请求可用，客户端据此决定截图范围。
            "options": {
                "capture_active_window": bool(self.capture_active_window),
            },
        }))
        logger.info(
            "远程客户端能力已登记: capabilities=%s client_id=%s",
            sorted(capabilities) or "[]",
            self._client_ids.get(websocket, "") or "<unknown>",
        )

    async def _handle_screenshot_meta(
        self, data: dict[str, Any], websocket
    ) -> _FrameDecision:
        """暂存该连接的截图元数据；此时缓存仍是上一张完整帧。"""
        request_id, id_error = self._validate_request_id(data.get("request_id"))
        if id_error:
            return _FrameDecision(reply={
                "error": "request_id 无效",
                "code": id_error,
            })

        async with self._lock:
            if request_id:
                pending = self._active_pending(request_id)
                if pending is None or pending.websocket is not websocket:
                    return _FrameDecision(reply={
                        "error": "请求编号无效或已过期",
                        "code": "expired_request",
                        "request_id": request_id,
                    })

            existing = self._pending_screenshot_meta.get(websocket)
            if existing is not None:
                # 协议顺序错误：不静默覆盖，否则下一张二进制图片会配错标题。
                self._pending_screenshot_meta.pop(websocket, None)
                stale_id = existing.request_id
                if stale_id:
                    stale_pending = self._active_pending(stale_id)
                    if stale_pending is not None and stale_pending.websocket is websocket:
                        self._fail_pending(
                            stale_pending, "capture_failed", "客户端元数据发送顺序错误"
                        )
                return _FrameDecision(
                    reply={
                        "error": "上一帧元数据尚未收到对应图片",
                        "code": "protocol_error",
                        **({"request_id": stale_id} if stale_id else {}),
                    },
                    close_client=True,
                )

            is_v2_client = websocket in self._client_capabilities
            window_title = str(data.get("window_title", "") or "")
            stored_meta = {
                "window_title": window_title,
                "system_stats": data.get("system_stats", {}),
                "timestamp": data.get("timestamp", time.time()),
                "client_id": data.get("client_id", ""),
                # 客户端如实上报的实际截图范围：window / fullscreen。
                "capture_scope": str(data.get("capture_scope", "") or ""),
                "protocol_version": PROTOCOL_VERSION if is_v2_client else 1,
            }
            if request_id:
                stored_meta["request_id"] = request_id
            self._pending_screenshot_meta[websocket] = _PendingMetadata(
                meta=stored_meta,
                request_id=request_id,
                received_monotonic=time.monotonic(),
            )

        ack: dict[str, Any] = {"status": "meta_received"}
        if request_id:
            ack["request_id"] = request_id
        return _FrameDecision(reply=ack)

    async def _handle_binary_frame(
        self, message: bytes, websocket
    ) -> _FrameDecision:
        """处理二进制 JPEG：与暂存元数据一起原子提交。"""
        async with self._lock:
            stored = self._pending_screenshot_meta.pop(websocket, None)
            is_v2_client = websocket in self._client_capabilities
            expired = bool(
                stored is not None
                and stored.received_monotonic > 0
                and (time.monotonic() - stored.received_monotonic) > META_TRANSACTION_TTL
            )
            if expired and (is_v2_client or (stored is not None and stored.request_id)):
                # v2 事务超期后不能继续在同一连接上接收裸图，否则下一帧可能配错标题。
                stale_id = stored.request_id if stored else ""
                return _FrameDecision(
                    reply={
                        "error": "帧事务已超时",
                        "code": "expired_request",
                        **({"request_id": stale_id} if stale_id else {}),
                    },
                    close_client=True,
                )
            if expired:
                # 旧客户端上传较慢时只丢弃过期帧头，按无元数据兼容路径继续。
                logger.debug("旧客户端截图帧头已过期，按无元数据路径接收该帧")
                stored = None

            request_id = stored.request_id if stored else ""
            meta = dict(stored.meta) if stored else {}
            title = str(meta.get("window_title", "") or "")
            # 旧客户端的裸 JPEG 没有元数据；仍明确标记来源协议，供缓存兼容判断。
            meta.setdefault("protocol_version", 2 if is_v2_client else 1)

            if is_v2_client and stored is None:
                # v2 客户端必须走「元数据 + 图片」事务，绝不降级成裸图兼容路径。
                return _FrameDecision(reply={
                    "error": "v2 客户端缺少配对的截图元数据",
                    "code": "invalid_frame",
                })

            pending: _PendingCapture | None = None
            if request_id:
                pending, id_error = self._validate_pending_for_frame(
                    websocket, request_id
                )
                if id_error:
                    # 迟到、错连接或未知编号：不完成等待者，也不污染缓存。
                    return _FrameDecision(reply={
                        "error": "请求编号无效或已过期",
                        "code": id_error,
                        "request_id": request_id,
                    })

            error = self._validate_jpeg(message)
            if error:
                return _FrameDecision(
                    reply=self._fail_and_build_error(
                        pending, "invalid_frame", error, request_id
                    )
                )

            self._commit_screenshot(
                jpeg_bytes=message,
                title=title,
                meta=meta,
                protocol_version=2 if is_v2_client else 1,
                pending=pending,
            )
            ack: dict[str, Any] = {"status": "binary_screenshot_received"}
            if request_id:
                ack["request_id"] = request_id
            logger.debug(f"收到截图: {len(message)} bytes")

        return _FrameDecision(reply=ack)

    async def _handle_screenshot_bundle(
        self, data: dict[str, Any], websocket
    ) -> _FrameDecision:
        """处理 Base64 bundle 截图，复用与二进制相同的提交与校验路径。"""
        request_id, id_error = self._validate_request_id(data.get("request_id"))
        if id_error:
            return _FrameDecision(reply={
                "error": "request_id 无效",
                "code": id_error,
            })

        jpeg_b64 = str(data.get("image", "") or "")
        # 先做与网络无关的校验，再在锁内确认请求归属，缩短持锁时间。
        decode_error = ""
        jpeg_bytes = b""
        if not jpeg_b64:
            decode_error = "缺少 image 字段"
        elif len(jpeg_b64) > ((self.MAX_SCREENSHOT_BYTES + 2) // 3) * 4:
            decode_error = "截图超过 10 MiB 限制"
        else:
            try:
                jpeg_bytes = base64.b64decode(jpeg_b64, validate=True)
            except (binascii.Error, ValueError, TypeError):
                decode_error = "image 字段不是有效的 base64"
            else:
                decode_error = self._validate_jpeg(jpeg_bytes)

        async with self._lock:
            is_v2_client = websocket in self._client_capabilities
            title = str(data.get("window_title", "") or "")
            meta = {
                "window_title": title,
                "system_stats": data.get("system_stats", {}),
                "timestamp": data.get("timestamp", time.time()),
                "client_id": data.get("client_id", ""),
                "capture_scope": str(data.get("capture_scope", "") or ""),
                "protocol_version": PROTOCOL_VERSION if is_v2_client else 1,
            }
            if request_id:
                meta["request_id"] = request_id

            pending: _PendingCapture | None = None
            if request_id:
                pending, id_error = self._validate_pending_for_frame(
                    websocket, request_id
                )
                if id_error:
                    return _FrameDecision(reply={
                        "error": "请求编号无效或已过期",
                        "code": id_error,
                        "request_id": request_id,
                    })

            # bundle 自带完整元数据，同时清掉可能残留的暂存项，避免污染下一帧。
            self._pending_screenshot_meta.pop(websocket, None)

            if decode_error:
                return _FrameDecision(
                    reply=self._fail_and_build_error(
                        pending, "invalid_frame", decode_error, request_id
                    )
                )

            self._commit_screenshot(
                jpeg_bytes=jpeg_bytes,
                title=title,
                meta=meta,
                protocol_version=2 if is_v2_client else 1,
                pending=pending,
            )
            ack: dict[str, Any] = {"status": "screenshot_received"}
            if request_id:
                ack["request_id"] = request_id
            logger.debug(f"收到 bundle 截图: {len(jpeg_bytes)} bytes")

        return _FrameDecision(reply=ack)

    async def _handle_capture_error(self, data: dict[str, Any], websocket) -> None:
        """处理客户端明确上报的采集失败。"""
        request_id, id_error = self._validate_request_id(data.get("request_id"))
        if id_error:
            await self._send_control(websocket, {
                "error": "request_id 无效",
                "code": id_error,
            })
            return
        client_code = str(data.get("code", "") or "").strip()
        mapped_code = _CLIENT_ERROR_CODE_MAP.get(client_code, "capture_failed")
        error_text = str(data.get("error", "") or "")[:MAX_ERROR_TEXT_LENGTH]

        if request_id:
            pending = self._active_pending(request_id)
            if pending is not None and pending.websocket is websocket:
                self._fail_pending(
                    pending,
                    mapped_code,
                    error_text or f"客户端上报 {client_code or 'capture_failed'}",
                )
        logger.debug(
            "远程客户端上报采集错误: code=%s mapped=%s request_id=%s",
            client_code or "<empty>",
            mapped_code,
            request_id or "<none>",
        )
        # 客户端错误不另发 ACK，避免多一条无归属响应。

    # ------------------------------------------------------------------
    # 视频（本次不修改其协议）
    # ------------------------------------------------------------------

    async def _handle_video_meta(self, data: dict[str, Any], websocket) -> None:
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
        reply: dict[str, Any] = {"status": "video_ready", "upload_id": upload_id}
        async with self._lock:
            now = time.time()
            self._video_uploads = {
                key: value
                for key, value in self._video_uploads.items()
                if now - float(value.get("created_at", now) or now) < 300
            }
            if len(self._video_uploads) >= 4 and upload_id not in self._video_uploads:
                reply = {"error": "同时进行的视频上传过多"}
            else:
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
        await websocket.send(json.dumps(reply))

    async def _handle_video_chunk(self, data: dict[str, Any], websocket) -> None:
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
        reply: dict[str, Any] = {
            "status": "video_chunk_received",
            "upload_id": upload_id,
            "index": chunk_index,
        }
        async with self._lock:
            upload = self._video_uploads.get(upload_id)
            if upload is None:
                reply = {"error": "未知 upload_id"}
            else:
                if chunk_index not in upload["chunks"]:
                    upload["chunks"][chunk_index] = chunk
                    upload["received_size"] += len(chunk)
                if upload["received_size"] > upload["total_size"]:
                    self._video_uploads.pop(upload_id, None)
                    reply = {"error": "视频分块总大小超出声明值"}
        await websocket.send(json.dumps(reply))

    async def _handle_video_complete(self, data: dict[str, Any], websocket) -> None:
        upload_id = str(data.get("upload_id", "") or "").strip()
        reply: dict[str, Any] = {"status": "video_complete", "upload_id": upload_id}
        video_size = 0
        async with self._lock:
            upload = self._video_uploads.pop(upload_id, None)
            if upload is None:
                reply = {"error": "未知 upload_id"}
            else:
                chunks = upload["chunks"]
                expected_size = upload["total_size"]
                if upload["received_size"] != expected_size or not chunks:
                    reply = {"error": "视频分块不完整"}
                else:
                    video_bytes = b"".join(chunks[index] for index in sorted(chunks))
                    if len(video_bytes) != expected_size:
                        reply = {"error": "视频分块顺序或大小不匹配"}
                    else:
                        self._latest_video_bytes = video_bytes
                        self._latest_video_meta = dict(upload["meta"])
                        self._latest_video_meta["completed_at"] = time.time()
                        video_size = len(video_bytes)
        await websocket.send(json.dumps(reply))
        if video_size:
            logger.debug(f"收到远程录屏: {video_size} bytes")

    @classmethod
    def _validate_jpeg(cls, payload: bytes) -> str:
        if not payload:
            return "截图内容为空"
        if len(payload) > cls.MAX_SCREENSHOT_BYTES:
            return "截图超过 10 MiB 限制"
        if len(payload) < 4 or not payload.startswith(b"\xff\xd8") or not payload.endswith(b"\xff\xd9"):
            return "截图不是有效的 JPEG 数据"
        return ""
