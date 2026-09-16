# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from astrbot.api.message_components import Plain

from astrbot_plugin_screen_companion import main
from astrbot_plugin_screen_companion.core.remote_receiver import RemoteScreenshotError


class ToolContextTests(unittest.IsolatedAsyncioTestCase):
    def test_get_tool_event_supports_wrapped_and_direct_contexts(self) -> None:
        event = SimpleNamespace(unified_msg_origin="napcat:FriendMessage:2306087691")
        agent_context = SimpleNamespace(event=event)
        wrapper = SimpleNamespace(context=agent_context)

        self.assertIs(main._get_tool_event(wrapper), event)
        self.assertIs(main._get_tool_event(agent_context), event)

    def test_resolve_tool_event_uses_task_local_hook_fallback(self) -> None:
        event = SimpleNamespace(unified_msg_origin="napcat:FriendMessage:2306087691")
        token = main._screen_companion_current_tool_event.set(event)
        try:
            self.assertIs(main._resolve_tool_event(SimpleNamespace()), event)
        finally:
            main._screen_companion_current_tool_event.reset(token)
    async def test_screen_peek_passes_complete_context_to_permission_check(self) -> None:
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))
        received_contexts = []

        async def deny(_plugin, context, *, tool_name):
            received_contexts.append((context, tool_name))
            return False, "denied"

        with (
            patch.object(main, "_screen_companion_tool_plugin", object()),
            patch.object(main, "_ensure_tool_admin_permission", side_effect=deny),
        ):
            result = await main.ScreenPeekTool().call(wrapper)

        self.assertEqual(result, "denied")
        self.assertEqual(received_contexts, [(wrapper, "screen_peek")])

    async def test_screen_peek_keeps_direct_agent_context_intact(self) -> None:
        agent_context = SimpleNamespace(event=object(), context=object())
        received_contexts = []

        async def deny(_plugin, context, *, tool_name):
            received_contexts.append((context, tool_name))
            return False, "denied"

        with (
            patch.object(main, "_screen_companion_tool_plugin", object()),
            patch.object(main, "_ensure_tool_admin_permission", side_effect=deny),
        ):
            result = await main.ScreenPeekTool().call(agent_context)

        self.assertEqual(result, "denied")
        self.assertEqual(received_contexts, [(agent_context, "screen_peek")])

    async def test_usage_tool_passes_complete_context_to_permission_check(self) -> None:
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))
        received_contexts = []

        async def deny(_plugin, context, *, tool_name):
            received_contexts.append((context, tool_name))
            return False, "denied"

        with (
            patch.object(main, "_screen_companion_tool_plugin", object()),
            patch.object(main, "_ensure_tool_admin_permission", side_effect=deny),
        ):
            result = await main.ScreenUsageContextTool().call(wrapper)

        self.assertEqual(result, "denied")
        self.assertEqual(received_contexts, [(wrapper, "screen_usage_context")])

    async def test_tool_hooks_bind_and_clear_screen_event(self) -> None:
        event = SimpleNamespace(unified_msg_origin="napcat:FriendMessage:2306087691")
        tool = SimpleNamespace(name="screen_peek")
        token = main._screen_companion_current_tool_event.set(None)
        try:
            await main.ScreenCompanion.bind_screen_tool_event(
                object(), event, tool, {"question": "看看屏幕"}
            )
            self.assertIs(main._screen_companion_current_tool_event.get(), event)

            await main.ScreenCompanion.clear_screen_tool_event(
                object(), event, tool, {"question": "看看屏幕"}, "result"
            )
            self.assertIsNone(main._screen_companion_current_tool_event.get())
        finally:
            main._screen_companion_current_tool_event.reset(token)


