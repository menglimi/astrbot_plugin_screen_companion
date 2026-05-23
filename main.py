import asyncio
import datetime
import functools
import inspect
import os
import re
import shutil
import time
from typing import Any

DEFAULT_SYSTEM_PROMPT = """
你是一个会陪用户一起看屏幕、一起推进当下任务的屏幕伙伴。
请自然、克制、具体地回应用户，优先给当前任务真正有帮助的观察、判断和建议，避免机械播报和空泛说教。
当文字上下文不足以判断当前屏幕或近期电脑使用情况时，你可以按需调用可用工具先确认；只在真的需要时再调用，不要每轮都窥屏或查记录。
"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from .core.config import PluginConfig
from .core.proactive import ScreenCompanionProactiveMixin
from .core.runtime import ScreenCompanionRuntimeMixin
from .core.memory import ScreenCompanionMemoryMixin
from .core.media import ScreenCompanionMediaMixin
from .core.input_stats import ScreenCompanionInputStatsMixin
from .core.command_support import ScreenCompanionCommandSupportMixin

_screen_companion_tool_plugin = None


def admin_required(func):
    if inspect.isasyncgenfunction(func):
        @functools.wraps(func)
        async def asyncgen_wrapper(self, event: AstrMessageEvent, *args, **kwargs):
            if not await self._ensure_admin_permission(event):
                return
            async for item in func(self, event, *args, **kwargs):
                yield item

        return asyncgen_wrapper

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(self, event: AstrMessageEvent, *args, **kwargs):
            if not await self._ensure_admin_permission(event):
                return
            return await func(self, event, *args, **kwargs)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(self, event: AstrMessageEvent, *args, **kwargs):
        if not self._has_admin_permission(event):
            return None
        return func(self, event, *args, **kwargs)

    return sync_wrapper


def _get_tool_event(context: Any) -> AstrMessageEvent | None:
    try:
        agent_ctx = getattr(context, "context", None)
        event = getattr(agent_ctx, "event", None) if agent_ctx else None
        if event is None and agent_ctx is not None:
            event = getattr(getattr(agent_ctx, "context", None), "event", None)
        return event
    except Exception:
        return None


def _extract_plain_text(components: Any) -> str:
    if not isinstance(components, list):
        return ""
    for component in components:
        text = str(getattr(component, "text", "") or "").strip()
        if text:
            return text
    return ""


@dataclass
class ScreenPeekTool(FunctionTool[AstrAgentContext]):
    name: str = "screen_peek"
    description: str = (
        "当你需要确认用户当前屏幕上正在做什么、界面里具体出现了什么、"
        "或需要基于当前画面给出判断时使用。只在当前消息和对话上下文不足时调用。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "这次想通过窥屏确认的重点，可留空，例如“确认当前在做什么”或“看看报错/界面重点”。",
                },
                "_": {
                    "type": "string",
                    "description": "Optional placeholder. Leave empty.",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        plugin = _screen_companion_tool_plugin
        if plugin is None:
            return "屏幕陪伴工具当前不可用。"

        question = str(kwargs.get("question", "") or "").strip()
        event = _get_tool_event(context.context)
        try:
            capture_context = await plugin._capture_recognition_context()
            active_window_title = str(capture_context.get("active_window_title", "") or "")
            components = await plugin._analyze_screen(
                capture_context,
                session=event,
                active_window_title=active_window_title,
                custom_prompt=question,
                task_id="llm_tool_screen_peek",
                user_request_text=question or "请先看一下当前屏幕的关键信息",
            )
            result_text = _extract_plain_text(components)
            if result_text:
                return result_text
            return "这次没有拿到可用的屏幕观察结果，可能当前不在允许识屏的时段，或画面分析没有返回有效文本。"
        except Exception as e:
            logger.error("LLM 工具 screen_peek 调用失败: %s", e)
            return f"窥屏失败：{e}"


@dataclass
class ScreenUsageContextTool(FunctionTool[AstrAgentContext]):
    name: str = "screen_usage_context"
    description: str = (
        "当你需要了解用户最近在电脑上主要做了什么、持续了多久、"
        "或最近浏览过哪些页面时使用。只在确实需要近期活动轨迹时调用，不要每轮都查。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "这次想确认的近期使用情况，可留空，例如“最近在忙什么”或“最近看了哪些网页”。",
                },
                "include_browser_history": {
                    "type": "boolean",
                    "description": "如果这次确实需要更强的网页浏览旁证，可以设为 true；否则默认 false。",
                },
                "_": {
                    "type": "string",
                    "description": "Optional placeholder. Leave empty.",
                },
            },
            "required": [],
        }
    )

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        plugin = _screen_companion_tool_plugin
        if plugin is None:
            return "电脑使用情况工具当前不可用。"

        question = str(kwargs.get("question", "") or "").strip()
        include_browser_history = bool(kwargs.get("include_browser_history", False))

        try:
            active_window_title, _ = await asyncio.to_thread(plugin._get_active_window_info)
            active_window_title = plugin._normalize_window_title(active_window_title)
            scene = ""
            if active_window_title:
                scene = plugin._normalize_scene_label(plugin._identify_scene(active_window_title))

            request_flags = plugin._looks_like_usage_context_request(question)
            item_limit = max(1, int(getattr(plugin, "usage_context_item_limit", 6) or 6))
            lookback_hours = max(1, int(getattr(plugin, "usage_context_lookback_hours", 6) or 6))
            browser_lookback_minutes = max(
                10,
                int(getattr(plugin, "browser_history_lookback_minutes", 180) or 180),
            )

            sections: list[str] = []

            live_snapshot = plugin._build_current_activity_snapshot()
            if live_snapshot:
                live_label = str(
                    live_snapshot.get("page_title")
                    or live_snapshot.get("site_label")
                    or live_snapshot.get("app_name")
                    or live_snapshot.get("resource_label")
                    or live_snapshot.get("window")
                    or ""
                ).strip()
                if live_label:
                    sections.append(
                        "当前活动："
                        f"{live_label}，已约 {plugin._format_usage_context_duration(live_snapshot.get('duration', 0))}"
                    )

            activity_lines = plugin._build_recent_activity_summary_lines(
                lookback_hours=lookback_hours,
                limit=item_limit,
            )
            if activity_lines:
                sections.append("最近活动轨迹：\n" + "\n".join(f"- {line}" for line in activity_lines))
            scene_lines = plugin._build_recent_scene_summary_lines(
                lookback_hours=lookback_hours,
                limit=max(3, min(item_limit, 5)),
            )
            if scene_lines:
                sections.append("最近时间分布：\n" + "\n".join(f"- {line}" for line in scene_lines))
            app_lines = plugin._build_recent_app_summary_lines(
                lookback_hours=lookback_hours,
                limit=max(3, min(item_limit, 5)),
            )
            if app_lines:
                sections.append("最近常用应用：\n" + "\n".join(f"- {line}" for line in app_lines))

            if bool(getattr(plugin, "enable_input_stats", False)):
                payload = plugin._build_input_stats_payload(
                    days=max(1, min(7, (lookback_hours + 23) // 24))
                )
                if payload.get("available"):
                    today = payload.get("today", {}) or {}
                    input_lines = [
                        (
                            f"今天本地输入约 {today.get('total_inputs_label', '0 次')}，"
                            f"活跃 {today.get('active_minutes_label', '0 分钟')}"
                        )
                    ]
                    peak_hour_label = str(today.get("peak_hour_label", "") or "").strip()
                    if peak_hour_label and peak_hour_label != "暂无":
                        input_lines.append(f"输入高峰大致在 {peak_hour_label}")
                    sections.append("输入活跃度：\n" + "\n".join(f"- {line}" for line in input_lines[:2]))

            need_browser_lines = bool(
                request_flags.get("browser")
                or include_browser_history
                or scene.startswith("浏览")
                or scene in {"邮件", "社交"}
            )
            if need_browser_lines:
                browser_lines = plugin._build_recent_browsing_activity_lines(
                    lookback_hours=lookback_hours,
                    limit=item_limit,
                )
                if browser_lines:
                    sections.append(
                        "最近浏览轨迹：\n" + "\n".join(f"- {line}" for line in browser_lines)
                    )

            if include_browser_history and bool(getattr(plugin, "enable_local_browser_history", False)):
                browser_history_lines = plugin._build_local_browser_history_lines(
                    lookback_minutes=browser_lookback_minutes,
                    limit=item_limit,
                )
                if browser_history_lines:
                    sections.append(
                        "本地浏览器历史旁证：\n"
                        + "\n".join(f"- {line}" for line in browser_history_lines)
                    )

            if not sections:
                return "这次没有整理出足够明显的近期使用轨迹。"

            header = "电脑使用情况摘要："
            if scene or active_window_title:
                scene_label = scene or "未识别场景"
                window_label = active_window_title or "未知窗口"
                header += f"\n当前窗口：{window_label}（{scene_label}）"
            if question:
                header += f"\n查询重点：{question}"
            return header + "\n" + "\n".join(sections)
        except Exception as e:
            logger.error("LLM 工具 screen_usage_context 调用失败: %s", e)
            return f"读取电脑使用情况失败：{e}"


class ScreenCompanion(ScreenCompanionProactiveMixin, ScreenCompanionRuntimeMixin, ScreenCompanionMemoryMixin, ScreenCompanionInputStatsMixin, ScreenCompanionMediaMixin, ScreenCompanionCommandSupportMixin, Star):
    SCREEN_SKILL_NAME = "screen_skill"
    LEGACY_DEFAULT_CUSTOM_TASK = "02:00 根据用户行为催促其尽快休息"
    DEFAULT_WEBUI_PORT = 6314
    SCREENSHOT_MODE = "screenshot"
    RECORDING_MODE = "recording"
    REST_ACTIVITY_WINDOW_START_HOUR = 20
    REST_REMINDER_CUTOFF_HOUR = 4
    REST_REMINDER_ADVANCE_MINUTES = 20
    REST_REMINDER_LATEST_AFTER_MINUTES = 30
    REST_INFERENCE_LOOKBACK_DAYS = 10
    REST_INFERENCE_MIN_SAMPLES = 1
    RECORDING_FPS = 1.0
    RECORDING_DURATION_SECONDS = 10
    CHANGE_AWARE_IDLE_KEEPALIVE_SECONDS = 15 * 60
    CHANGE_AWARE_SIMILAR_REPLY_COOLDOWN_SECONDS = 8 * 60
    USER_ACTIVITY_GRACE_SECONDS = 45
    USER_ACTIVITY_CHANGE_GRACE_SECONDS = 15
    WORK_WINDOW_MESSAGE_COOLDOWN_SECONDS = 150
    GENERAL_WINDOW_MESSAGE_COOLDOWN_SECONDS = 240
    ENTERTAINMENT_WINDOW_MESSAGE_COOLDOWN_SECONDS = 360
    REST_CUE_REPLY_COOLDOWN_SECONDS = 90 * 60
    CUSTOM_TASK_PROCESS_DEDUP_SECONDS = 90
    BACKGROUND_SCREEN_GUARD_STALE_SECONDS = 5 * 60
    WINDOW_COMPANION_REATTACH_GRACE_SECONDS = 300
    SCREEN_ANALYSIS_FAILURE_BACKOFF_BASE_SECONDS = 30
    SCREEN_ANALYSIS_FAILURE_BACKOFF_MAX_SECONDS = 5 * 60
    SCREEN_TRACE_LIMIT = 40
    START_END_CONTEXT_LOOKBACK = 2
    LONG_TERM_MEMORY_RETENTION_DAYS = 45
    LIGHT_MEMORY_RETENTION_DAYS = 90
    EPISODIC_MEMORY_LIMIT = 120
    FOCUS_PATTERN_LIMIT = 80
    ACTIVITY_HISTORY_LIMIT = 1000
    ACTIVITY_MIN_DURATION_SECONDS = 15
    LIVE_ACTIVITY_MIN_DURATION_SECONDS = 5
    GEMINI_API_BASE = "https://generativelanguage.googleapis.com"
    GEMINI_FILE_POLL_TIMEOUT_SECONDS = 120
    GEMINI_FILE_POLL_INTERVAL_SECONDS = 2

    def __init__(self, context: Context, config: dict):
        import os

        super().__init__(context)
        global _screen_companion_tool_plugin
        _screen_companion_tool_plugin = self
        
        self.plugin_config = PluginConfig(config, context)

        try:
            self.context.add_llm_tools(
                ScreenPeekTool(),
                ScreenUsageContextTool(),
            )
        except Exception as e:
            logger.warning("注册屏幕陪伴 LLM 工具失败: %s", e)
        
        self._sync_all_config()
        self._instance_token = ""
        self._register_process_instance()
        self._cleanup_legacy_default_custom_tasks()
        
        self.auto_tasks = {}
        self.is_running = False
        self.task_counter = 0
        self.running = True
        self.background_tasks = []
        self._screen_recording_lock = asyncio.Lock()
        self._screen_recording_process = None
        self._screen_recording_path = ""
        self._recording_audio_device = None
        self._recording_ffmpeg_path = None
        self._recording_video_encoder = None
        self._recording_video_encoder_source = ""
        self._mic_monitor_background_task = None
        self._mic_input_device_index = None
        self._mic_input_device_name = ""
        self.state = "inactive"  # active, inactive, temporary
        self.temporary_tasks = {}
        # 固定自动观察任务 ID
        self.AUTO_TASK_ID = "task_0"
        self.WINDOW_COMPANION_TASK_ID = "window_companion_auto"

        # 日记功能相关
        self.diary_entries = []
        self.last_diary_date = None
        self.diary_metadata = {}

        if not self.diary_storage:
            self.diary_storage = str(self.plugin_config.diary_dir)
        self._refresh_diary_storage_runtime()

        self.parsed_custom_tasks = []
        self._parse_custom_tasks()

        self.last_mic_trigger = 0  # 上次麦克风触发时间
        self.mic_debounce_time = 60  # 麦克风防抖时间，单位为秒
        self.last_rest_reminder_time = None  # 上次休息提醒时间，用于冷却
        self.last_rest_reminder_day = ""

        self.parsed_preferences = {}
        self.learning_data = {}

        self.custom_presets = self.plugin_config.custom_presets
        self.current_preset_index = self.plugin_config.current_preset_index
        self.parsed_custom_presets = []
        self._parse_custom_presets()
        # 确保预设索引有效
        if self.current_preset_index >= len(self.parsed_custom_presets):
            self.current_preset_index = -1

        self.last_interaction_mode = self.interaction_mode
        self.last_check_interval = self.check_interval
        self.last_trigger_probability = self.trigger_probability
        self.last_active_time_range = self.active_time_range

        if not self.learning_storage:
            self.learning_storage = str(self.plugin_config.learning_dir)
        os.makedirs(self.learning_storage, exist_ok=True)
        self.input_stats_file = os.path.join(self.learning_storage, "input_stats_daily.json")
        self._ensure_input_stats_state()
        self._load_input_stats_daily()

        # 观察记录相关
        self.observations = []  # 存储观察记录

        if not self.observation_storage:
            self.observation_storage = str(self.plugin_config.observations_dir)
        os.makedirs(self.observation_storage, exist_ok=True)

        # 加载观察记录
        self._load_observations()

        # WebUI 相关
        self.web_server = None
        self.page_api = None
        self._register_plugin_page_api_if_available()
        self._ensure_webui_password()

        # 长期记忆系统
        self.long_term_memory = {}
        self.long_term_memory_file = os.path.join(self.learning_storage, "long_term_memory.json")
        self._load_long_term_memory()

        # 互动频率管理
        self.user_engagement = 5  # 用户参与度，范围 1-10
        self.engagement_history = []  # 记录用户参与度历史

        self.active_tasks = {}
        self.corrections = {}
        self.corrections_file = os.path.join(self.learning_storage, "corrections.json")
        self._load_corrections()
        
        # 窗口变化检测相关
        self.previous_windows = set()
        self.window_change_cooldown = 0
        self.window_timestamps = {}  # 记录窗口首次出现的时间戳
        self.auto_screen_runtime = {}
        self.recent_user_activity = {}
        self.screen_analysis_traces = []

        # 时间跟踪相关
        self.current_activity = None  # 当前活动
        self.current_activity_meta = None  # 当前活动的结构化信息
        self.current_activity_source = ""  # 当前活动来源
        self.activity_start_time = None  # 活动开始时间
        self.activity_history = []  # 活动历史记录
        self.activity_history_file = os.path.join(self.learning_storage, "activity_history.json")
        self._load_activity_history()
        self.rest_reminder_state_file = os.path.join(
            self.learning_storage, "rest_reminder_state.json"
        )
        self._load_rest_reminder_state()

        self.uncertainty_words = ["也许", "可能", "看起来", "我猜", "像是", "大概", "说不定", "似乎"]

        # 解析用户偏好配置
        self._parse_user_preferences()

        # 加载学习数据
        if self.enable_learning:
            self._load_learning_data()

        self.task_semaphore = asyncio.Semaphore(2)  # 限制同时运行的任务数
        self.task_queue = asyncio.Queue()

        task = asyncio.create_task(self._task_scheduler())
        self.background_tasks.append(task)

        # 启动日记任务
        if self.enable_diary:
            task = asyncio.create_task(self._diary_task())
            self.background_tasks.append(task)

        task = asyncio.create_task(self._custom_tasks_task())
        self.background_tasks.append(task)

        task = asyncio.create_task(self._input_stats_flush_task())
        self.background_tasks.append(task)

        self._ensure_mic_monitor_background_task()
        task = asyncio.create_task(self._background_activity_tracking_task())
        self.background_tasks.append(task)
        task = asyncio.create_task(self._window_companion_task())
        self.background_tasks.append(task)
        self._shutdown_lock = asyncio.Lock()
        self._webui_lock = asyncio.Lock()
        self._is_stopping = False
        self._screen_assist_cooldowns = {}
        self.last_shared_activity_invite_time = 0.0
        self._ensure_input_stats_listener()
        if self._use_screen_recording_mode():
            self._safe_create_task(
                self._ensure_recording_ready(),
                name="screen_recording_bootstrap",
            )

    async def terminate(self) -> None:
        """AstrBot 重载/卸载时的生命周期钩子。"""
        logger.info("收到 terminate 生命周期回调，准备停止屏幕伙伴插件")
        global _screen_companion_tool_plugin
        if _screen_companion_tool_plugin is self:
            _screen_companion_tool_plugin = None
        await self.stop()

    def _register_plugin_page_api_if_available(self) -> None:
        """注册 AstrBot 插件拓展页面 API。"""
        if not hasattr(self.context, "register_web_api"):
            return

        try:
            from .page_api import PluginPageApi
        except Exception as e:
            logger.warning(f"插件拓展页面 API 不可用，已跳过注册: {e}", exc_info=True)
            return

        try:
            self.page_api = PluginPageApi(self)
            self.page_api.register(self.context)
        except Exception as e:
            self.page_api = None
            logger.warning(f"插件拓展页面 API 注册失败，已跳过: {e}", exc_info=True)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _normalize_config_path(self, value: Any, *, field_name: str) -> str:
        normalized = PluginConfig.normalize_path_text(value)
        if normalized != str(value or "").strip():
            logger.warning(f"配置项 {field_name} 包含异常路径，已自动修正为: {normalized}")
            try:
                setattr(self.plugin_config, field_name, normalized)
            except Exception as e:
                logger.debug(f"回写修正后的路径配置失败 {field_name}: {e}")
        return normalized

    def _get_runtime_flag(self, name: str, default: bool = False) -> bool:
        return self._coerce_bool(getattr(self, name, default))

    def _get_configured_admin_ids(self) -> set[str]:
        admin_ids: set[str] = set()

        admin_qq = str(getattr(self, "admin_qq", "") or "").strip()
        if admin_qq:
            admin_ids.add(admin_qq)

        config_obj = getattr(getattr(self, "context", None), "astrbot_config", None)
        if isinstance(config_obj, dict):
            admins_raw = config_obj.get("admins_id", [])
            if isinstance(admins_raw, str):
                candidates = admins_raw.split(",")
            elif isinstance(admins_raw, (list, tuple, set)):
                candidates = admins_raw
            else:
                candidates = []
            for item in candidates:
                normalized = str(item or "").strip()
                if normalized:
                    admin_ids.add(normalized)

        return admin_ids

    def _get_primary_admin_id(self) -> str:
        admin_ids = self._get_configured_admin_ids()
        if not admin_ids:
            return ""

        admin_qq = str(getattr(self, "admin_qq", "") or "").strip()
        if admin_qq and admin_qq in admin_ids:
            return admin_qq

        return sorted(admin_ids)[0]

    def _get_event_sender_id(self, event: AstrMessageEvent) -> str:
        getter = getattr(event, "get_sender_id", None)
        if callable(getter):
            try:
                sender_id = str(getter() or "").strip()
                if sender_id:
                    return sender_id
            except Exception:
                pass

        for attr in ("sender_id", "user_id", "qq", "author_id"):
            value = str(getattr(event, attr, "") or "").strip()
            if value:
                return value

        return ""

    def _is_group_message_event(self, event: AstrMessageEvent) -> bool:
        getter = getattr(event, "get_group_id", None)
        if callable(getter):
            try:
                if str(getter() or "").strip():
                    return True
            except Exception:
                pass

        unified_msg_origin = str(getattr(event, "unified_msg_origin", "") or "").strip()
        return ":GroupMessage:" in unified_msg_origin

    def _has_admin_permission(self, event: AstrMessageEvent) -> bool:
        is_admin = getattr(event, "is_admin", None)
        if callable(is_admin):
            try:
                if is_admin():
                    return True
            except Exception:
                pass

        sender_id = self._get_event_sender_id(event)
        if not sender_id:
            return False

        return sender_id in self._get_configured_admin_ids()

    async def _ensure_admin_permission(
        self,
        event: AstrMessageEvent,
        *,
        reply_on_denied: bool = True,
        stop_on_denied: bool | None = None,
        message: str = "权限不足：仅管理员可使用该功能。",
    ) -> bool:
        if self._has_admin_permission(event):
            return True

        if stop_on_denied is None:
            stop_on_denied = reply_on_denied

        if reply_on_denied:
            try:
                await event.send(event.plain_result(message))
            except Exception as e:
                logger.debug(f"发送权限不足提示失败: {e}")

        if stop_on_denied:
            try:
                event.stop_event()
            except Exception:
                pass
        return False

    def _message_addresses_bot(self, message_text: str) -> bool:
        text = str(message_text or "").strip()
        bot_name = str(getattr(self, "bot_name", "") or "").strip()
        if not text or not bot_name:
            return False

        escaped_name = re.escape(bot_name)
        address_patterns = (
            rf"^\s*@?{escaped_name}(?:[，,。!！?？:：\s]|$)",
            rf"(?:^|[\s,，。!！?？:：])@{escaped_name}(?:[，,。!！?？:：\s]|$)",
            rf"^\s*(?:请|麻烦|欸|哎|诶)?\s*{escaped_name}(?:[，,。!！?？:：\s]|$)",
        )
        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in address_patterns
        )

    def _allow_implicit_screen_skill_trigger(
        self,
        event: AstrMessageEvent,
        message_text: str,
    ) -> bool:
        if not self._is_group_message_event(event):
            return True
        return self._message_addresses_bot(message_text)

    def _build_screen_skill_prompt(self, user_request: str) -> str:
        default_skill_prompt = (
            f"你正在执行内部识屏技能 {self.SCREEN_SKILL_NAME}。"
            "这是用户主动请求你看看当前屏幕。"
            "请像聊天里顺手接一句那样回应，先对齐用户这轮到底想确认什么，再说最关键的判断。"
            "先判断用户的问题目标是什么，再判断当前屏幕是否真的覆盖了这个目标。"
            "如果当前屏幕足以回答，就依据屏幕里的确定事实回答；如果还没覆盖到用户要找的东西，就直接说明还没看到，并追问它在哪个窗口/页面，或让用户切到那里。"
            "如果信息还不够，就明确说你现在能确定到哪一步，不要把推测说成看到了。"
            "如果要提建议，只给当前最有用的一条，不要写成解说词、战报腔或固定的夸赞加总结模板，也不要先机械复述一遍屏幕。"
            "不要提自动撤回或系统设定。"
        )
        custom_skill_prompt = str(
            getattr(self, "screen_skill_prompt", "") or ""
        ).strip()
        parts = [default_skill_prompt]
        if custom_skill_prompt:
            parts.append(custom_skill_prompt)
        user_request_text = str(user_request or "").strip()
        if user_request_text:
            parts.append(f"用户的原始请求：{user_request_text}")
        return "\n".join(part for part in parts if part)

    async def _invoke_screen_skill(
        self,
        event: AstrMessageEvent,
        *,
        request_prompt: str,
        history_user_text: str,
        task_id: str | None = None,
    ) -> str:
        ok, err_msg = self._check_env()
        if not ok:
            if self.debug:
                logger.warning(f"识屏技能环境检查失败: {err_msg}")
            return ""

        use_recording_mode = self._use_screen_recording_mode()
        capture_timeout = self._get_capture_context_timeout(
            "video" if use_recording_mode else "image"
        )
        capture_context = await asyncio.wait_for(
            self._capture_recognition_context(
                force_fresh_capture=not use_recording_mode,
                force_fresh_recording=use_recording_mode,
            ),
            timeout=capture_timeout,
        )
        custom_prompt = self._build_screen_skill_prompt(request_prompt)
        return await self._run_screen_assist(
            event,
            task_id=task_id or self.SCREEN_SKILL_NAME,
            custom_prompt=custom_prompt,
            history_user_text=history_user_text,
            capture_context=capture_context,
        )

    def _sync_all_config(self) -> None:
        """将配置对象同步到插件运行时字段。"""
        # 同步基础配置
        self.bot_name = self.plugin_config.bot_name
        self.enabled = self._coerce_bool(self.plugin_config.enabled)
        self.interaction_mode = self.plugin_config.interaction_mode
        self.check_interval = self.plugin_config.check_interval
        self.trigger_probability = self.plugin_config.trigger_probability
        self.active_time_range = self.plugin_config.active_time_range
        style_mode = getattr(self.plugin_config, "interaction_style_mode", "普通")
        if hasattr(style_mode, "value"):
            style_mode = style_mode.value
        self.interaction_style_mode = str(style_mode or "普通")
        self.use_companion_mode = self.interaction_style_mode == "陪伴"
        self.companion_prompt = getattr(self.plugin_config, 'companion_prompt', '')
        self.stealth_watch_mode = self.interaction_style_mode == "偷看"
        self.enable_usage_context_autopilot = self._coerce_bool(
            getattr(self.plugin_config, "enable_usage_context_autopilot", False)
        )
        self.enable_local_browser_history = self._coerce_bool(
            getattr(self.plugin_config, "enable_local_browser_history", False)
        )
        self.usage_context_lookback_hours = max(
            1,
            int(getattr(self.plugin_config, "usage_context_lookback_hours", 6) or 6),
        )
        self.browser_history_lookback_minutes = max(
            10,
            int(
                getattr(
                    self.plugin_config,
                    "browser_history_lookback_minutes",
                    180,
                )
                or 180
            ),
        )
        self.usage_context_item_limit = max(
            1,
            min(
                12,
                int(getattr(self.plugin_config, "usage_context_item_limit", 6) or 6),
            ),
        )
        self.capture_active_window = self._coerce_bool(self.plugin_config.capture_active_window)
        self.bot_vision_quality = self.plugin_config.bot_vision_quality
        self.screen_recognition_mode = self._normalize_screen_recognition_mode(
            getattr(
                self.plugin_config,
                "screen_recognition_mode",
                self.SCREENSHOT_MODE,
            )
        )
        self.image_prompt = self.plugin_config.image_prompt
        self.ffmpeg_path = self._normalize_config_path(
            getattr(self.plugin_config, "ffmpeg_path", ""),
            field_name="ffmpeg_path",
        )
        self.recording_fps = max(
            0.01, float(getattr(self.plugin_config, "recording_fps", self.RECORDING_FPS) or self.RECORDING_FPS)
        )
        self.recording_duration_seconds = max(
            1,
            int(
                getattr(
                    self.plugin_config,
                    "recording_duration_seconds",
                    self.RECORDING_DURATION_SECONDS,
                )
                or self.RECORDING_DURATION_SECONDS
            ),
        )
        self.use_external_vision = self._coerce_bool(
            getattr(self.plugin_config, "use_external_vision", False)
        )
        self.allow_unsafe_video_direct_fallback = self._coerce_bool(
            getattr(self.plugin_config, "allow_unsafe_video_direct_fallback", False)
        )
        self.vision_provider_id = str(
            getattr(self.plugin_config, "vision_provider_id", "") or ""
        ).strip()
        self.vision_provider_id_backup = str(
            getattr(self.plugin_config, "vision_provider_id_backup", "") or ""
        ).strip()
        self.vision_api_url = self.plugin_config.vision_api_url
        self.vision_api_key = self.plugin_config.vision_api_key
        self.vision_api_model = self.plugin_config.vision_api_model
        # 同步备用视觉API配置
        self.vision_api_url_backup = getattr(self.plugin_config, 'vision_api_url_backup', None)
        self.vision_api_key_backup = getattr(self.plugin_config, 'vision_api_key_backup', None)
        self.vision_api_model_backup = getattr(self.plugin_config, 'vision_api_model_backup', None)
        self.user_preferences = self.plugin_config.user_preferences
        self.use_llm_for_start_end = self._coerce_bool(self.plugin_config.use_llm_for_start_end)
        self.start_preset = self.plugin_config.start_preset
        self.end_preset = self.plugin_config.end_preset
        self.start_llm_prompt = self.plugin_config.start_llm_prompt
        self.end_llm_prompt = self.plugin_config.end_llm_prompt
        self.enable_diary = self._coerce_bool(self.plugin_config.enable_diary)
        raw_diary_time = getattr(self.plugin_config, "diary_time", "00:00")
        normalized_diary_time = self._normalize_clock_text(
            raw_diary_time,
            default="00:00",
        )
        self.diary_time = normalized_diary_time
        if normalized_diary_time != raw_diary_time:
            self.plugin_config.diary_time = normalized_diary_time
        self.diary_storage = self._normalize_config_path(
            self.plugin_config.diary_storage,
            field_name="diary_storage",
        )
        self.diary_reference_days = self.plugin_config.diary_reference_days
        self.diary_auto_recall = self._coerce_bool(self.plugin_config.diary_auto_recall)
        self.diary_recall_time = self.plugin_config.diary_recall_time
        self.diary_send_as_image = self._coerce_bool(self.plugin_config.diary_send_as_image)
        self.diary_generation_prompt = self.plugin_config.diary_generation_prompt
        self.weather_api_key = self.plugin_config.weather_api_key
        self.weather_city = self.plugin_config.weather_city
        self.enable_mic_monitor = self._coerce_bool(self.plugin_config.enable_mic_monitor)
        self.mic_threshold = self.plugin_config.mic_threshold
        self.mic_check_interval = self.plugin_config.mic_check_interval
        self.enable_input_stats = self._coerce_bool(
            getattr(self.plugin_config, "enable_input_stats", False)
        )
        self.enable_background_activity_tracking = self._coerce_bool(
            getattr(self.plugin_config, "enable_background_activity_tracking", False)
        )
        self.background_activity_tracking_interval = max(
            5,
            int(
                getattr(
                    self.plugin_config,
                    "background_activity_tracking_interval",
                    15,
                )
                or 15
            ),
        )
        self.input_stats_flush_interval = max(
            10,
            int(getattr(self.plugin_config, "input_stats_flush_interval", 60) or 60),
        )
        self.enable_away_auto_pause = self._coerce_bool(
            getattr(self.plugin_config, "enable_away_auto_pause", False)
        )
        self.away_auto_pause_threshold = max(
            300,
            int(getattr(self.plugin_config, "away_auto_pause_threshold", 1200) or 1200),
        )
        self.away_long_notice_threshold = max(
            self.away_auto_pause_threshold + 60,
            int(getattr(self.plugin_config, "away_long_notice_threshold", 3600) or 3600),
        )
        self.mask_activity_window_titles = self._coerce_bool(
            getattr(self.plugin_config, "mask_activity_window_titles", False)
        )
        self.activity_recognition_rules = str(
            getattr(self.plugin_config, "activity_recognition_rules", "") or ""
        )
        self.memory_threshold = self.plugin_config.memory_threshold
        self.battery_threshold = self.plugin_config.battery_threshold
        self.admin_qq = self.plugin_config.admin_qq
        self.proactive_target = self.plugin_config.proactive_target
        self.enable_proactive_decorating_hooks = self._coerce_bool(
            getattr(self.plugin_config, "enable_proactive_decorating_hooks", True)
        )
        self.save_local = self._coerce_bool(self.plugin_config.save_local)
        self.enable_natural_language_screen_assist = (
            self._coerce_bool(self.plugin_config.enable_natural_language_screen_assist)
        )
        self.screen_skill_prompt = str(
            getattr(self.plugin_config, "screen_skill_prompt", "") or ""
        )
        self.enable_window_companion = self._coerce_bool(self.plugin_config.enable_window_companion)
        self.window_companion_targets = self.plugin_config.window_companion_targets
        self.window_companion_check_interval = (
            self.plugin_config.window_companion_check_interval
        )
        self.window_companion_reattach_grace_seconds = max(
            10,
            int(
                getattr(
                    self.plugin_config,
                    "window_companion_reattach_grace_seconds",
                    self.WINDOW_COMPANION_REATTACH_GRACE_SECONDS,
                )
                or self.WINDOW_COMPANION_REATTACH_GRACE_SECONDS
            ),
        )
        self.use_shared_screenshot_dir = self._coerce_bool(self.plugin_config.use_shared_screenshot_dir)
        self.shared_screenshot_dir = self._normalize_config_path(
            self.plugin_config.shared_screenshot_dir,
            field_name="shared_screenshot_dir",
        )
        self.custom_tasks = self.plugin_config.custom_tasks
        self.rest_time_range = self.plugin_config.rest_time_range
        self.enable_learning = self._coerce_bool(self.plugin_config.enable_learning)
        self.enable_manual_correction_learning = self._coerce_bool(
            getattr(self.plugin_config, "enable_manual_correction_learning", True)
        )
        self.enable_natural_feedback_learning = self._coerce_bool(
            getattr(self.plugin_config, "enable_natural_feedback_learning", True)
        )
        self.enable_shared_activity_followup = self._coerce_bool(
            getattr(self.plugin_config, "enable_shared_activity_followup", True)
        )
        self.enable_shared_activity_preference_learning = self._coerce_bool(
            getattr(self.plugin_config, "enable_shared_activity_preference_learning", True)
        )
        self.learning_storage = self._normalize_config_path(
            self.plugin_config.learning_storage,
            field_name="learning_storage",
        )
        if not self.learning_storage:
            self.learning_storage = str(self.plugin_config.learning_dir)
        self.input_stats_file = os.path.join(self.learning_storage, "input_stats_daily.json")
        self.interaction_kpi = self.plugin_config.interaction_kpi
        self.debug = self._coerce_bool(self.plugin_config.debug)
        self.custom_presets = self.plugin_config.custom_presets
        self.current_preset_index = self.plugin_config.current_preset_index
        self._parse_custom_presets()
        # 确保预设索引有效
        if self.current_preset_index >= len(self.parsed_custom_presets):
            self.current_preset_index = -1
            self.plugin_config.current_preset_index = -1
        self._sync_window_companion_effective_params()
        # 同步配置
        self.observation_storage = self._normalize_config_path(
            self.plugin_config.observation_storage,
            field_name="observation_storage",
        )
        self.max_observations = self.plugin_config.max_observations
        self.interaction_frequency = self.plugin_config.interaction_frequency
        self.image_quality = self.plugin_config.image_quality
        self.system_prompt = self.plugin_config.system_prompt
        self.bot_appearance = self.plugin_config.bot_appearance

        # 同步 WebUI 配置
        self.webui_enabled = self._coerce_bool(self.plugin_config.webui.enabled)
        self.webui_host = self.plugin_config.webui.host
        normalized_port = self._normalize_webui_port(self.plugin_config.webui.port)
        if normalized_port != self.plugin_config.webui.port:
            self.plugin_config.webui.port = normalized_port
            self.plugin_config.save_webui_config()
        # 确保使用标准化后的端口值
        self.webui_port = normalized_port
        self.webui_auth_enabled = self._coerce_bool(self.plugin_config.webui.auth_enabled)
        self.webui_password = self.plugin_config.webui.password
        self.webui_session_timeout = self.plugin_config.webui.session_timeout
        self.webui_allow_external_api = self._coerce_bool(self.plugin_config.webui.allow_external_api)
        self._parse_window_companion_targets()

    def _get_learning_switches(self) -> list[tuple[str, str, bool]]:
        return [
            ("all", "总学习", self._coerce_bool(getattr(self, "enable_learning", True))),
            (
                "correction",
                "手动纠正学习",
                self._coerce_bool(getattr(self, "enable_manual_correction_learning", True)),
            ),
            (
                "feedback",
                "自然反馈学习",
                self._coerce_bool(getattr(self, "enable_natural_feedback_learning", True)),
            ),
            (
                "followup",
                "共同体验追问",
                self._coerce_bool(getattr(self, "enable_shared_activity_followup", True)),
            ),
            (
                "preference",
                "共同体验偏好学习",
                self._coerce_bool(
                    getattr(self, "enable_shared_activity_preference_learning", True)
                ),
            ),
        ]

    def _format_learning_switch_report(self) -> str:
        lines = ["学习开关状态："]
        master_enabled = self._coerce_bool(getattr(self, "enable_learning", True))
        for key, label, enabled in self._get_learning_switches():
            suffix = ""
            if key != "all" and not master_enabled:
                suffix = "（受总学习开关限制）"
            lines.append(f"- {label}：{'开启' if enabled else '关闭'}{suffix}")
        return "\n".join(lines)

    def _format_learning_activity_report(self) -> str:
        events = self._get_learning_runtime_events()
        channel_labels = {
            "correction": "手动纠正",
            "feedback": "自然反馈",
            "followup": "共同体验追问",
            "preference": "共同体验偏好",
        }
        lines = ["最近学习动态："]
        for channel in ("correction", "feedback", "followup", "preference"):
            item = events.get(channel, {}) or {}
            status = str(item.get("status", "") or "").strip()
            detail = str(item.get("detail", "") or "").strip()
            timestamp = self._format_runtime_timestamp(item.get("timestamp"))
            if not status:
                lines.append(f"- {channel_labels[channel]}：暂无记录")
                continue
            lines.append(
                f"- {channel_labels[channel]}：{status} / {detail or '无详情'} / {timestamp}"
            )
        return "\n".join(lines)

    def _build_kpi_help_text(self) -> str:
        return "\n".join(
            [
                "屏幕伙伴常用命令",
                "",
                "快速开始：",
                "- /kp 立即看一眼当前屏幕",
                "- /kpr 录一小段屏幕后再分析",
                "- /kpi start 开始自动观察",
                "- /kpi stop 停止自动观察",
                "",
                "学习相关：",
                "- /kpi learning 查看或切换学习开关",
                "- /kpi learned 查看最近自动学到的自然反馈",
                "- /kpi unlearn 1 删除一条误学记录",
                "- /kpi correct 原回复 纠正后的回复",
                "- /kpi jk 查看今日本地输入统计",
                "",
                "诊断维护：",
                "- /kpi status 查看运行状态和最近学习动态",
                "- /kpi list 查看当前运行中的任务",
                "- /kpi webui 查看插件拓展页面状态",
                "- /kpi webui start 手动启动兼容独立 WebUI",
                "- /kpi ffmpeg 查看或设置 ffmpeg",
                "",
                "小提示：",
                "- 如果你只是想让它少说点、自然点，优先用 /kpi learning 看当前学习状态。",
                "- 如果你想先试体验，最短路径是 /kp -> /kpi learning -> /kpi start。",
            ]
        )

    def _build_status_suggestions(
        self,
        *,
        env_ok: bool,
        active_task_ids: list[str],
    ) -> list[str]:
        suggestions: list[str] = []
        if not self.enabled:
            suggestions.append("插件当前未启用，先在配置里开启后再试 /kpi start。")
            return suggestions

        if not env_ok:
            suggestions.append("环境检查还没通过，先用 /kpi ffmpeg 或 /kpi status 看缺的依赖。")
            return suggestions

        if not active_task_ids or not self.is_running:
            suggestions.append("如果你想先直接体验一次，可以先用 /kp。")
            suggestions.append("如果你想开始自动观察，可以执行 /kpi start。")
            return suggestions

        suggestions.append("自动观察已经在运行；如果想检查学习是否生效，可以执行 /kpi learning。")
        suggestions.append("如果想看当前任务和最近状态细节，可以执行 /kpi list。")
        return suggestions

    def _set_learning_switch(self, target: str, enabled: bool) -> tuple[bool, str]:
        normalized_target = str(target or "").strip().lower()
        target_map = {
            "all": ("enable_learning", "总学习"),
            "总学习": ("enable_learning", "总学习"),
            "learning": ("enable_learning", "总学习"),
            "correction": ("enable_manual_correction_learning", "手动纠正学习"),
            "纠正": ("enable_manual_correction_learning", "手动纠正学习"),
            "feedback": ("enable_natural_feedback_learning", "自然反馈学习"),
            "自然反馈": ("enable_natural_feedback_learning", "自然反馈学习"),
            "followup": ("enable_shared_activity_followup", "共同体验追问"),
            "追问": ("enable_shared_activity_followup", "共同体验追问"),
            "preference": (
                "enable_shared_activity_preference_learning",
                "共同体验偏好学习",
            ),
            "偏好": ("enable_shared_activity_preference_learning", "共同体验偏好学习"),
        }
        if normalized_target not in target_map:
            return False, "未知开关，可用项：all, correction, feedback, followup, preference"

        config_key, label = target_map[normalized_target]
        setattr(self.plugin_config, config_key, bool(enabled))
        self._sync_all_config()
        return True, f"{label}已{'开启' if enabled else '关闭'}。"

    def _normalize_webui_port(self, port) -> int:
        try:
            normalized = int(port)
        except Exception:
            normalized = self.DEFAULT_WEBUI_PORT

        if normalized < 1 or normalized > 65535:
            logger.warning(
                f"WebUI 端口 {port} 不在有效范围内，已自动回退到 {self.DEFAULT_WEBUI_PORT}"
            )
            return self.DEFAULT_WEBUI_PORT
        elif normalized < 1024:
            logger.warning(
                f"WebUI 端口 {port} 是系统保留端口，可能需要管理员权限"
            )
        return normalized




























    def _apply_plugin_config_updates(self, config_dict: dict) -> None:
        """将配置字典写回插件配置对象。"""
        for k, v in config_dict.items():
            if k == "webui" and isinstance(v, dict):
                current_webui = self.plugin_config.webui
                # 检测密码是否被显式清空
                password_set_to_empty = "password" in v and not str(v["password"] or "").strip()
                for wk, wv in v.items():
                    if wk == "password" and not str(wv or "").strip():
                        # 允许显式清空密码
                        setattr(current_webui, wk, wv)
                    else:
                        setattr(current_webui, wk, wv)
                self.plugin_config.save_webui_config()
            elif k.startswith("webui_"):
                # 兼容旧版扁平 key，例如 webui_enabled -> webui.enabled
                wk = k[6:]
                if hasattr(self.plugin_config.webui, wk):
                    if wk == "password" and not str(v or "").strip():
                        # 允许显式清空密码
                        setattr(self.plugin_config.webui, wk, v)
                    else:
                        setattr(self.plugin_config.webui, wk, v)
                    self.plugin_config.save_webui_config()
            else:
                setattr(self.plugin_config, k, v)

    def _update_config_from_dict(self, config_dict: dict):
        """根据字典更新插件配置并处理运行时变更。"""
        if not config_dict:
            return

        try:
            # 使用配置服务更新配置
            if self.plugin_config:
                old_webui_state = self._snapshot_webui_runtime()
                old_recognition_mode = self._normalize_screen_recognition_mode(
                    getattr(self, "screen_recognition_mode", self.SCREENSHOT_MODE)
                )
                old_mic_monitor_enabled = bool(getattr(self, "enable_mic_monitor", False))
                old_input_stats_enabled = bool(getattr(self, "enable_input_stats", False))
                self._apply_plugin_config_updates(config_dict)

                self._sync_all_config()
                self._refresh_diary_storage_runtime()
                
                if self.enable_mic_monitor:
                    self._ensure_mic_monitor_background_task()
                elif old_mic_monitor_enabled:
                    self._stop_mic_monitor_background_task()

                if self.enable_input_stats:
                    if not old_input_stats_enabled:
                        self._ensure_input_stats_listener()
                elif old_input_stats_enabled:
                    self._stop_input_stats_listener(reason="config_update")

                # 检查是否明确设置了空密码
                password_set_to_empty = False
                if "webui" in config_dict and isinstance(config_dict["webui"], dict):
                    password_set_to_empty = "password" in config_dict["webui"] and not str(config_dict["webui"]["password"] or "").strip()
                elif "webui_password" in config_dict:
                    password_set_to_empty = not str(config_dict["webui_password"] or "").strip()
                
                # 只有未显式清空密码时，才自动补齐密码
                if not password_set_to_empty and self._ensure_webui_password():
                    self._sync_all_config()

                if self._is_webui_runtime_changed(old_webui_state):
                    self._safe_create_task(self._restart_webui(), name="restart_webui")

                new_recognition_mode = self._normalize_screen_recognition_mode(
                    getattr(self, "screen_recognition_mode", self.SCREENSHOT_MODE)
                )
                if old_recognition_mode != new_recognition_mode:
                    self._safe_create_task(
                        self._handle_screen_recognition_mode_change(),
                        name="switch_screen_recognition_mode",
                    )

                logger.debug("配置更新完成")
        except Exception as e:
            logger.error(f"更新配置失败: {e}")









































































































































































































    @admin_required
    @filter.command("kp")
    async def kp(self, event: AstrMessageEvent):
        """立即执行一次截图分析。"""
        ok, err_msg = self._check_screenshot_env()
        if not ok:
            yield event.plain_result(f"无法使用屏幕观察：\n{err_msg}")
            return

        try:
            capture_context = await asyncio.wait_for(
                self._capture_screenshot_context(force_fresh_capture=True), timeout=20.0
            )
            screen_result = await self._run_screen_assist(
                event,
                task_id="manual",
                custom_prompt="",
                history_user_text="/kp",
                capture_context=capture_context,
            )

            if not screen_result:
                yield event.plain_result("未获取到有效识别结果")
                return

            segments = self._split_message(screen_result)
            if len(segments) > 1:
                for i in range(len(segments) - 1):
                    segment = segments[i]
                    if segment.strip():
                        await self.context.send_message(
                            event.unified_msg_origin, MessageChain([Plain(segment)])
                        )
                        await asyncio.sleep(0.5)
                if segments[-1].strip():
                    yield event.plain_result(segments[-1])
            else:
                yield event.plain_result(screen_result)

            if self.debug:
                logger.info("处理完成")
        except asyncio.TimeoutError:
            logger.error("操作超时，请检查网络连接、模型响应速度或系统资源。")
            yield event.plain_result("操作超时，请稍后重试。")
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            import traceback

            logger.error(traceback.format_exc())
            yield event.plain_result("这次处理失败了，我先缓一口气，你可以再试一次。")

    @admin_required
    @filter.command("kpr")
    async def kpr(self, event: AstrMessageEvent):
        """\u7acb\u5373\u6267\u884c\u4e00\u6b21\u5f55\u5c4f\u5206\u6790\u3002"""
        ok, err_msg = self._check_recording_env()
        if not ok:
            yield event.plain_result(f"\u65e0\u6cd5\u4f7f\u7528\u5f55\u5c4f\u8bc6\u522b\uff1a\n{err_msg}")
            return

        try:
            duration = self._get_recording_duration_seconds()
            capture_timeout = self._get_capture_context_timeout("video")
            yield event.plain_result(
                f"\u5f00\u59cb\u5f55\u5236\u6700\u8fd1 {duration} \u79d2\u684c\u9762\u753b\u9762\u4e86\u3002\n"
                "\u5f55\u5236\u5b8c\u6210\u540e\u6211\u4f1a\u7ee7\u7eed\u5206\u6790\u5185\u5bb9\uff0c\u6574\u4e2a\u8fc7\u7a0b\u4f1a\u6bd4 /kp \u6162\u4e00\u4e9b\u3002"
            )
            capture_context = await asyncio.wait_for(
                self._capture_one_shot_recording_context(duration),
                timeout=capture_timeout,
            )
            yield event.plain_result("\u5f55\u5236\u5b8c\u6210\uff0c\u6b63\u5728\u5206\u6790\u753b\u9762\u5185\u5bb9...")

            screen_result = await self._run_screen_assist(
                event,
                task_id="manual_recording",
                custom_prompt="",
                history_user_text="/kpr",
                capture_context=capture_context,
                analysis_timeout=self._get_screen_analysis_timeout("video"),
            )

            if not screen_result:
                yield event.plain_result("\u8fd9\u6b21\u5f55\u5c4f\u6ca1\u6709\u62ff\u5230\u6709\u6548\u8bc6\u522b\u7ed3\u679c\uff0c\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u4e00\u6b21\u3002")
                return

            segments = self._split_message(screen_result)
            if len(segments) > 1:
                for i in range(len(segments) - 1):
                    segment = segments[i]
                    if segment.strip():
                        await self.context.send_message(
                            event.unified_msg_origin, MessageChain([Plain(segment)])
                        )
                        await asyncio.sleep(0.5)
                if segments[-1].strip():
                    yield event.plain_result(segments[-1])
            else:
                yield event.plain_result(screen_result)

            if self.debug:
                logger.info("\u5355\u6b21\u5f55\u5c4f\u6307\u4ee4\u5904\u7406\u5b8c\u6210")
        except asyncio.TimeoutError:
            logger.error("\u5355\u6b21\u5f55\u5c4f\u6216\u8bc6\u522b\u64cd\u4f5c\u8d85\u65f6")
            yield event.plain_result(
                "\u8fd9\u6b21 /kpr \u8d85\u65f6\u4e86\u3002\n"
                f"\u5f53\u524d\u5f55\u5c4f\u65f6\u957f\u662f {self._get_recording_duration_seconds()} \u79d2\uff0c"
                "\u5982\u679c\u8fd9\u4e2a\u95ee\u9898\u7ecf\u5e38\u51fa\u73b0\uff0c\u5efa\u8bae\u4f18\u5148\u7f29\u77ed\u5f55\u5c4f\u65f6\u957f\u6216\u964d\u4f4e\u5e27\u7387\u540e\u518d\u8bd5\u3002"
            )
        except Exception as e:
            logger.error(f"\u5355\u6b21\u5f55\u5c4f\u8bc6\u522b\u5931\u8d25: {e}")
            import traceback

            logger.error(traceback.format_exc())
            yield event.plain_result(
                "\u8fd9\u6b21\u5f55\u5c4f\u8bc6\u522b\u5931\u8d25\u4e86\uff0c\u4f60\u53ef\u4ee5\u7a0d\u540e\u518d\u8bd5\u4e00\u6b21\u3002"
            )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=0)
    async def on_shared_activity_memory(self, event: AstrMessageEvent):
        """从用户明确提到的共同经历里学习。"""
        try:
            message_text = str(getattr(event, "message_str", "") or "").strip()
            if not message_text or message_text.startswith("/"):
                return
            self._remember_recent_user_activity(event)
            self._remember_recent_companion_message(
                str(getattr(event, "unified_msg_origin", "") or ""),
                "user",
                message_text,
            )
            self._consume_pending_shared_activity_followup(event, message_text)
            self._learn_shared_activity_from_message(message_text)
            await self._learn_from_user_feedback_message(event, message_text)
            await self._maybe_follow_up_shared_activity(event, message_text)
        except Exception as e:
            logger.debug(f"记录共同经历失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1)
    async def on_natural_language_screen_assist(self, event: AstrMessageEvent):
        """处理自然语言触发的内置识屏技能。"""
        if not getattr(self, "enable_natural_language_screen_assist", False):
            return

        try:
            message_text = str(getattr(event, "message_str", "") or "").strip()
            if not message_text or message_text.startswith("/"):
                return

            allow_implicit_trigger = self._allow_implicit_screen_skill_trigger(
                event,
                message_text,
            )
            request_prompt = self._extract_screen_assist_prompt(
                message_text,
                allow_implicit=allow_implicit_trigger,
            )
            if not request_prompt:
                return

            if not await self._ensure_admin_permission(
                event,
                reply_on_denied=False,
                stop_on_denied=False,
            ):
                if self.debug:
                    sender_id = self._get_event_sender_id(event) or "<unknown>"
                    scope = "群聊" if self._is_group_message_event(event) else "私聊"
                    logger.debug(
                        f"自然语言识屏求助被拒绝：{scope} 发送者 {sender_id} 没有权限"
                    )
                return

            cooldown_key = str(getattr(event, "unified_msg_origin", "") or getattr(event, "get_sender_id", lambda: "")())
            now_ts = time.time()
            last_trigger = float((getattr(self, "_screen_assist_cooldowns", {}) or {}).get(cooldown_key, 0.0))
            if now_ts - last_trigger < 20:
                if self.debug:
                    logger.debug("自然语言识屏求助命中过冷却时间，跳过触发")
                return
            self._screen_assist_cooldowns[cooldown_key] = now_ts

            screen_result = await self._invoke_screen_skill(
                event,
                task_id="nl_screen_assist",
                request_prompt=request_prompt,
                history_user_text=message_text,
            )
            if not screen_result:
                return

            event.stop_event()
            segments = self._split_message(screen_result)
            for index, segment in enumerate(segments):
                if not segment.strip():
                    continue
                if index == len(segments) - 1:
                    yield event.plain_result(segment)
                else:
                    await self.context.send_message(
                        event.unified_msg_origin, MessageChain([Plain(segment)])
                    )
                    await asyncio.sleep(0.4)
        except Exception as e:
            logger.error(f"自然语言识屏助手失败: {e}")

    @admin_required
    @filter.command("kps")
    async def kps(self, event: AstrMessageEvent):
        """切换自动观察运行状态。"""
        self._ensure_runtime_state()
        if self.state == "active":
            # 停止自动观察
            self.state = "inactive"
            self.is_running = False
            logger.info("正在停止所有自动观察任务...")

            # 停止所有自动任务
            tasks_to_cancel = list(self.auto_tasks.items())
            for task_id, task in tasks_to_cancel:
                logger.info(f"取消任务 {task_id}")
                task.cancel()

            for task_id, task in tasks_to_cancel:
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待任务 {task_id} 停止超时")
                except asyncio.CancelledError:
                    logger.info(f"[Task {task_id}] status update")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

            self.auto_tasks.clear()
            logger.info("所有自动观察任务已停止")
            end_response = await self._get_end_response(event.unified_msg_origin)
            yield event.plain_result(end_response)
        else:
            # 启动自动观察
            if not self.enabled:
                yield event.plain_result(
                    "插件当前未启用，请先在配置中开启后再启动自动观察。"
                )
                return

            ok, err_msg = self._check_env(check_mic=False)
            if not ok:
                yield event.plain_result(f"启动失败：\n{err_msg}")
                return

            # 检查是否已有自动观察任务
            if self.AUTO_TASK_ID in self.auto_tasks or self.is_running:
                logger.info("自动观察任务已存在，无需重复启动")
                yield event.plain_result("自动观察任务已在运行中")
                return

            self.state = "active"
            self.is_running = True
            logger.info(f"启动任务 {self.AUTO_TASK_ID}")
            self.auto_tasks[self.AUTO_TASK_ID] = asyncio.create_task(
                self._auto_screen_task(event, task_id=self.AUTO_TASK_ID)
            )
            start_response = await self._get_start_response(event.unified_msg_origin)
            yield event.plain_result(start_response)

    @filter.command_group("kpi")
    def kpi_group(self):
        """管理自动观察屏幕任务。"""
        pass

    @admin_required
    @kpi_group.command("ys")
    async def kpi_ys(self, event: AstrMessageEvent, preset_index: int = None):
        """切换预设。"""
        if preset_index is None:
            async for result in self._render_preset_list(event):
                yield result
            return
        
        if preset_index < 0:
            self.current_preset_index = -1
            self.plugin_config.current_preset_index = -1
            yield event.plain_result("已切换到手动配置模式。")
            return
        
        if preset_index >= len(self.parsed_custom_presets):
            yield event.plain_result(
                f"预设 {preset_index} 不存在。\n"
                f"当前共有 {len(self.parsed_custom_presets)} 个预设。\n"
                f"用法: /kpi y [序号] [间隔秒数] [触发概率]"
            )
            return
        
        self.current_preset_index = preset_index
        self.plugin_config.current_preset_index = preset_index
        
        preset = self.parsed_custom_presets[preset_index]
        yield event.plain_result(
            f"已切换到预设 {preset_index}: {preset['name']}，间隔 {preset['check_interval']} 秒，触发概率 {preset['trigger_probability']}%"
        )

    @admin_required
    @kpi_group.command("start")
    async def kpi_start(self, event: AstrMessageEvent):
        self._ensure_runtime_state()
        if not self.enabled:
            yield event.plain_result(
                    "插件当前未启用，请先在配置中开启后再启动自动观察。"
            )
            return

        ok, err_msg = self._check_env(check_mic=False)
        if not ok:
            yield event.plain_result(f"启动失败：\n{err_msg}")
            return

        # 检查是否已有自动观察任务
        if self.AUTO_TASK_ID in self.auto_tasks:
            logger.info("自动观察任务已存在，无需重复启动")
            return

        self.state = "active"
        self.is_running = True
        logger.info(f"启动任务 {self.AUTO_TASK_ID}")
        self.auto_tasks[self.AUTO_TASK_ID] = asyncio.create_task(
            self._auto_screen_task(event, task_id=self.AUTO_TASK_ID)
        )
        start_response = await self._get_start_response(event.unified_msg_origin)
        yield event.plain_result(f"已启动自动观察任务 {self.AUTO_TASK_ID}。\n{start_response}")

    @admin_required
    @kpi_group.command("stop")
    async def kpi_stop(self, event: AstrMessageEvent, task_id: str = None):
        """停止自动观察任务。"""
        self._ensure_runtime_state()
        if task_id:
            if task_id in self.auto_tasks:
                task = self.auto_tasks.pop(task_id)
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待任务 {task_id} 停止超时")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"停止任务 {task_id} 失败: {e}")
                yield event.plain_result(f"已停止自动观察任务 {task_id}。")
            else:
                yield event.plain_result(f"任务 {task_id} 不存在。")
        else:
            # 停止所有自动任务
            tasks_to_cancel = list(self.auto_tasks.items())
            for task_id, task in tasks_to_cancel:
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待任务 {task_id} 停止超时")
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"停止任务 {task_id} 失败: {e}")
                self.auto_tasks.pop(task_id, None)
            
            # 停止窗口陪伴任务
            if hasattr(self, "window_companion_active_title") and self.window_companion_active_title:
                await self._stop_window_companion_session(reason="manual_stop")
            
            self.is_running = False
            self.state = "inactive"
            end_response = await self._get_end_response(event.unified_msg_origin)
            yield event.plain_result(f"已停止所有自动观察任务。\n{end_response}")



    @admin_required
    @kpi_group.command("status")
    async def kpi_status(self, event: AstrMessageEvent):
        """输出当前运行状态和关键诊断信息。"""
        async for result in self._render_status_report(event):
            yield result

    @admin_required
    @kpi_group.command("help")
    async def kpi_help(self, event: AstrMessageEvent):
        """查看常用命令帮助。"""
        yield event.plain_result(self._build_kpi_help_text())

    @admin_required
    @kpi_group.command("list")
    async def kpi_list(self, event: AstrMessageEvent):
        """列出当前运行中的自动观察任务。"""
        self._ensure_runtime_state()
        if not self.auto_tasks:
            yield event.plain_result(
                "当前没有运行中的自动观察任务。\n"
                "可以先用 /kp 试一次即时识屏，或者用 /kpi start 开始自动观察。"
            )
        else:
            msg = "当前运行中的任务：\n"
            for task_id in self.auto_tasks:
                msg += f"- {task_id}\n"
            yield event.plain_result(msg)

    @admin_required
    @kpi_group.command("ffmpeg")
    async def kpi_ffmpeg(self, event: AstrMessageEvent, ffmpeg_path: str = None):
        """设置 ffmpeg 路径并自动复制到插件数据目录。"""
        import shutil
        
        if not ffmpeg_path:
            current_ffmpeg = self._get_ffmpeg_path()
            if current_ffmpeg:
                yield event.plain_result(f"当前 ffmpeg 路径：{current_ffmpeg}")
            else:
                storage_dir = self._get_ffmpeg_storage_dir()
                yield event.plain_result(
                    "未找到 ffmpeg。\n"
                    "用法: /kpi ffmpeg [ffmpeg.exe 所在路径]\n"
                    "例如: /kpi ffmpeg C:\\Users\\用户名\\Downloads\\ffmpeg\\bin\\ffmpeg.exe\n"
                    "\n"
                    f"插件会自动将 ffmpeg 复制到插件数据目录的 bin 文件夹：{storage_dir}"
                )
            return
        
        source_path = os.path.abspath(os.path.expanduser(ffmpeg_path.strip()))
        
        ffmpeg_bin_dir = self._get_ffmpeg_storage_dir(create=True)
        
        dest_path = os.path.join(ffmpeg_bin_dir, "ffmpeg.exe")
        
        if not os.path.exists(source_path):
            yield event.plain_result(f"源文件不存在：{source_path}")
            return
        
        try:
            shutil.copy2(source_path, dest_path)
            self._recording_ffmpeg_path = None  # 清除缓存，强制重新检测
            new_path = self._get_ffmpeg_path()
            yield event.plain_result(f"ffmpeg 已复制到：{new_path}")
        except Exception as e:
            yield event.plain_result(f"复制失败：{str(e)}")

    @admin_required
    @kpi_group.command("y")
    async def kpi_y(self, event: AstrMessageEvent, preset_index: int = None, interval: int = None, probability: int = None):
        """新增或修改自定义预设。"""
        if preset_index is None:
            yield event.plain_result(
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30 表示把预设 1 设置为每 90 秒、30% 概率触发"
            )
            return
        
        if interval is None or probability is None:
            yield event.plain_result(
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30 表示把预设 1 设置为每 90 秒、30% 概率触发"
            )
            return
        
        if preset_index < 0:
            yield event.plain_result("预设序号不能小于 0。")
            return
        
        interval = max(10, int(interval))
        probability = max(0, min(100, int(probability)))
        
        lines = []
        if self.custom_presets:
            lines = self.custom_presets.strip().split('\n')
        
        preset_name = f"预设{preset_index}"
        new_preset = f"{preset_name}|{interval}|{probability}"
        
        while len(lines) <= preset_index:
            lines.append("")
        
        lines[preset_index] = new_preset
        
        self.custom_presets = "\n".join(lines)
        self.plugin_config.custom_presets = self.custom_presets
        
        self._parse_custom_presets()
        
        yield event.plain_result(
            f"已更新预设 {preset_index}：间隔 {interval} 秒，触发概率 {probability}%"
        )


    @admin_required
    @kpi_group.command("p")
    async def kpi_p(self, event: AstrMessageEvent):
        """列出全部自定义预设。"""
        async for result in self._render_preset_list(event):
            yield result

    @admin_required
    @kpi_group.command("add")
    async def kpi_add(self, event: AstrMessageEvent, interval: int, *prompt):
        """新增一个自定义观察任务。"""
        if not self.enabled:
            yield event.plain_result(
                "插件当前未启用，请先开启后再添加自定义任务。"
            )
            return

        custom_prompt = " ".join(prompt) if prompt else ""
        try:
            interval = max(30, int(interval))
            if not self.is_running:
                self.is_running = True
            task_id = f"task_{self.task_counter}"
            self.task_counter += 1
            self.auto_tasks[task_id] = asyncio.create_task(
                self._auto_screen_task(
                    event,
                    task_id=task_id,
                    custom_prompt=custom_prompt,
                    interval=interval,
                )
            )
            yield event.plain_result(
                f"已添加自定义任务 {task_id}，触发间隔为 {interval} 秒。"
            )
        except ValueError:
            yield event.plain_result("用法: /kpi add [间隔秒数] [自定义提示词]")

    @admin_required
    @kpi_group.command("d")
    async def kpi_d(self, event: AstrMessageEvent, date: str = None):
        """查看指定日期的日记。"""
        async for result in self._handle_diary_command(event, date):
            yield result


    @admin_required
    @kpi_group.command("jk")
    async def kpi_jk(self, event: AstrMessageEvent):
        """查看今日本地输入统计。"""
        report_text = self._format_today_input_stats_text()

        if not self.enable_input_stats:
            yield event.plain_result(report_text)
            return

        if not self.use_llm_for_start_end:
            yield event.plain_result(report_text)
            return

        provider = self.context.get_using_provider()
        if not provider:
            yield event.plain_result(report_text)
            return

        try:
            stats_report = self._build_today_input_stats_report()
            if not stats_report.get("available"):
                yield event.plain_result(report_text)
                return

            today = stats_report.get("today", {}) if isinstance(stats_report.get("today"), dict) else {}
            llm_prompt = "\n".join(
                [
                    "请把下面这份“今日本地输入统计”整理成一段自然、简短、具体的中文回顾。",
                    "要求：",
                    "1. 保留数据感，但不要逐项机械复述成报表。",
                    "2. 可以点出今天大致忙不忙、输入节奏是否集中，但不要过度脑补。",
                    "3. 不要输出标题，不要使用 Markdown 列表。",
                    "4. 控制在 80 到 160 字。",
                    "",
                    f"键盘：{today.get('keys_label', '0 次')}",
                    f"点击：{today.get('clicks_label', '0 次')}",
                    f"滚轮：{today.get('scroll_steps_label', '0 格')}",
                    f"鼠标移动：{today.get('moves_label', '0 段')} / {today.get('move_pixels_label', '0 px')}",
                    f"活跃分钟：{today.get('active_minutes_label', '0 分钟')}",
                    f"输入总量：{today.get('total_inputs_label', '0 次')}",
                    f"高峰时段：{today.get('peak_hour_label', '暂无')}",
                    f"活跃区间：{stats_report.get('active_ranges_label', '暂无')}",
                    f"最近一次输入：{today.get('last_event_time_label', '暂无') or '暂无'}",
                    f"当前在场感：{stats_report.get('presence_label', '未知')}",
                    f"在场感说明：{stats_report.get('presence_detail', '暂无') or '暂无'}",
                ]
            )
            system_prompt = await self._get_persona_prompt(event.unified_msg_origin)
            response = await provider.text_chat(prompt=llm_prompt, system_prompt=system_prompt)
            llm_text = str(getattr(response, "completion_text", "") or "").strip()
            yield event.plain_result(llm_text or report_text)
        except Exception as e:
            logger.error(f"生成输入统计二次加工回复失败: {e}")
            yield event.plain_result(report_text)

    @admin_required
    @kpi_group.command("correct")
    async def kpi_correct(self, event: AstrMessageEvent, *args):
        """纠正 Bot 的回复。"""
        if len(args) < 2:
            yield event.plain_result("用法: /kpi correct [原回复] [纠正后的回复]")
            return
        
        # 提取原回复和纠正后的内容
        original = args[0]
        corrected = ' '.join(args[1:])
        
        # 记录纠正
        learned = self._learn_from_correction(original, corrected)
        if learned:
            yield event.plain_result("已记录这次纠正，我会把它作为后续参考。")
        else:
            yield event.plain_result("当前手动纠正学习已关闭，这次没有写入学习记录。")

    @admin_required
    @kpi_group.command("preference")
    async def kpi_preference(self, event: AstrMessageEvent, category: str, *preference):
        """添加用户偏好。"""
        if not preference:
            yield event.plain_result("用法: /kpi preference [类别] [偏好内容]")
            yield event.plain_result("支持的类别: music, movies, food, hobbies, other")
            return
        
        # 验证类别
        valid_categories = ["music", "movies", "food", "hobbies", "other"]
        if category not in valid_categories:
            yield event.plain_result(f"无效类别，支持的类别有: {', '.join(valid_categories)}")
            return
        
        # 提取偏好内容
        preference_content = ' '.join(preference)
        
        # 添加偏好
        self._add_user_preference(category, preference_content)
        
        yield event.plain_result(f"已添加偏好: {category} - {preference_content}")

    @admin_required
    @kpi_group.command("learning")
    async def kpi_learning(self, event: AstrMessageEvent, target: str = "", state: str = ""):
        """查看或切换学习相关开关。"""
        normalized_target = str(target or "").strip().lower()
        normalized_state = str(state or "").strip().lower()

        if not normalized_target or normalized_target in {"status", "list"}:
            lines = [
                self._format_learning_switch_report(),
                "",
                self._format_learning_activity_report(),
                "",
                "用法：/kpi learning [all|correction|feedback|followup|preference] [on|off]",
                "示例：/kpi learning feedback off",
            ]
            yield event.plain_result("\n".join(lines))
            return

        if normalized_target in {"on", "off"} and not normalized_state:
            normalized_state = normalized_target
            normalized_target = "all"

        if normalized_state not in {"on", "off"}:
            yield event.plain_result(
                "用法：/kpi learning [all|correction|feedback|followup|preference] [on|off]"
            )
            return

        ok, message = self._set_learning_switch(
            normalized_target,
            normalized_state == "on",
        )
        if not ok:
            yield event.plain_result(message)
            return

        yield event.plain_result(
            f"{message}\n{self._format_learning_switch_report()}\n\n{self._format_learning_activity_report()}"
        )

    @admin_required
    @kpi_group.command("learned")
    async def kpi_learned(self, event: AstrMessageEvent, limit: int = 5):
        """查看最近自动学到的自然反馈。"""
        limit = max(1, min(10, int(limit)))
        records = self._get_recent_learned_feedback_records(limit=limit, source="natural_feedback")
        if not records:
            yield event.plain_result(
                "最近还没有自动学习到新的自然反馈。\n"
                "你可以先自然说一句像“别太官方，短一点”，再执行 /kpi learning 看有没有命中。"
            )
            return

        lines = ["最近自动学习到的自然反馈："]
        for index, record in enumerate(records, start=1):
            timestamp = str(record.get("timestamp", "") or "")[:16].replace("T", " ")
            scene = str(record.get("scene", "") or "通用")
            preference_hint = str(record.get("preference_hint", "") or "").strip()
            corrected = str(record.get("corrected", "") or "").strip()
            lines.append(
                f"{index}. [{timestamp or '未知时间'}] {scene} | {preference_hint or corrected or '无摘要'}"
            )
            if corrected and corrected != preference_hint:
                lines.append(f"   原话：{corrected}")

        lines.append("可用 /kpi unlearn [序号] 删除，或 /kpi unlearn all 清空自动学习记录。")
        yield event.plain_result("\n".join(lines))

    @admin_required
    @kpi_group.command("unlearn")
    async def kpi_unlearn(self, event: AstrMessageEvent, target: str = ""):
        """删除自动学习到的自然反馈。"""
        normalized_target = str(target or "").strip().lower()
        if not normalized_target:
            yield event.plain_result("用法: /kpi unlearn [序号] 或 /kpi unlearn all")
            return

        if normalized_target == "all":
            records = self._get_recent_learned_feedback_records(limit=200, source="natural_feedback")
            removed = 0
            for record in records:
                if self._delete_correction_learning_record(record.get("id", "")):
                    removed += 1
            yield event.plain_result(f"已删除 {removed} 条自动学习记录。")
            return

        if not normalized_target.isdigit():
            yield event.plain_result("请提供要删除的序号，或使用 /kpi unlearn all。")
            return

        index = int(normalized_target)
        records = self._get_recent_learned_feedback_records(limit=10, source="natural_feedback")
        if index < 1 or index > len(records):
            yield event.plain_result(f"当前只有 {len(records)} 条可删除记录。")
            return

        target_record = records[index - 1]
        if not self._delete_correction_learning_record(target_record.get("id", "")):
            yield event.plain_result("删除失败，这条记录可能已经不存在。")
            return

        summary = str(target_record.get("preference_hint", "") or target_record.get("corrected", "") or "").strip()
        yield event.plain_result(f"已删除第 {index} 条自动学习记录：{summary or '已移除'}")

    @admin_required
    @kpi_group.command("recent")
    async def kpi_recent(self, event: AstrMessageEvent, days: int = 3):
        """查看最近几天的日记。"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("日记功能当前未启用。")
            return

        days = max(1, min(7, int(days)))  # 限制 1-7 天
        # 获取日记文件列表
        today = datetime.date.today()
        found_diaries = []

        for i in range(days):
            target_date = today - datetime.timedelta(days=i)
            diary_filename = f"diary_{target_date.strftime('%Y%m%d')}.md"
            diary_path = os.path.join(self.diary_storage, diary_filename)

            if os.path.exists(diary_path):
                try:
                    with open(diary_path, encoding="utf-8") as f:
                        diary_content = f.read()
                    found_diaries.append(
                        {"date": target_date, "content": diary_content}
                    )
                except Exception as e:
                    logger.error(f"读取日记失败: {e}")

        if not found_diaries:
            yield event.plain_result("最近几天还没有找到可查看的日记。")
            return

        if self.diary_auto_recall:
            logger.info(f"日记消息将在 {self.diary_recall_time} 秒后自动撤回")

            # 启动自动撤回任务
            async def recall_message():
                await asyncio.sleep(self.diary_recall_time)
                try:
                    logger.info(f"最近日记消息已到达自动撤回时间: {self.diary_recall_time} 秒")
                except Exception as e:
                    logger.error(f"自动撤回日记记录失败: {e}")

            task = asyncio.create_task(recall_message())
            self.background_tasks.append(task)

        for diary in found_diaries:
            diary_message = self._format_diary_preview_message(
                diary["date"],
                diary["content"],
            )
            
            send_as_image = self.diary_send_as_image
            
            if send_as_image:
                try:
                    temp_file_path = self._generate_diary_image(diary_message)
                    yield event.image_result(temp_file_path)
                    os.unlink(temp_file_path)
                except Exception as e:
                    logger.error(f"生成日记图片失败: {e}")
                    yield event.plain_result(diary_message)
            else:
                yield event.plain_result(diary_message)
            
            await asyncio.sleep(0.5)  # 加一点小延迟，让发送更自然

        # 同时异步生成“被偷看日记”时的回复
        async def generate_blame():
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt(event.unified_msg_origin)
                    response = await provider.text_chat(
                        prompt=self.diary_response_prompt, system_prompt=system_prompt
                    )
                    if (
                        response
                        and hasattr(response, "completion_text")
                        and response.completion_text
                    ):
                        await self.context.send_message(
                            event.unified_msg_origin, 
                            MessageChain([Plain(response.completion_text)])
                        )
                    else:
                        await self.context.send_message(
                            event.unified_msg_origin, 
                            MessageChain([Plain("喂，你怎么一下子翻了我这么多天的日记呀，真是的……")])
                        )
                except Exception as e:
                    logger.error(f"生成日记被偷看回复失败: {e}")
                    await self.context.send_message(
                        event.unified_msg_origin, 
                        MessageChain([Plain("喂，你怎么一下子翻了我这么多天的日记呀，真是的……")])
                    )
            else:
                await self.context.send_message(
                    event.unified_msg_origin, 
                    MessageChain([Plain("喂，你怎么一下子翻了我这么多天的日记呀，真是的……")])
                )

        # 异步生成这条吐槽式回复
        blame_task = asyncio.create_task(generate_blame())
        self.background_tasks.append(blame_task)

    @admin_required
    @kpi_group.command("debug")
    async def kpi_debug(self, event: AstrMessageEvent, status: str = None):
        """切换调试模式 /kpi debug [on/off]"""
        if status is None:
            current_status = self.debug
            status_text = "开启" if current_status else "关闭"
            yield event.plain_result(f"当前调试模式状态：{status_text}")
            return
        
        status = status.lower()
        if status == "on":
            self.plugin_config.debug = True
            yield event.plain_result("调试模式已开启，后续会输出更多日志。")
        elif status == "off":
            self.plugin_config.debug = False
            yield event.plain_result("调试模式已关闭，将隐藏大部分调试日志。")
        else:
            yield event.plain_result("用法: /kpi debug [on/off]")

    @admin_required
    @kpi_group.command("webui")
    async def kpi_webui(self, event: AstrMessageEvent, action: str = ""):
        """查看或控制 WebUI /kpi webui [start/stop]"""
        action_text = str(action or "").strip().lower()
        if not action_text:
            async for result in self._render_webui_status(event):
                yield result
            return
        if action_text == "start":
            if self.web_server:
                yield event.plain_result("兼容独立 WebUI 已经在运行中。")
            else:
                await self._start_webui()
                yield event.plain_result(f"兼容独立 WebUI 已启动，访问地址: http://127.0.0.1:{self.webui_port}")
        elif action_text == "stop":
            if not self.web_server:
                yield event.plain_result("兼容独立 WebUI 当前没有运行。")
            else:
                await self._stop_webui()
                self.web_server = None
                yield event.plain_result("兼容独立 WebUI 已停止。")
        else:
            yield event.plain_result("无效操作，请使用 /kpi webui start 或 /kpi webui stop")

    @admin_required
    @kpi_group.command("cd")
    async def kpi_cd(self, event: AstrMessageEvent, date: str = None):
        """补写日记 /kpi cd [YYYYMMDD]"""
        async for result in self._handle_complete_command(event, date):
            yield result
















    
    
    
    














