# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import io
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any

from astrbot.api import logger

_PROCESS_GUARD_LOCK = threading.Lock()
_PROCESS_GUARDS: dict[str, float] = {}
_ACTIVE_INSTANCE_TOKEN = ""


class ScreenCompanionRuntimeMixin:
    @staticmethod
    def _safe_create_task(coro, *, name: str = "") -> asyncio.Task:
        """创建带异常兜底的后台任务。"""
        task = asyncio.create_task(coro, name=name or None)

        def _on_done(t: asyncio.Task):
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error(f"后台任务 '{t.get_name()}' 异常: {exc}", exc_info=exc)

        task.add_done_callback(_on_done)
        return task

    async def _cancel_tasks(self, tasks: list[asyncio.Task], label: str) -> None:
        """取消并等待一组后台任务退出。"""
        alive_tasks = [task for task in tasks if task and not task.done()]
        if not alive_tasks:
            return

        for task in alive_tasks:
            task.cancel()

        for task in alive_tasks:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"等待{label}停止超时")
            except asyncio.CancelledError:
                logger.info(f"{label} cancelled")
            except Exception as e:
                logger.error(f"等待{label}停止时出错: {e}")

    def _normalize_screen_recognition_mode(self, value: Any) -> str:
        if isinstance(value, bool):
            return self.RECORDING_MODE if value else self.SCREENSHOT_MODE

        if isinstance(value, str):
            mode = value.strip().lower()
            if mode in {self.RECORDING_MODE, "video", "true", "1", "yes", "on"}:
                return self.RECORDING_MODE
            if mode in {self.SCREENSHOT_MODE, "image", "false", "0", "no", "off"}:
                return self.SCREENSHOT_MODE

        return self.SCREENSHOT_MODE

    def _use_screen_recording_mode(self) -> bool:
        if self._get_runtime_flag("remote_mode"):
            return False
        return (
            self._normalize_screen_recognition_mode(
                getattr(self, "screen_recognition_mode", self.SCREENSHOT_MODE)
            )
            == self.RECORDING_MODE
        )

    @staticmethod
    def _normalize_clock_text(value: Any, default: str = "00:00") -> str:
        text = str(value or "").strip()
        if not text:
            return default
        try:
            hour_text, minute_text = text.split(":", 1)
            hour = int(hour_text)
            minute = int(minute_text)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        except Exception:
            pass
        return default

    @staticmethod
    def _resolve_diary_target_date(
        now: datetime.datetime | None = None,
        *,
        early_morning_cutoff_hour: int = 2,
    ) -> datetime.date:
        current = now or datetime.datetime.now()
        target_date = current.date()
        if current.hour < max(0, int(early_morning_cutoff_hour)):
            target_date -= datetime.timedelta(days=1)
        return target_date

    def _get_capture_context_timeout(self, media_kind: str | None = None) -> float:
        normalized_kind = str(media_kind or "").strip().lower()
        if not normalized_kind:
            normalized_kind = "video" if self._use_screen_recording_mode() else "image"
        if normalized_kind == "video":
            duration = self._get_recording_duration_seconds()
            return float(max(duration + 35, 60))
        return 20.0

    def _get_interaction_timeout(
        self, media_kind: str, use_external_vision: bool
    ) -> float:
        normalized_kind = str(media_kind or "image").strip().lower()
        if normalized_kind == "video":
            return 300.0 if use_external_vision else 360.0
        return 180.0 if use_external_vision else 240.0

    def _get_screen_analysis_timeout(
        self,
        media_kind: str,
        use_external_vision: bool | None = None,
    ) -> float:
        if use_external_vision is None:
            use_external_vision = self._get_runtime_flag("use_external_vision")
        interaction_timeout = self._get_interaction_timeout(
            media_kind,
            bool(use_external_vision),
        )
        base_timeout = 120.0 if str(media_kind or "image").strip().lower() == "video" else 45.0
        return interaction_timeout + base_timeout

    async def _handle_screen_recognition_mode_change(self) -> None:
        self._ensure_runtime_state()
        if self._use_screen_recording_mode():
            await self._ensure_recording_ready()
            return
        await self._stop_recording_if_running()

    def _ensure_runtime_state(self) -> None:
        if not hasattr(self, "auto_tasks") or self.auto_tasks is None:
            self.auto_tasks = {}
        if not hasattr(self, "temporary_tasks") or self.temporary_tasks is None:
            self.temporary_tasks = {}
        if not hasattr(self, "background_tasks") or self.background_tasks is None:
            self.background_tasks = []
        if not hasattr(self, "active_tasks") or self.active_tasks is None:
            self.active_tasks = {}
        if not hasattr(self, "last_task_execution") or self.last_task_execution is None:
            self.last_task_execution = {}
        if not hasattr(self, "task_counter"):
            self.task_counter = 0
        if not hasattr(self, "is_running"):
            self.is_running = False
        if not hasattr(self, "running"):
            self.running = True
        if not hasattr(self, "state"):
            self.state = "inactive"
        if not hasattr(self, "web_server"):
            self.web_server = None
        if not hasattr(self, "task_semaphore") or self.task_semaphore is None:
            self.task_semaphore = asyncio.Semaphore(2)
        if not hasattr(self, "task_queue") or self.task_queue is None:
            self.task_queue = asyncio.Queue()
        if not hasattr(self, "_shutdown_lock") or self._shutdown_lock is None:
            self._shutdown_lock = asyncio.Lock()
        if not hasattr(self, "_webui_lock") or self._webui_lock is None:
            self._webui_lock = asyncio.Lock()
        if not hasattr(self, "_is_stopping"):
            self._is_stopping = False
        if not hasattr(self, "_screen_assist_cooldowns") or self._screen_assist_cooldowns is None:
            self._screen_assist_cooldowns = {}
        if not hasattr(self, "last_shared_activity_invite_time"):
            self.last_shared_activity_invite_time = 0.0
        if not hasattr(self, "previous_windows") or self.previous_windows is None:
            self.previous_windows = set()
        if not hasattr(self, "window_change_cooldown"):
            self.window_change_cooldown = 0
        if not hasattr(self, "window_timestamps") or self.window_timestamps is None:
            self.window_timestamps = {}
        if not hasattr(self, "auto_screen_runtime") or self.auto_screen_runtime is None:
            self.auto_screen_runtime = {}
        if not hasattr(self, "recent_user_activity") or self.recent_user_activity is None:
            self.recent_user_activity = {}
        if not hasattr(self, "screen_analysis_traces") or self.screen_analysis_traces is None:
            self.screen_analysis_traces = []
        if not hasattr(self, "current_activity_source"):
            self.current_activity_source = ""
        if not hasattr(self, "input_stats_daily") or self.input_stats_daily is None:
            self.input_stats_daily = {}
        if not hasattr(self, "_learning_runtime_state") or self._learning_runtime_state is None:
            self._learning_runtime_state = {}
        if not hasattr(self, "_instance_token"):
            self._instance_token = ""
        if not hasattr(self, "_screen_analysis_failure_count"):
            self._screen_analysis_failure_count = 0
        if not hasattr(self, "_screen_analysis_backoff_until"):
            self._screen_analysis_backoff_until = 0.0
        if not hasattr(self, "window_companion_active_title"):
            self.window_companion_active_title = ""
        if not hasattr(self, "window_companion_active_target"):
            self.window_companion_active_target = ""
        if not hasattr(self, "window_companion_active_rule") or self.window_companion_active_rule is None:
            self.window_companion_active_rule = {}
        if not hasattr(self, "window_companion_missing_since"):
            self.window_companion_missing_since = 0.0
        if not hasattr(self, "last_rest_reminder_time"):
            self.last_rest_reminder_time = None
        if not hasattr(self, "last_rest_reminder_day"):
            self.last_rest_reminder_day = ""
        if not hasattr(self, "rest_reminder_state_file"):
            self.rest_reminder_state_file = os.path.join(
                self.learning_storage,
                "rest_reminder_state.json",
            )
        if not hasattr(self, "input_stats_file"):
            self.input_stats_file = os.path.join(
                self.learning_storage,
                "input_stats_daily.json",
            )
        if not hasattr(self, "_input_stats_lock") or self._input_stats_lock is None:
            import threading

            self._input_stats_lock = threading.Lock()
        if not hasattr(self, "_input_stats_dirty"):
            self._input_stats_dirty = False
        if not hasattr(self, "_input_stats_listeners") or self._input_stats_listeners is None:
            self._input_stats_listeners = []
        if not hasattr(self, "_input_stats_status"):
            self._input_stats_status = "disabled"
        if not hasattr(self, "_input_stats_status_detail"):
            self._input_stats_status_detail = "未启用本地输入统计"
        if not hasattr(self, "_input_stats_last_flush_time"):
            self._input_stats_last_flush_time = 0.0
        if not hasattr(self, "_input_stats_last_move_time"):
            self._input_stats_last_move_time = 0.0
        if not hasattr(self, "_input_stats_last_mouse_position"):
            self._input_stats_last_mouse_position = None
        if not hasattr(self, "_input_stats_last_event_at"):
            self._input_stats_last_event_at = ""
        if not hasattr(self, "_away_pause_runtime_state") or self._away_pause_runtime_state is None:
            self._away_pause_runtime_state = {}
        self._ensure_recording_runtime_state()

    def _ensure_recording_runtime_state(self) -> None:
        if not hasattr(self, "_screen_recording_lock") or self._screen_recording_lock is None:
            self._screen_recording_lock = asyncio.Lock()
        if not hasattr(self, "_screen_recording_process"):
            self._screen_recording_process = None
        if not hasattr(self, "_screen_recording_path"):
            self._screen_recording_path = ""
        if not hasattr(self, "_recording_audio_device"):
            self._recording_audio_device = None
        if not hasattr(self, "_recording_ffmpeg_path"):
            self._recording_ffmpeg_path = None
        if not hasattr(self, "_recording_video_encoder"):
            self._recording_video_encoder = None
        if not hasattr(self, "_recording_video_encoder_source"):
            self._recording_video_encoder_source = ""

    def _remember_learning_runtime_event(
        self,
        channel: str,
        status: str,
        detail: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_runtime_state()
        normalized_channel = str(channel or "").strip()
        if not normalized_channel:
            return

        state = getattr(self, "_learning_runtime_state", None)
        if not isinstance(state, dict):
            state = {}
            self._learning_runtime_state = state

        state[normalized_channel] = {
            "status": str(status or "").strip(),
            "detail": str(detail or "").strip(),
            "timestamp": time.time(),
            "extra": dict(extra or {}),
        }

    def _get_learning_runtime_events(self) -> dict[str, dict[str, Any]]:
        self._ensure_runtime_state()
        state = getattr(self, "_learning_runtime_state", None)
        return state if isinstance(state, dict) else {}

    def _register_process_instance(self) -> None:
        global _ACTIVE_INSTANCE_TOKEN
        token = uuid.uuid4().hex
        with _PROCESS_GUARD_LOCK:
            _ACTIVE_INSTANCE_TOKEN = token
        self._instance_token = token

    def _is_current_process_instance(self) -> bool:
        token = str(getattr(self, "_instance_token", "") or "").strip()
        if not token:
            return True
        with _PROCESS_GUARD_LOCK:
            return _ACTIVE_INSTANCE_TOKEN == token

    def _cleanup_legacy_default_custom_tasks(self) -> None:
        legacy_value = self.LEGACY_DEFAULT_CUSTOM_TASK.strip()
        current_value = str(getattr(self, "custom_tasks", "") or "").strip()
        if current_value != legacy_value:
            return

        logger.info("检测到旧版默认自定义监控任务，已自动清理")
        self.custom_tasks = ""
        try:
            self.plugin_config.custom_tasks = ""
        except Exception:
            pass

    def _try_enter_process_guard(
        self,
        guard_key: str,
        *,
        stale_seconds: float,
    ) -> bool:
        now_ts = time.time()
        with _PROCESS_GUARD_LOCK:
            expired_keys = [
                key
                for key, started_at in _PROCESS_GUARDS.items()
                if (now_ts - float(started_at or 0.0)) >= stale_seconds
            ]
            for key in expired_keys:
                _PROCESS_GUARDS.pop(key, None)
            if guard_key in _PROCESS_GUARDS:
                return False
            _PROCESS_GUARDS[guard_key] = now_ts
            return True

    def _leave_process_guard(self, guard_key: str) -> None:
        with _PROCESS_GUARD_LOCK:
            _PROCESS_GUARDS.pop(guard_key, None)

    def _try_mark_custom_task_dispatch(self, task_key: str) -> bool:
        return self._try_enter_process_guard(
            f"custom_task_dispatch:{task_key}",
            stale_seconds=self.CUSTOM_TASK_PROCESS_DEDUP_SECONDS,
        )

    def _get_screen_analysis_backoff_remaining(self) -> float:
        self._ensure_runtime_state()
        backoff_until = float(getattr(self, "_screen_analysis_backoff_until", 0.0) or 0.0)
        return max(0.0, backoff_until - time.time())

    def _record_screen_analysis_result(self, ok: bool, *, error_type: str = "") -> None:
        self._ensure_runtime_state()
        if ok:
            self._screen_analysis_failure_count = 0
            self._screen_analysis_backoff_until = 0.0
            return

        normalized_error_type = str(error_type or "").strip().lower()
        if normalized_error_type not in {"api", "timeout"}:
            return

        failure_count = int(getattr(self, "_screen_analysis_failure_count", 0) or 0) + 1
        self._screen_analysis_failure_count = failure_count
        backoff_seconds = min(
            self.SCREEN_ANALYSIS_FAILURE_BACKOFF_MAX_SECONDS,
            self.SCREEN_ANALYSIS_FAILURE_BACKOFF_BASE_SECONDS * (2 ** max(0, failure_count - 1)),
        )
        self._screen_analysis_backoff_until = time.time() + backoff_seconds
        logger.warning(
            f"识屏链路连续失败，进入退避 {backoff_seconds} 秒: error_type={normalized_error_type}, "
            f"failure_count={failure_count}"
        )

    def _try_begin_background_screen_job(self) -> tuple[bool, str]:
        remaining = self._get_screen_analysis_backoff_remaining()
        if remaining > 0:
            return False, f"识屏链路退避中，约 {max(1, int(remaining))} 秒后再试"

        acquired = self._try_enter_process_guard(
            "background_screen_job",
            stale_seconds=self.BACKGROUND_SCREEN_GUARD_STALE_SECONDS,
        )
        if not acquired:
            return False, "已有后台识屏任务正在执行"
        return True, ""

    def _finish_background_screen_job(self) -> None:
        self._leave_process_guard("background_screen_job")

    def _get_recording_fps(self) -> float:
        return max(0.01, float(getattr(self, "recording_fps", self.RECORDING_FPS) or self.RECORDING_FPS))

    def _get_recording_duration_seconds(self) -> int:
        return max(
            1,
            int(
                getattr(
                    self,
                    "recording_duration_seconds",
                    self.RECORDING_DURATION_SECONDS,
                )
                or self.RECORDING_DURATION_SECONDS
            ),
        )

    def _get_ffmpeg_path(self) -> str:
        self._ensure_recording_runtime_state()
        cached_path = getattr(self, "_recording_ffmpeg_path", None)
        if cached_path and os.path.exists(cached_path):
            return cached_path

        candidate_paths: list[str] = []

        configured_path = str(getattr(self, "ffmpeg_path", "") or "").strip()
        if configured_path:
            candidate_paths.append(configured_path)

        data_ffmpeg_dir = self._get_ffmpeg_storage_dir()
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        candidate_paths.extend(
            [
                os.path.join(data_ffmpeg_dir, "ffmpeg.exe"),
                os.path.join(data_ffmpeg_dir, "ffmpeg"),
                os.path.join(plugin_dir, "bin", "ffmpeg.exe"),
                os.path.join(plugin_dir, "bin", "ffmpeg"),
                os.path.join(plugin_dir, "ffmpeg.exe"),
                os.path.join(plugin_dir, "ffmpeg"),
            ]
        )

        for candidate in candidate_paths:
            normalized = os.path.abspath(os.path.expanduser(candidate))
            if os.path.isfile(normalized):
                self._recording_ffmpeg_path = normalized
                return normalized

        ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or ""
        self._recording_ffmpeg_path = ffmpeg_path or None
        return ffmpeg_path

    def _get_ffmpeg_storage_dir(self, create: bool = False) -> str:
        data_dir = str(getattr(self.plugin_config, "data_dir", "") or "").strip()
        if data_dir:
            ffmpeg_dir = os.path.join(data_dir, "bin")
        else:
            ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
        if create:
            os.makedirs(ffmpeg_dir, exist_ok=True)
        return ffmpeg_dir

    def _get_recording_video_encoder(self) -> str:
        self._ensure_recording_runtime_state()
        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            return "libx264"

        cached_encoder = str(getattr(self, "_recording_video_encoder", "") or "").strip()
        cached_source = str(getattr(self, "_recording_video_encoder_source", "") or "").strip()
        if cached_encoder and cached_source == ffmpeg_path:
            return cached_encoder

        encoder = "mpeg4"
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=12,
                creationflags=creationflags,
            )
            output = "\n".join(
                piece for piece in [result.stdout or "", result.stderr or ""] if piece
            )
            if "libx264" in output:
                encoder = "libx264"
        except Exception as e:
            logger.debug(f"检测 ffmpeg 编码器失败，将使用兼容编码器: {e}")

        self._recording_video_encoder = encoder
        self._recording_video_encoder_source = ffmpeg_path
        return encoder

    def _build_recording_video_args(self) -> list[str]:
        encoder = self._get_recording_video_encoder()
        args = ["-c:v", encoder]
        if encoder == "libx264":
            args.extend(["-preset", "ultrafast", "-crf", "32"])
        else:
            args.extend(["-q:v", "7"])
        args.extend(["-pix_fmt", "yuv420p"])
        return args

    def _is_recording_platform_supported(self) -> bool:
        return sys.platform == "win32" or sys.platform == "darwin"

    def _unsupported_recording_platform_message(self) -> str:
        return "录屏视频识别目前支持 Windows 和 macOS 桌面环境。"

    def _get_ffmpeg_missing_message(self) -> str:
        if sys.platform == "win32":
            return (
                "未检测到 ffmpeg。请将 ffmpeg.exe 放到插件数据目录下的 bin 文件夹，"
                "或在配置中填写 ffmpeg_path，或加入系统 PATH。"
            )
        if sys.platform == "darwin":
            return "未检测到 ffmpeg。请先执行 brew install ffmpeg，或在配置中填写 ffmpeg_path。"
        return "未检测到 ffmpeg。请先安装 ffmpeg，或在配置中填写 ffmpeg_path。"

    def _detect_macos_screen_device(self) -> str:
        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            return "1"

        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
            )
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
        except Exception as e:
            logger.debug(f"检测 macOS 屏幕录制设备失败，将使用默认设备: {e}")
            return "1"

        in_video_section = False
        for raw_line in output.splitlines():
            line = raw_line.strip()
            lower = line.lower()
            if "avfoundation video devices" in lower:
                in_video_section = True
                continue
            if "avfoundation audio devices" in lower:
                in_video_section = False
                continue
            if not in_video_section:
                continue
            if "capture screen" not in lower and "screen" not in lower:
                continue

            import re

            match = re.search(r"\[(\d+)\]", line)
            if match:
                device = match.group(1)
                logger.info(f"检测到 macOS 屏幕录制设备: {line}")
                return device

        logger.info("未能从 avfoundation 设备列表中匹配屏幕设备，将使用默认设备 1")
        return "1"

    def _build_recording_input_args(self) -> list[str]:
        fps = str(self._get_recording_fps())
        if sys.platform == "win32":
            args = [
                "-f",
                "gdigrab",
                "-framerate",
                fps,
                "-i",
                "desktop",
            ]
            audio_device = self._detect_system_audio_device()
            if audio_device:
                args.extend(
                    [
                        "-f",
                        "dshow",
                        "-i",
                        f"audio={audio_device}",
                        "-shortest",
                    ]
                )
            return args

        if sys.platform == "darwin":
            screen_device = self._detect_macos_screen_device()
            return [
                "-f",
                "avfoundation",
                "-framerate",
                fps,
                "-capture_cursor",
                "1",
                "-i",
                f"{screen_device}:none",
            ]

        raise RuntimeError(self._unsupported_recording_platform_message())

    @staticmethod
    def _build_evenly_spaced_indices(total_count: int, sample_count: int) -> list[int]:
        total = max(0, int(total_count or 0))
        target = max(1, int(sample_count or 1))
        if total <= 0:
            return []
        if total <= target:
            return list(range(total))
        if target == 1:
            return [total // 2]

        last_index = total - 1
        indices = []
        for position in range(target):
            ratio = position / max(1, target - 1)
            indices.append(int(round(last_index * ratio)))
        return sorted(set(max(0, min(last_index, value)) for value in indices))

    @staticmethod
    def _build_sample_frame_labels(total_count: int, chosen_indices: list[int]) -> list[str]:
        if not chosen_indices:
            return []
        if len(chosen_indices) == 1:
            return ["中段"]
        if len(chosen_indices) == 2:
            return ["开头", "结尾"]
        if len(chosen_indices) == 3:
            return ["开头", "中段", "结尾"]

        labels = []
        last_index = max(1, int(total_count) - 1)
        for index, frame_index in enumerate(chosen_indices):
            if index == 0:
                labels.append("开头")
                continue
            if index == len(chosen_indices) - 1:
                labels.append("结尾")
                continue
            percent = int(round((frame_index / last_index) * 100))
            labels.append(f"{percent}%")
        return labels

    def _get_video_sampling_plan(
        self,
        scene: str,
        *,
        duration_seconds: int,
        use_external_vision: bool,
    ) -> dict[str, Any]:
        normalized_duration = max(1, int(duration_seconds or self._get_recording_duration_seconds()))
        profile = self._get_scene_behavior_profile(scene)
        category = str(profile.get("category", "general") or "general")

        if normalized_duration <= 8:
            sample_count = 3
        elif normalized_duration <= 15:
            sample_count = 4
        elif normalized_duration <= 25:
            sample_count = 5
        else:
            sample_count = 6

        if category == "entertainment":
            sample_count = min(6, sample_count + 1)
        elif category == "work":
            sample_count = max(3, sample_count - 1)

        if use_external_vision:
            sample_count = max(sample_count, 4)

        if sample_count <= 3:
            sampling_strategy = "keyframe_sheet"
        elif category == "entertainment":
            sampling_strategy = "timeline_sheet_dense"
        elif category == "work":
            sampling_strategy = "timeline_sheet_compact"
        else:
            sampling_strategy = "timeline_sheet"

        return {
            "sample_count": sample_count,
            "sampling_strategy": sampling_strategy,
            "duration_seconds": normalized_duration,
            "scene_category": category,
        }

    def _extract_video_sample_sheet_sync(
        self,
        video_bytes: bytes,
        *,
        sample_count: int = 3,
        sampling_strategy: str = "keyframe_sheet",
        latest_frame_bytes: bytes | None = None,
    ) -> dict[str, Any] | None:
        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path or not video_bytes:
            return None

        from PIL import Image, ImageDraw, ImageFont

        with tempfile.TemporaryDirectory(prefix="screen_companion_sample_") as temp_dir:
            input_path = os.path.join(temp_dir, "input.mp4")
            with open(input_path, "wb") as f:
                f.write(video_bytes)

            frame_pattern = os.path.join(temp_dir, "frame_%03d.jpg")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    input_path,
                    "-vf",
                    "fps=1",
                    frame_pattern,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=20,
                creationflags=creationflags,
            )
            if result.returncode != 0:
                return None

            frame_paths = sorted(
                os.path.join(temp_dir, filename)
                for filename in os.listdir(temp_dir)
                if filename.startswith("frame_") and filename.endswith(".jpg")
            )
            if not frame_paths:
                return None

            chosen_indices = self._build_evenly_spaced_indices(
                len(frame_paths),
                sample_count,
            )
            chosen_paths = [frame_paths[index] for index in chosen_indices]
            frame_labels = self._build_sample_frame_labels(len(frame_paths), chosen_indices)
            frames = []
            for index, frame_path in enumerate(chosen_paths):
                with Image.open(frame_path) as image:
                    frame = image.convert("RGB")
                    label = frame_labels[min(index, len(frame_labels) - 1)]
                    frames.append((label, frame.copy()))

            has_live_anchor_frame = False
            if latest_frame_bytes:
                try:
                    with Image.open(io.BytesIO(latest_frame_bytes)) as latest_image:
                        frames.append(("现在", latest_image.convert("RGB").copy()))
                        has_live_anchor_frame = True
                except Exception:
                    has_live_anchor_frame = False

            if not frames:
                return None

            target_width = min(960, max(frame.width for _, frame in frames))
            padding = 18
            gap = 12
            label_height = 34
            resized_frames = []
            for label, frame in frames:
                scale = target_width / max(1, frame.width)
                target_height = max(1, int(frame.height * scale))
                resized_frames.append(
                    (
                        label,
                        frame.resize((target_width, target_height)),
                    )
                )

            total_height = padding * 2 + sum(frame.height + label_height for _, frame in resized_frames) + gap * max(0, len(resized_frames) - 1)
            canvas = Image.new("RGB", (target_width + padding * 2, total_height), "#111418")
            draw = ImageDraw.Draw(canvas)
            try:
                font = ImageFont.truetype("msyh.ttc", 18)
            except Exception:
                font = ImageFont.load_default()

            current_y = padding
            for label, frame in resized_frames:
                draw.rounded_rectangle(
                    (padding, current_y, padding + target_width, current_y + label_height - 8),
                    radius=10,
                    fill="#1d232c",
                )
                draw.text(
                    (padding + 12, current_y + 5),
                    f"{label}关键帧",
                    fill="#f4f7fb",
                    font=font,
                )
                current_y += label_height
                canvas.paste(frame, (padding, current_y))
                current_y += frame.height + gap

            buffer = io.BytesIO()
            canvas.save(buffer, format="JPEG", quality=86)
            return {
                "media_kind": "image",
                "mime_type": "image/jpeg",
                "media_bytes": buffer.getvalue(),
                "frame_count": len(resized_frames),
                "frame_labels": [label for label, _ in resized_frames],
                "sampling_strategy": sampling_strategy,
                "has_live_anchor_frame": has_live_anchor_frame,
            }

    async def _build_video_sample_capture_context(
        self,
        capture_context: dict[str, Any],
        *,
        scene: str,
        use_external_vision: bool,
    ) -> dict[str, Any] | None:
        media_bytes = capture_context.get("media_bytes", b"") or b""
        duration_seconds = int(
            capture_context.get("duration_seconds", 0) or self._get_recording_duration_seconds()
        )
        sampling_plan = self._get_video_sampling_plan(
            scene,
            duration_seconds=duration_seconds,
            use_external_vision=use_external_vision,
        )
        sample_sheet = await asyncio.to_thread(
            self._extract_video_sample_sheet_sync,
            media_bytes,
            sample_count=int(sampling_plan.get("sample_count", 3) or 3),
            sampling_strategy=str(
                sampling_plan.get("sampling_strategy", "keyframe_sheet") or "keyframe_sheet"
            ),
            latest_frame_bytes=capture_context.get("latest_image_bytes", b"") or None,
        )
        if not sample_sheet:
            return None

        return {
            "media_kind": "image",
            "mime_type": sample_sheet["mime_type"],
            "media_bytes": sample_sheet["media_bytes"],
            "active_window_title": capture_context.get("active_window_title", ""),
            "source_label": "录屏关键帧拼图",
            "sampling_strategy": sample_sheet.get("sampling_strategy", "keyframe_sheet"),
            "frame_count": sample_sheet.get("frame_count", 0),
            "frame_labels": sample_sheet.get("frame_labels", []),
            "has_live_anchor_frame": bool(sample_sheet.get("has_live_anchor_frame")),
            "duration_seconds": duration_seconds,
            "original_media_kind": "video",
        }

    def _should_keep_sampled_video_only(
        self,
        scene: str,
        *,
        use_external_vision: bool,
        preserve_full_video_for_audio: bool = False,
    ) -> bool:
        if preserve_full_video_for_audio:
            return False
        profile = self._get_scene_behavior_profile(scene)
        if use_external_vision:
            return True
        return bool(profile.get("prefer_sample_only", False))

    def _looks_uncertain_screen_result(self, text: str) -> bool:
        normalized = self._normalize_record_text(text)
        if not normalized or self._is_low_value_record_text(normalized):
            return True
        uncertain_markers = (
            "看不清",
            "不确定",
            "无法判断",
            "信息不足",
            "可能",
            "似乎",
        )
        return any(marker in str(text or "") for marker in uncertain_markers)

    def _get_recording_cache_dir(self) -> str:
        cache_dir = os.path.join(str(self.plugin_config.data_dir), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _detect_system_audio_device(self) -> str | None:
        if sys.platform != "win32":
            return None
        if self._recording_audio_device is not None:
            return self._recording_audio_device

        import re

        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            self._recording_audio_device = ""
            return self._recording_audio_device

        cmd = [
            ffmpeg_path,
            "-hide_banner",
            "-list_devices",
            "true",
            "-f",
            "dshow",
            "-i",
            "dummy",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=10,
                creationflags=creationflags,
            )
            output = f"{result.stdout or ''}\n{result.stderr or ''}"
        except Exception as e:
            logger.debug(f"检测系统音频设备失败: {e}")
            self._recording_audio_device = ""
            return self._recording_audio_device

        keywords = ("立体声混音", "stereo mix", "realtek")
        matched_devices: list[str] = []
        for line in output.splitlines():
            lower_line = line.lower()
            if not any(keyword in lower_line for keyword in keywords):
                continue
            match = re.search(r'"([^"]+)"', line)
            if match:
                matched_devices.append(match.group(1))

        self._recording_audio_device = matched_devices[0] if matched_devices else ""
        if self._recording_audio_device:
            logger.info(f"检测到系统音频设备: {self._recording_audio_device}")
        else:
            logger.info("未检测到可用的系统音频设备，将仅录制桌面画面")
        return self._recording_audio_device

    def _cleanup_recording_cache(self, keep_latest: int = 3) -> None:
        try:
            cache_dir = self._get_recording_cache_dir()
            candidates = []
            for filename in os.listdir(cache_dir):
                if not filename.startswith("rec_") or not filename.endswith(".mp4"):
                    continue
                path = os.path.join(cache_dir, filename)
                try:
                    candidates.append((os.path.getmtime(path), path))
                except OSError:
                    continue
            candidates.sort(key=lambda item: item[0], reverse=True)
            for _, path in candidates[keep_latest:]:
                try:
                    os.remove(path)
                except OSError:
                    pass
        except Exception as e:
            logger.debug(f"清理录屏缓存失败: {e}")

    def _record_screen_clip_sync(self, duration_seconds: int) -> str:
        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            raise RuntimeError(self._get_ffmpeg_missing_message())
        if not self._is_recording_platform_supported():
            raise RuntimeError(self._unsupported_recording_platform_message())

        duration = max(1, int(duration_seconds or self._get_recording_duration_seconds()))
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        clip_name = f"manual_rec_{timestamp}_{secrets.token_hex(4)}.mp4"
        output_path = os.path.join(self._get_recording_cache_dir(), clip_name)
        cmd = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        cmd.extend(self._build_recording_input_args())
        cmd.extend(
            [
                "-t",
                str(duration),
            ]
        )
        cmd.extend(self._build_recording_video_args())
        cmd.append(output_path)

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=max(duration + 30, 45),
            creationflags=creationflags,
        )
        if result.returncode != 0:
            stderr_text = (result.stderr or "").strip()
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            raise RuntimeError(
                "\u5355\u6b21\u5f55\u5c4f\u5931\u8d25\uff0cffmpeg \u5df2\u9000\u51fa\u3002"
                + (f" stderr: {stderr_text[:300]}" if stderr_text else "")
            )
        return output_path

    def _start_screen_recording_sync(self) -> str:
        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            raise RuntimeError(self._get_ffmpeg_missing_message())
        if not self._is_recording_platform_supported():
            raise RuntimeError(self._unsupported_recording_platform_message())

        process = getattr(self, "_screen_recording_process", None)
        if process and process.poll() is None:
            return str(getattr(self, "_screen_recording_path", "") or "")

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(self._get_recording_cache_dir(), f"rec_{timestamp}.mp4")
        cmd = [
            ffmpeg_path,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        cmd.extend(self._build_recording_input_args())
        cmd.extend(
            [
                "-t",
                str(self._get_recording_duration_seconds()),
            ]
        )
        cmd.extend(self._build_recording_video_args())
        cmd.append(output_path)

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._screen_recording_process = process
        self._screen_recording_path = output_path
        self._cleanup_recording_cache()
        logger.info(f"已启动桌面录屏: {output_path}")
        return output_path

    def _stop_screen_recording_sync(self) -> str:
        process = getattr(self, "_screen_recording_process", None)
        output_path = str(getattr(self, "_screen_recording_path", "") or "")
        self._screen_recording_process = None
        self._screen_recording_path = ""

        if process and process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
            except Exception:
                pass

            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

        return output_path

    async def _ensure_recording_ready(self) -> None:
        self._ensure_recording_runtime_state()
        async with self._screen_recording_lock:
            await asyncio.to_thread(self._start_screen_recording_sync)

    async def _stop_recording_if_running(self) -> None:
        self._ensure_recording_runtime_state()
        async with self._screen_recording_lock:
            await asyncio.to_thread(self._stop_screen_recording_sync)

    def _get_active_window_info(self) -> tuple[str, tuple[int, int, int, int] | None]:
        title = ""
        region = None
        if sys.platform != "win32":
            return title, region

        try:
            import pygetwindow

            active_window = pygetwindow.getActiveWindow()
            if not active_window:
                return title, region

            title = str(active_window.title or "").strip()
            left = int(getattr(active_window, "left", 0) or 0)
            top = int(getattr(active_window, "top", 0) or 0)
            width = int(getattr(active_window, "width", 0) or 0)
            height = int(getattr(active_window, "height", 0) or 0)
            if width > 20 and height > 20:
                region = (left, top, width, height)
        except Exception as e:
            logger.debug(f"获取活动窗口信息失败: {e}")

        return title, region