class ScreenPeekRemoteCaptureTests(unittest.IsolatedAsyncioTestCase):
    """screen_peek 仅在远程图像模式要求新帧，并把远程错误呈现为工具失败。"""

    def _make_plugin(self, *, remote_mode: bool, recording: bool, result=None, error=None):
        plugin = SimpleNamespace(
            remote_mode=remote_mode,
            screen_recognition_mode=recording,
            _get_runtime_flag=lambda name, default=False: bool(
                getattr(SimpleNamespace(remote_mode=remote_mode), name, default)
            ),
            _use_screen_recording_mode=lambda: recording,
        )
        calls: list = []

        async def capture_recognition_context(**kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return {
                "media_kind": "image",
                "media_bytes": b"\xff\xd8x\xff\xd9",
                "active_window_title": "Editor",
            }

        plugin._capture_recognition_context = capture_recognition_context
        plugin._analyze_screen = AsyncMock(
            return_value=[Plain("看到了编辑器")] if result is None else result
        )
        return plugin, calls

    async def test_remote_image_mode_requests_fresh_frame(self) -> None:
        plugin, calls = self._make_plugin(remote_mode=True, recording=False)
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))

        with (
            patch.object(main, "_screen_companion_tool_plugin", plugin),
            patch.object(
                main, "_ensure_tool_admin_permission", AsyncMock(return_value=(True, ""))
            ),
        ):
            result = await main.ScreenPeekTool().call(wrapper, question="看看")

        self.assertEqual("看到了编辑器", result)
        self.assertEqual([{"force_fresh_capture": True}], calls)
        plugin._analyze_screen.assert_awaited_once()

    async def test_local_mode_keeps_default_capture_parameters(self) -> None:
        plugin, calls = self._make_plugin(remote_mode=False, recording=False)
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))

        with (
            patch.object(main, "_screen_companion_tool_plugin", plugin),
            patch.object(
                main, "_ensure_tool_admin_permission", AsyncMock(return_value=(True, ""))
            ),
        ):
            await main.ScreenPeekTool().call(wrapper)

        # 本地/共享目录模式保留原默认，不借远程改造改变本地选择。
        self.assertEqual([{"force_fresh_capture": False}], calls)

    async def test_remote_recording_mode_does_not_force_fresh_image(self) -> None:
        plugin, calls = self._make_plugin(remote_mode=True, recording=True)
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))

        with (
            patch.object(main, "_screen_companion_tool_plugin", plugin),
            patch.object(
                main, "_ensure_tool_admin_permission", AsyncMock(return_value=(True, ""))
            ),
        ):
            await main.ScreenPeekTool().call(wrapper)

        self.assertEqual([{"force_fresh_capture": False}], calls)

    async def test_remote_capture_error_is_surfaced_without_vision_call(self) -> None:
        error = RemoteScreenshotError(
            "timeout", "远程截图超时，请检查网络或客户端截图权限。"
        )
        plugin, _calls = self._make_plugin(
            remote_mode=True, recording=False, error=error
        )
        wrapper = SimpleNamespace(context=SimpleNamespace(event=object()))

        with (
            patch.object(main, "_screen_companion_tool_plugin", plugin),
            patch.object(
                main, "_ensure_tool_admin_permission", AsyncMock(return_value=(True, ""))
            ),
        ):
            result = await main.ScreenPeekTool().call(wrapper)

        self.assertIn(error.public_message, result)
        # 采集失败不进入视觉分析。
        plugin._analyze_screen.assert_not_called()

    async def test_denied_permission_never_requests_capture(self) -> None:
        plugin, calls = self._make_plugin(remote_mode=True, recording=False)
        wrapper = SimpleNamespace(context=SimpleNamespace(event=None))

        with (
            patch.object(main, "_screen_companion_tool_plugin", plugin),
            patch.object(
                main,
                "_ensure_tool_admin_permission",
                AsyncMock(return_value=(False, "denied")),
            ),
        ):
            result = await main.ScreenPeekTool().call(wrapper)

        self.assertEqual("denied", result)
        self.assertEqual([], calls)
        plugin._analyze_screen.assert_not_called()

    async def test_missing_tool_context_never_requests_capture(self) -> None:
        plugin, calls = self._make_plugin(remote_mode=True, recording=False)
        wrapper = SimpleNamespace()
        token = main._screen_companion_current_tool_event.set(None)
        try:
            with patch.object(main, "_screen_companion_tool_plugin", plugin):
                result = await main.ScreenPeekTool().call(wrapper)
        finally:
            main._screen_companion_current_tool_event.reset(token)

        self.assertIn("权限不足", result)
        self.assertEqual([], calls)

    async def test_work_collaboration_context_never_captures(self) -> None:
        plugin = ScreenCompanionRemoteEntryTests._make_work_plugin()
        # 只读缓存接口不得依赖任何采集入口：没有该属性本身即是约束。
        self.assertFalse(hasattr(plugin, "_capture_recognition_context"))
        api = main.ScreenCompanionExtensionAPI(plugin)

        result = await api.get_work_collaboration_context(user_id="10001")

        self.assertTrue(result["available"])
        plugin._analyze_screen.assert_not_called()


