# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from astrbot_plugin_screen_companion import main


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


if __name__ == "__main__":
    unittest.main()
