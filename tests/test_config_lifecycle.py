# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from astrbot.core.config.astrbot_config import AstrBotConfig

from astrbot_plugin_screen_companion.core.config import PluginConfig
from astrbot_plugin_screen_companion.core.media import ScreenCompanionMediaMixin
from astrbot_plugin_screen_companion.core.runtime import ScreenCompanionRuntimeMixin


class ConfigPersistenceTests(unittest.TestCase):
    def test_plugin_config_writes_and_verifies_new_lifecycle_setting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "plugin.json"
            config_path.write_text("{}", encoding="utf-8")
            data = AstrBotConfig(config_path=str(config_path), default_config={})
            config = PluginConfig(data)

            config.enable_start_end_messages = False

            persisted = json.loads(config_path.read_text(encoding="utf-8-sig"))
            self.assertFalse(persisted["enable_start_end_messages"])
            self.assertTrue(
                config.verify_persisted({"enable_start_end_messages": False})
            )


class LifecycleMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_lifecycle_messages_return_empty_text(self) -> None:
        plugin = ScreenCompanionMediaMixin()
        plugin.enable_start_end_messages = False
        plugin.use_llm_for_start_end = True

        self.assertEqual("", await plugin._get_start_response())
        self.assertEqual("", await plugin._get_end_response())


class AutoScreenRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unexpected_task_error_keeps_active_state_and_schedules_restart(self) -> None:
        class RecoveryHarness(ScreenCompanionRuntimeMixin, ScreenCompanionMediaMixin):
            pass

        plugin = RecoveryHarness()
        plugin.auto_tasks = {}
        plugin.is_running = True
        plugin.state = "active"
        plugin.running = True
        plugin.enabled = True
        plugin._instance_token = ""
        plugin.learning_storage = "."
        plugin._is_in_active_time_range = lambda: True

        def fail_before_first_cycle():
            raise RuntimeError("synthetic task failure")

        plugin._get_current_preset_params = fail_before_first_cycle
        task = asyncio.create_task(plugin._auto_screen_task(object(), task_id="task_0"))
        plugin.auto_tasks["task_0"] = task

        await task

        self.assertTrue(plugin.is_running)
        self.assertEqual("active", plugin.state)
        restart_task = plugin._auto_screen_restart_tasks.get("task_0")
        self.assertIsNotNone(restart_task)
        restart_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await restart_task


if __name__ == "__main__":
    unittest.main()