class ScreenCompanionRemoteEntryTests(unittest.IsolatedAsyncioTestCase):
    """自然语言与 /kp 入口的远程错误呈现。"""

    @staticmethod
    def _make_work_plugin() -> SimpleNamespace:
        now = datetime.datetime.now().timestamp()
        return SimpleNamespace(
            mask_activity_window_titles=False,
            enable_background_activity_tracking=True,
            is_running=False,
            auto_tasks={},
            _get_active_window_info=lambda: ("Editor", None),
            _identify_scene=lambda _window: "编程",
            _build_current_activity_snapshot=lambda: {
                "type": "工作",
                "scene": "编程",
                "window": "Editor",
                "app_name": "Editor",
                "resource_label": "Editor",
                "duration": 60,
                "end_time": now,
            },
            _build_activity_record_meta=lambda **kwargs: dict(kwargs),
            _get_recent_screen_analysis_traces=lambda limit=8: [],
            _analyze_screen=AsyncMock(),
        )

    async def test_natural_language_failure_reports_once_and_stops_event(self) -> None:
        error = RemoteScreenshotError(
            "no_client", "远程客户端未连接，请启动客户端后重试。"
        )
        captured_replies: list = []
        stop_calls: list = []

        class FakeEvent:
            message_str = "帮我看看屏幕上写了什么"
            unified_msg_origin = "napcat:FriendMessage:10001"

            def stop_event(self) -> None:
                stop_calls.append(True)

            def plain_result(self, text):
                captured_replies.append(text)
                return text

        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.enable_natural_language_screen_assist = True
        plugin.debug = False
        plugin._screen_assist_cooldowns = {}
        plugin._allow_implicit_screen_skill_trigger = lambda event, text: False
        plugin._extract_screen_assist_prompt = lambda text, allow_implicit: text
        plugin._is_private_message_event = lambda event: True
        plugin._ensure_admin_permission = AsyncMock(return_value=True)
        plugin._invoke_screen_skill = AsyncMock(side_effect=error)
        plugin._split_message = lambda text: [text]

        event = FakeEvent()
        results = [
            item
            async for item in plugin.on_natural_language_screen_assist(event)
        ]

        self.assertEqual(1, len(results))
        self.assertIn(error.public_message, results[0])
        self.assertEqual([True], stop_calls)
        # 失败时冷却已消费，但不应产生成功轨迹记录。
        plugin._invoke_screen_skill.assert_awaited_once()

    async def test_natural_language_not_triggered_never_captures(self) -> None:
        class FakeEvent:
            message_str = "今天天气不错"
            unified_msg_origin = "napcat:FriendMessage:10001"

        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.enable_natural_language_screen_assist = True
        plugin.debug = False
        plugin._allow_implicit_screen_skill_trigger = lambda event, text: False
        plugin._extract_screen_assist_prompt = lambda text, allow_implicit: ""
        plugin._invoke_screen_skill = AsyncMock()

        results = [
            item
            async for item in plugin.on_natural_language_screen_assist(FakeEvent())
        ]

        self.assertEqual([], results)
        plugin._invoke_screen_skill.assert_not_called()

    async def test_natural_language_disabled_never_captures(self) -> None:
        class FakeEvent:
            message_str = "帮我看看屏幕"
            unified_msg_origin = "napcat:FriendMessage:10001"

        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.enable_natural_language_screen_assist = False
        plugin._invoke_screen_skill = AsyncMock()

        results = [
            item
            async for item in plugin.on_natural_language_screen_assist(FakeEvent())
        ]

        self.assertEqual([], results)
        plugin._invoke_screen_skill.assert_not_called()

    async def test_group_message_never_captures(self) -> None:
        class FakeEvent:
            message_str = "帮我看看屏幕上写了什么"
            unified_msg_origin = "napcat:GroupMessage:999"

        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.enable_natural_language_screen_assist = True
        plugin.debug = False
        plugin._allow_implicit_screen_skill_trigger = lambda event, text: False
        plugin._extract_screen_assist_prompt = lambda text, allow_implicit: text
        plugin._is_private_message_event = lambda event: False
        plugin._is_group_message_event = lambda event: True
        plugin._get_event_sender_id = lambda event: "999"
        plugin._invoke_screen_skill = AsyncMock()

        results = [
            item
            async for item in plugin.on_natural_language_screen_assist(FakeEvent())
        ]

        self.assertEqual([], results)
        plugin._invoke_screen_skill.assert_not_called()


class SharedActivityExtensionTests(unittest.TestCase):
    def test_external_watch_is_recorded_without_overwriting_screen_activity(self) -> None:
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin._external_shared_activities = {}
        plugin.current_activity = "工作:编程:VS Code"
        plugin.activity_start_time = 1.0
        captured = []
        plugin._build_activity_record_meta = lambda **kwargs: dict(kwargs)
        plugin._append_activity_record = lambda **kwargs: captured.append(kwargs) or True
        api = main.ScreenCompanionExtensionAPI(plugin)

        item = api.notify_shared_activity_started(
            "together:room",
            user_id="10001",
            kind="shared_watch",
            label="正在一起看《测试影片》",
            source_plugin="astrbot_plugin_together_companion",
        )
        item["started_at"] -= 10
        plugin._external_shared_activities["together:room"] = item
        ended = api.notify_shared_activity_ended("together:room")

        self.assertTrue(ended)
        self.assertEqual("工作:编程:VS Code", plugin.current_activity)
        self.assertEqual("摸鱼:视频:正在一起看《测试影片》", captured[0]["activity"])
        self.assertEqual("astrbot_plugin_together_companion", captured[0]["activity_meta"]["capture_source"])

    def test_external_work_is_recorded_as_office_work(self) -> None:
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin._external_shared_activities = {}
        captured = []
        plugin._build_activity_record_meta = lambda **kwargs: dict(kwargs)
        plugin._append_activity_record = lambda **kwargs: captured.append(kwargs) or True
        api = main.ScreenCompanionExtensionAPI(plugin)

        item = api.notify_shared_activity_started(
            "together:work-room",
            kind="shared_work",
            source_plugin="astrbot_plugin_together_companion",
        )
        item["started_at"] -= 10
        plugin._external_shared_activities["together:work-room"] = item

        self.assertTrue(api.notify_shared_activity_ended("together:work-room"))
        self.assertEqual("工作:办公:一起工作", captured[0]["activity"])
        self.assertEqual("工作", captured[0]["activity_meta"]["activity_type"])
        self.assertEqual("办公", captured[0]["activity_meta"]["scene"])


class WorkCollaborationContextTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _make_plugin(*, privacy_masked: bool = False) -> SimpleNamespace:
        window = "Secret roadmap - Visual Studio Code"
        now = datetime.datetime.now().isoformat()
        snapshot = {
            "type": "工作",
            "scene": "编程",
            "window": window,
            "app_name": "Visual Studio Code",
            "resource_label": "Secret roadmap",
            "duration": 125,
            "end_time": datetime.datetime.now().timestamp(),
        }
        trace = {
            "timestamp": now,
            "status": "ok",
            "scene": "编程",
            "active_window_title": window,
            "display_title": "Secret roadmap",
            "fact_summary": "正在 Secret roadmap 中整理下一版本的实现步骤",
            "frame_labels": ["不应暴露"],
            "image": "not-returned",
        }

        def build_meta(*, activity_type, scene, window):
            return {
                "type": activity_type,
                "scene": scene,
                "window": window,
                "app_name": "Visual Studio Code",
                "resource_label": "Secret roadmap",
            }

        return SimpleNamespace(
            mask_activity_window_titles=privacy_masked,
            enable_background_activity_tracking=True,
            is_running=False,
            auto_tasks={},
            _get_active_window_info=lambda: (window, None),
            _identify_scene=lambda _window: "编程",
            _build_current_activity_snapshot=lambda: dict(snapshot),
            _build_activity_record_meta=build_meta,
            _get_recent_screen_analysis_traces=lambda limit=8: [dict(trace)][:limit],
        )

    async def test_work_context_uses_cached_structured_state(self) -> None:
        api = main.ScreenCompanionExtensionAPI(self._make_plugin())

        result = await api.get_work_collaboration_context(user_id="10001")

        self.assertTrue(result["available"])
        self.assertTrue(result["context_available"])
        self.assertTrue(result["tracking_enabled"])
        self.assertEqual("工作", result["current"]["type"])
        self.assertEqual("编程", result["current"]["scene"])
        self.assertEqual("Visual Studio Code", result["current"]["app_name"])
        self.assertEqual(125, result["current"]["duration_seconds"])
        self.assertIn("下一版本", result["observation"]["summary"])
        self.assertGreater(result["captured_at"], 0)
        self.assertNotIn("image", repr(result))
        self.assertNotIn("frame_labels", repr(result))
        self.assertTrue(api.get_capabilities()["work_collaboration_context"])
        self.assertTrue(api.get_capabilities()["shared_work"])

    async def test_work_context_masks_window_titles_and_summary(self) -> None:
        api = main.ScreenCompanionExtensionAPI(
            self._make_plugin(privacy_masked=True)
        )

        result = await api.get_work_collaboration_context()

        self.assertTrue(result["privacy_masked"])
        self.assertEqual("已脱敏 · Visual Studio Code", result["current"]["window"])
        self.assertEqual("Visual Studio Code", result["current"]["resource_label"])
        self.assertNotIn("Secret roadmap", repr(result))

    async def test_work_context_failure_does_not_escape_to_caller(self) -> None:
        def fail_window_read():
            raise RuntimeError("window access failed")

        plugin = self._make_plugin()
        plugin._get_active_window_info = fail_window_read
        api = main.ScreenCompanionExtensionAPI(plugin)

        result = await api.get_work_collaboration_context()

        self.assertTrue(result["available"])
        self.assertFalse(result["context_available"])
        self.assertEqual({}, result["current"])
        self.assertEqual({}, result["observation"])


class _FakeRemoteReceiver:
    """接收器替身：只暴露本次改造用到的只读探测属性。"""

    def __init__(
        self,
        *,
        system_stats: dict | None = None,
        window_title: str = "",
        has_screenshot: bool = True,
    ) -> None:
        self.latest_system_stats = dict(system_stats or {})
        self.latest_window_title = window_title
        self.has_screenshot = has_screenshot


