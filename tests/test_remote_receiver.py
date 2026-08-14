# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from astrbot_plugin_screen_companion.core.media import ScreenCompanionMediaMixin
from astrbot_plugin_screen_companion.core.remote_receiver import RemoteScreenReceiver


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


class RemoteReceiverTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual("binary_screenshot_received", websocket.sent[-1]["status"])
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


class MediaRoutingTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_remote_recording_context_uses_completed_video_upload(self) -> None:
        receiver = SimpleNamespace(
            is_running=True,
            latest_video_age_seconds=0.1,
            get_latest_video=AsyncMock(
                return_value=(
                    b"mp4",
                    {"mime_type": "video/mp4", "window_title": "Player"},
                )
            ),
            get_latest_screenshot=AsyncMock(
                return_value=(b"\xff\xd8x\xff\xd9", "Player", {})
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


if __name__ == "__main__":
    unittest.main()