def _make_remote_media_plugin(receiver):
    """构造一个只带远程分支所需字段的真实插件实例（不跑 Star 初始化）。"""
    plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
    plugin.remote_mode = True
    plugin._remote_receiver = receiver
    plugin.battery_threshold = 20
    plugin.memory_threshold = 80
    return plugin


class RemoteSystemStatusPromptTests(unittest.TestCase):
    """远程系统状态必须来自客户端统计，且缺失时不得回落服务器本机采样。"""

    def test_remote_stats_drive_high_load_prompt(self) -> None:
        plugin = _make_remote_media_plugin(
            _FakeRemoteReceiver(system_stats={"cpu_percent": 95, "memory_percent": 30})
        )

        prompt, high_load = plugin._get_system_status_prompt()

        self.assertTrue(high_load)
        self.assertIn("当前系统负载较高", prompt)

    def test_remote_low_battery_prompt(self) -> None:
        plugin = _make_remote_media_plugin(
            _FakeRemoteReceiver(
                system_stats={"cpu_percent": 5, "memory_percent": 20, "battery_percent": 8}
            )
        )

        prompt, high_load = plugin._get_system_status_prompt()

        self.assertFalse(high_load)
        self.assertIn("当前设备电量偏低", prompt)

    def test_remote_without_stats_does_not_fall_back_to_local_psutil(self) -> None:
        """按需截图默认不采样统计；此时必须完全不产生提示。"""
        plugin = _make_remote_media_plugin(_FakeRemoteReceiver(system_stats={}))

        with patch("psutil.cpu_percent") as cpu_mock:
            prompt, high_load = plugin._get_system_status_prompt()

        self.assertEqual("", prompt)
        self.assertFalse(high_load)
        cpu_mock.assert_not_called()

    def test_remote_without_receiver_does_not_probe_local_machine(self) -> None:
        plugin = _make_remote_media_plugin(None)

        with patch("psutil.cpu_percent") as cpu_mock:
            prompt, high_load = plugin._get_system_status_prompt()

        self.assertEqual("", prompt)
        self.assertFalse(high_load)
        cpu_mock.assert_not_called()

    def test_invalid_remote_stat_values_are_ignored(self) -> None:
        """缺字段、非数值和越界值都不能被当作可信数据。"""
        plugin = _make_remote_media_plugin(
            _FakeRemoteReceiver(
                system_stats={
                    "cpu_percent": "not-a-number",
                    "memory_percent": None,
                    "battery_percent": 500,
                }
            )
        )

        prompt, high_load = plugin._get_system_status_prompt()

        self.assertEqual("", prompt)
        self.assertFalse(high_load)

    def test_coerce_stat_percent_bounds(self) -> None:
        from astrbot_plugin_screen_companion.core.media import (
            ScreenCompanionMediaMixin,
        )

        coerce = ScreenCompanionMediaMixin._coerce_stat_percent

        self.assertEqual(42.5, coerce(42.5))
        self.assertEqual(0.0, coerce(0))
        self.assertEqual(100.0, coerce(100))
        self.assertIsNone(coerce(None))
        self.assertIsNone(coerce(True))
        self.assertIsNone(coerce("abc"))
        self.assertIsNone(coerce(-1))
        self.assertIsNone(coerce(101))
        self.assertIsNone(coerce(float("nan")))
        self.assertIsNone(coerce(float("inf")))


class RemoteActiveWindowSourceTests(unittest.TestCase):
    """远程活动窗口必须来自客户端帧，且不得读取服务器本机窗口。"""

    @staticmethod
    def _make_runtime_plugin(receiver, *, remote_mode: bool = True):
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = remote_mode
        plugin._remote_receiver = receiver
        return plugin

    @staticmethod
    def _forbid_local_window_api():
        """注入一个一被访问就报错的 pygetwindow，用于证明本机窗口未被读取。

        宿主机通常没有安装 pygetwindow，因此不能直接 patch 属性；
        这里显式注入替身，远程分支一旦触碰本机窗口查询就会立刻失败。
        """
        calls: list = []
        fake = SimpleNamespace(
            getActiveWindow=lambda: calls.append(True) or None,
        )
        return patch.dict("sys.modules", {"pygetwindow": fake}), calls

    def test_remote_mode_returns_client_window_title(self) -> None:
        plugin = self._make_runtime_plugin(
            _FakeRemoteReceiver(window_title="Visual Studio Code")
        )

        patcher, calls = self._forbid_local_window_api()
        with patcher:
            title, region = plugin._get_active_window_info()

        self.assertEqual("Visual Studio Code", title)
        self.assertIsNone(region)
        self.assertEqual([], calls)

    def test_remote_mode_without_frame_returns_empty_without_local_probe(self) -> None:
        plugin = self._make_runtime_plugin(
            _FakeRemoteReceiver(window_title="", has_screenshot=False)
        )

        patcher, calls = self._forbid_local_window_api()
        with patcher:
            title, region = plugin._get_active_window_info()

        self.assertEqual("", title)
        self.assertIsNone(region)
        self.assertEqual([], calls)

    def test_remote_mode_without_receiver_returns_empty(self) -> None:
        plugin = self._make_runtime_plugin(None)

        title, region = plugin._get_active_window_info()

        self.assertEqual("", title)
        self.assertIsNone(region)

    def test_local_mode_still_uses_local_window(self) -> None:
        """本地模式行为保持不变：依然读取本机窗口，不使用远程帧。"""
        plugin = self._make_runtime_plugin(
            _FakeRemoteReceiver(window_title="Remote Window"),
            remote_mode=False,
        )
        local_window = SimpleNamespace(
            title="Local Editor",
            left=10,
            top=20,
            width=800,
            height=600,
        )

        with (
            patch.dict(
                "sys.modules",
                {"pygetwindow": SimpleNamespace(getActiveWindow=lambda: local_window)},
            ),
            patch("sys.platform", "win32"),
        ):
            title, region = plugin._get_active_window_info()

        self.assertEqual("Local Editor", title)
        self.assertEqual((10, 20, 800, 600), region)
        self.assertNotEqual("Remote Window", title)


class ReceiverReadOnlyAccessorTests(unittest.TestCase):
    """接收器的只读探测不得触发采集。"""

    @staticmethod
    def _make_receiver(*, image: bytes, title: str, stats: dict | None):
        from astrbot_plugin_screen_companion.core.remote_receiver import (
            RemoteScreenReceiver,
        )

        receiver = RemoteScreenReceiver(auth_token="test-token")
        receiver._latest_image_bytes = image
        receiver._latest_window_title = title
        receiver._latest_timestamp = 1.0
        receiver._latest_meta = {"system_stats": dict(stats or {})}
        return receiver

    def test_accessors_expose_committed_frame(self) -> None:
        receiver = self._make_receiver(
            image=b"\xff\xd8\xff\xe0jpeg",
            title="Editor",
            stats={"cpu_percent": 12},
        )

        self.assertEqual("Editor", receiver.latest_window_title)
        self.assertEqual({"cpu_percent": 12}, receiver.latest_system_stats)

    def test_accessors_return_empty_without_frame(self) -> None:
        receiver = self._make_receiver(image=b"", title="Editor", stats={"cpu_percent": 12})

        self.assertEqual("", receiver.latest_window_title)
        self.assertEqual({}, receiver.latest_system_stats)

    def test_accessors_return_empty_for_non_dict_stats(self) -> None:
        receiver = self._make_receiver(image=b"\xff\xd8jpeg", title="", stats=None)
        receiver._latest_meta = {"system_stats": "broken"}

        self.assertEqual("", receiver.latest_window_title)
        self.assertEqual({}, receiver.latest_system_stats)


class RemoteLocalOnlyCollectorGuardTests(unittest.TestCase):
    """远程模式下不得采集服务器本机的键鼠、麦克风与浏览器历史。"""

    @staticmethod
    def _make_plugin(**flags):
        """构造一个具备运行时状态字段的真实插件实例（不跑 Star 初始化）。"""
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.learning_storage = tempfile.mkdtemp(prefix="sc_test_")
        plugin.enable_input_stats = False
        plugin.enable_mic_monitor = False
        plugin.running = True
        for name, value in flags.items():
            setattr(plugin, name, value)
        plugin._ensure_input_stats_state()
        return plugin

    def test_input_stats_listener_disabled_in_remote_mode(self) -> None:
        plugin = self._make_plugin(remote_mode=True, enable_input_stats=True)

        # 注入一个一被构造就报错的 pynput 替身：远程分支一旦触碰键盘监听即失败。
        constructed: list = []

        def _listener(**_kwargs):
            constructed.append(True)
            return SimpleNamespace(start=lambda: None, stop=lambda: None)

        with patch.dict(
            "sys.modules",
            {"pynput": SimpleNamespace(keyboard=SimpleNamespace(Listener=_listener))},
        ):
            started = plugin._ensure_input_stats_listener()

        self.assertFalse(started)
        self.assertEqual([], constructed)
        self.assertEqual("remote_unsupported", plugin._input_stats_status)
        self.assertIn("远程模式", plugin._input_stats_status_detail)

    def test_input_stats_listener_still_starts_in_local_mode(self) -> None:
        """本地模式不因本次改动而改变：仍会尝试启动监听。"""
        plugin = self._make_plugin(remote_mode=False, enable_input_stats=True)

        fake_listener = SimpleNamespace(start=lambda: None, stop=lambda: None)
        with patch.dict(
            "sys.modules",
            {
                "pynput": SimpleNamespace(
                    keyboard=SimpleNamespace(Listener=lambda **_: fake_listener)
                )
            },
        ):
            started = plugin._ensure_input_stats_listener()

        self.assertTrue(started)
        self.assertEqual("running", plugin._input_stats_status)

    def test_browser_history_candidates_empty_in_remote_mode(self) -> None:
        plugin = self._make_plugin(remote_mode=True)

        with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"}):
            candidates = plugin._get_local_browser_history_candidates()

        self.assertEqual([], candidates)

    def test_browser_history_candidates_not_forced_empty_in_local_mode(self) -> None:
        """本地模式不做远程拦截：候选列表由本机目录是否存在决定。"""
        plugin = self._make_plugin(remote_mode=False)

        with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\definitely\missing\path"}):
            candidates = plugin._get_local_browser_history_candidates()

        self.assertEqual([], candidates)

    def test_mic_monitor_not_started_in_remote_mode(self) -> None:
        plugin = self._make_plugin(remote_mode=True, enable_mic_monitor=True)

        with patch.object(plugin, "_safe_create_task") as create_mock:
            plugin._ensure_mic_monitor_background_task()

        create_mock.assert_not_called()
        self.assertIsNone(getattr(plugin, "_mic_monitor_background_task", None))


class RemoteActivityFrameStalenessTests(unittest.TestCase):
    """远程活动轨迹不得用过期帧无限延长同一条活动。"""

    @staticmethod
    def _make_plugin(age: float, *, max_age: int = 60, remote_mode: bool = True):
        receiver = _FakeRemoteReceiver()
        receiver.latest_age_seconds = age
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = remote_mode
        plugin._remote_receiver = receiver
        plugin.remote_screenshot_max_age = max_age
        return plugin

    def test_fresh_frame_is_not_stale(self) -> None:
        self.assertFalse(self._make_plugin(5.0)._remote_activity_frame_is_stale())

    def test_expired_frame_is_stale(self) -> None:
        self.assertTrue(self._make_plugin(600.0)._remote_activity_frame_is_stale())

    def test_missing_receiver_is_treated_as_stale(self) -> None:
        plugin = self._make_plugin(1.0)
        plugin._remote_receiver = None

        self.assertTrue(plugin._remote_activity_frame_is_stale())

    def test_infinite_and_nan_age_are_stale(self) -> None:
        self.assertTrue(
            self._make_plugin(float("inf"))._remote_activity_frame_is_stale()
        )
        self.assertTrue(
            self._make_plugin(float("nan"))._remote_activity_frame_is_stale()
        )

    def test_runtime_status_exposes_remote_staleness(self) -> None:
        plugin = self._make_plugin(600.0)
        plugin.enable_background_activity_tracking = True
        plugin.background_activity_tracking_interval = 15

        status = plugin._get_background_activity_tracking_runtime_status()

        self.assertTrue(status["remote_mode"])
        self.assertTrue(status["remote_frame_stale"])

    def test_runtime_status_marks_local_mode_as_not_remote(self) -> None:
        plugin = self._make_plugin(600.0, remote_mode=False)
        plugin.enable_background_activity_tracking = True
        plugin.background_activity_tracking_interval = 15

        status = plugin._get_background_activity_tracking_runtime_status()

        self.assertFalse(status["remote_mode"])
        self.assertFalse(status["remote_frame_stale"])


class RemoteRecordingEntryTests(unittest.IsolatedAsyncioTestCase):
    """手动录屏入口在远程模式下必须复用已上传录屏并如实标注来源。"""

    def _make_plugin(self, *, remote_mode: bool):
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = remote_mode
        return plugin

    async def test_remote_mode_reuses_uploaded_recording_and_labels_it(self) -> None:
        plugin = self._make_plugin(remote_mode=True)
        cached_calls: list = []
        one_shot_calls: list = []

        async def cached():
            cached_calls.append(True)
            return {
                "media_kind": "video",
                "media_bytes": b"video",
                "active_window_title": "Editor",
            }

        async def one_shot(_duration=None):
            one_shot_calls.append(True)
            return {"media_kind": "video", "media_bytes": b"fresh"}

        plugin._capture_recording_context = cached
        plugin._capture_one_shot_recording_context = one_shot

        context = await plugin._capture_command_recording_context()

        self.assertEqual([True], cached_calls)
        self.assertEqual([], one_shot_calls)
        self.assertTrue(context["remote_cached_recording"])
        self.assertIn("远程客户端最近上传的录屏", context["source_label"])
        self.assertIn("Editor", context["source_label"])

    async def test_local_mode_still_records_a_fresh_clip(self) -> None:
        plugin = self._make_plugin(remote_mode=False)
        one_shot_calls: list = []

        async def one_shot(duration=None):
            one_shot_calls.append(duration)
            return {"media_kind": "video", "media_bytes": b"fresh"}

        async def cached():  # pragma: no cover - 本地模式不应走到这里
            raise AssertionError("本地模式不应读取远程录屏缓存")

        plugin._capture_recording_context = cached
        plugin._capture_one_shot_recording_context = one_shot
        plugin._get_recording_duration_seconds = lambda: 10

        context = await plugin._capture_command_recording_context()

        self.assertEqual([10], one_shot_calls)
        self.assertNotIn("remote_cached_recording", context)

    async def test_remote_kpr_does_not_claim_it_is_recording_now(self) -> None:
        """/kpr 在远程模式不得提示"正在录制"，否则用户会以为画面是现拍的。"""
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = True
        plugin.debug = False
        plugin.running = True
        plugin._split_message = lambda text: [text]
        plugin._get_recording_duration_seconds = lambda: 10
        plugin._get_capture_context_timeout = lambda _kind=None: 60.0
        plugin._get_screen_analysis_timeout = lambda _kind=None: 120.0
        # /kpr 带 @admin_required，直接调用装饰器需要权限钩子。
        plugin._ensure_admin_permission = AsyncMock(return_value=True)
        # 环境检查要求远程接收服务正在运行，否则会在发消息前提前返回。
        running_receiver = _FakeRemoteReceiver()
        running_receiver.is_running = True
        plugin._remote_receiver = running_receiver

        async def command_recording():
            return {
                "media_kind": "video",
                "media_bytes": b"video",
                "source_label": "Editor（远程客户端最近上传的录屏）",
            }

        plugin._capture_command_recording_context = command_recording
        plugin._run_screen_assist = AsyncMock(return_value="看到了编辑器")

        replies: list = []

        class FakeEvent:
            unified_msg_origin = "napcat:FriendMessage:10001"

            def plain_result(self, text):
                replies.append(text)
                return text

        results = [item async for item in plugin.kpr(FakeEvent())]
        joined = "\n".join(str(item) for item in results)

        self.assertNotIn("开始录制", joined)
        self.assertIn("无法命令客户端立刻补录", joined)
        self.assertIn("最近上传的录屏", joined)
        plugin._run_screen_assist.assert_awaited_once()


class RemoteAutoScreenLoadSourceTests(unittest.TestCase):
    """自动观察的高负载判定在远程模式下必须用客户端统计，而不是服务器负载。"""

    def test_remote_high_load_comes_from_client_stats(self) -> None:
        plugin = _make_remote_media_plugin(
            _FakeRemoteReceiver(system_stats={"cpu_percent": 96, "memory_percent": 40})
        )

        with patch("psutil.cpu_percent") as cpu_mock:
            result = plugin._get_remote_system_status_prompt()

        self.assertIsNotNone(result)
        _prompt, high_load = result
        self.assertTrue(high_load)
        cpu_mock.assert_not_called()

    def test_remote_without_stats_reports_no_high_load(self) -> None:
        """没有客户端统计时必须返回 None，让调用方不触发高负载分支。"""
        plugin = _make_remote_media_plugin(_FakeRemoteReceiver(system_stats={}))

        with patch("psutil.cpu_percent") as cpu_mock:
            result = plugin._get_remote_system_status_prompt()

        self.assertIsNone(result)
        cpu_mock.assert_not_called()

    def test_remote_without_receiver_reports_no_high_load(self) -> None:
        plugin = _make_remote_media_plugin(None)

        self.assertIsNone(plugin._get_remote_system_status_prompt())


class RemoteOpenWindowListTests(unittest.TestCase):
    """远程模式下窗口列表不得来自服务器桌面。"""

    def test_remote_mode_returns_empty_without_touching_pygetwindow(self) -> None:
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = True

        # 注入一被调用就报错的替身：远程分支一旦读取本机窗口列表即失败。
        def _boom(*_args, **_kwargs):
            raise AssertionError("远程模式不应读取本机窗口列表")

        with patch.dict(
            "sys.modules",
            {
                "pygetwindow": SimpleNamespace(
                    getAllTitles=_boom, getAllWindows=_boom
                )
            },
        ):
            titles = plugin._list_open_window_titles()

        self.assertEqual([], titles)

    def test_local_mode_still_reads_window_titles(self) -> None:
        """本地模式行为保持不变：仍会读取并去重本机窗口标题。"""
        plugin = main.ScreenCompanion.__new__(main.ScreenCompanion)
        plugin.remote_mode = False
        plugin._normalize_window_title = lambda text: str(text or "").strip()

        with patch.dict(
            "sys.modules",
            {
                "pygetwindow": SimpleNamespace(
                    getAllTitles=lambda: ["Editor", "Editor", "  ", "Browser"]
                )
            },
        ):
            titles = plugin._list_open_window_titles()

        self.assertEqual(["Editor", "Browser"], titles)


if __name__ == "__main__":
    unittest.main()
