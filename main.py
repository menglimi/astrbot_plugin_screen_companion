import asyncio
import base64
import datetime
import io
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import uuid

# 默认的人格设定
DEFAULT_SYSTEM_PROMPT = """角色设定：窥屏助手
把你正在使用的人格复制到这里"""

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import BaseMessageComponent, Image, Plain
from astrbot.api.star import Context, Star, StarTools

# 导入 WebServer 类
from .web_server import WebServer
# 导入配置管理
from .core.config import PluginConfig


class ScreenCompanion(Star):
    def __init__(self, context: Context, config: dict):
        import os

        super().__init__(context)
        
        # 初始化插件配置
        self.plugin_config = PluginConfig(config, context)
        
        # 同步配置到实例属性
        self._sync_all_config()
        
        self.auto_tasks = {}
        self.is_running = False
        self.task_counter = 0
        self.running = True
        self.background_tasks = []
        # 状态管理
        self.state = "inactive"  # active, inactive, temporary
        self.temporary_tasks = {}
        # 固定自动化任务ID
        self.AUTO_TASK_ID = "task_0"

        # 日记功能相关
        self.diary_entries = []
        self.last_diary_date = None

        # 初始化日记存储路径
        if not self.diary_storage:
            self.diary_storage = str(self.plugin_config.diary_dir)
        os.makedirs(self.diary_storage, exist_ok=True)

        # 自定义监控任务相关
        self.parsed_custom_tasks = []
        self._parse_custom_tasks()

        # 麦克风监听相关
        self.last_mic_trigger = 0  # 上次触发时间，用于防抖
        self.mic_debounce_time = 60  # 防抖时间，单位秒

        # 用户偏好和学习相关
        self.parsed_preferences = {}
        self.learning_data = {}

        self.custom_presets = self.plugin_config.custom_presets
        self.current_preset_index = self.plugin_config.current_preset_index
        self.parsed_custom_presets = []
        self._parse_custom_presets()
        # 确保预设索引有效
        if self.current_preset_index >= len(self.parsed_custom_presets):
            self.current_preset_index = -1

        # 互动模式状态跟踪
        self.last_interaction_mode = self.interaction_mode
        self.last_check_interval = self.check_interval
        self.last_trigger_probability = self.trigger_probability
        self.last_active_time_range = self.active_time_range

        # 初始化学习数据存储路径
        if not self.learning_storage:
            self.learning_storage = str(self.plugin_config.learning_dir)
        os.makedirs(self.learning_storage, exist_ok=True)

        # 观察记录相关
        self.observations = []  # 存储观察记录

        # 初始化观察记录存储路径
        if not self.observation_storage:
            self.observation_storage = str(self.plugin_config.observations_dir)
        os.makedirs(self.observation_storage, exist_ok=True)

        # 加载观察记录
        self._load_observations()

        # Web UI 相关
        self.web_server = None
        self._ensure_webui_password()

        # 日记元数据相关（记录日记查看状态）
        self.diary_metadata = {}
        self.diary_metadata_file = os.path.join(self.diary_storage, "diary_metadata.json")
        self._load_diary_metadata()

        # 长期记忆系统
        self.long_term_memory = {}
        self.long_term_memory_file = os.path.join(self.learning_storage, "long_term_memory.json")
        self._load_long_term_memory()

        # 互动频率管理
        self.user_engagement = 5  # 用户参与度，范围1-10，默认5
        self.engagement_history = []  # 记录用户参与度历史

        # 情绪词汇和语气词
        self.emotion_words = {
            "happy": ["真好", "太棒了", "开心", "高兴", "兴奋", "不错", "很棒", "厉害"],
            "concerned": ["担心", "注意", "小心", "提醒", "建议"],
            "curious": ["好奇", "想知道", "有意思", "有趣", "奇怪"],
            "encouraging": ["加油", "努力", "坚持", "相信你", "做得好"],
            "casual": ["嗯", "哦", "对了", "你知道吗", "话说", "其实", "不过", "对啦"],
            "surprised": ["哇", "天哪", "真的吗", "没想到", "太意外了"]
        }

        # 任务完成检测
        self.active_tasks = {}  # 记录用户正在进行的任务

        # 学习反馈系统
        self.corrections = {}  # 记录用户纠正的错误
        self.corrections_file = os.path.join(self.learning_storage, "corrections.json")
        self._load_corrections()

        # 不确定性表达词汇
        self.uncertainty_words = ["可能", "好像", "我记得", "似乎", "大概", "也许", "说不定", "感觉"]

        # 解析用户偏好设置
        self._parse_user_preferences()

        # 加载学习数据
        if self.enable_learning:
            self._load_learning_data()

        # 任务调度器相关
        self.task_semaphore = asyncio.Semaphore(2)  # 限制同时运行的任务数
        self.task_queue = asyncio.Queue()

        # 启动任务调度器
        task = asyncio.create_task(self._task_scheduler())
        self.background_tasks.append(task)

        # 启动日记任务
        if self.enable_diary:
            task = asyncio.create_task(self._diary_task())
            self.background_tasks.append(task)

        # 启动 Web UI（如果启用）
        if self.webui_enabled:
            task = asyncio.create_task(self._start_webui())
            self.background_tasks.append(task)

        # 启动自定义监控任务
        task = asyncio.create_task(self._custom_tasks_task())
        self.background_tasks.append(task)

        # 启动麦克风监听任务
        task = asyncio.create_task(self._mic_monitor_task())
        self.background_tasks.append(task)

    def _sync_all_config(self) -> None:
        """从配置服务同步所有配置到实例属性。"""
        # 同步基础配置
        self.bot_name = self.plugin_config.bot_name
        self.enabled = self.plugin_config.enabled
        self.interaction_mode = self.plugin_config.interaction_mode
        self.check_interval = self.plugin_config.check_interval
        self.trigger_probability = self.plugin_config.trigger_probability
        self.active_time_range = self.plugin_config.active_time_range
        self.watch_mode = self.plugin_config.watch_mode
        self.capture_mode = self.plugin_config.capture_mode
        self.bot_vision_quality = self.plugin_config.bot_vision_quality
        self.image_prompt = self.plugin_config.image_prompt
        self.use_external_vision = self.plugin_config.use_external_vision
        self.vision_api_url = self.plugin_config.vision_api_url
        self.vision_api_key = self.plugin_config.vision_api_key
        self.vision_api_model = self.plugin_config.vision_api_model
        self.user_preferences = self.plugin_config.user_preferences
        self.start_end_mode = self.plugin_config.start_end_mode
        self.start_preset = self.plugin_config.start_preset
        self.end_preset = self.plugin_config.end_preset
        self.start_llm_prompt = self.plugin_config.start_llm_prompt
        self.end_llm_prompt = self.plugin_config.end_llm_prompt
        self.enable_diary = self.plugin_config.enable_diary
        self.diary_time = self.plugin_config.diary_time
        self.diary_storage = self.plugin_config.diary_storage
        self.diary_reference_days = self.plugin_config.diary_reference_days
        self.diary_auto_recall = self.plugin_config.diary_auto_recall
        self.diary_recall_time = self.plugin_config.diary_recall_time
        self.diary_send_as_image = self.plugin_config.diary_send_as_image
        self.diary_generation_prompt = self.plugin_config.diary_generation_prompt
        self.weather_api_key = self.plugin_config.weather_api_key
        self.weather_city = self.plugin_config.weather_city
        self.enable_mic_monitor = self.plugin_config.enable_mic_monitor
        self.mic_threshold = self.plugin_config.mic_threshold
        self.mic_check_interval = self.plugin_config.mic_check_interval
        self.admin_qq = self.plugin_config.admin_qq
        self.proactive_target = self.plugin_config.proactive_target
        self.save_local = self.plugin_config.save_local
        self.custom_tasks = self.plugin_config.custom_tasks
        self.rest_time_range = self.plugin_config.rest_time_range
        self.enable_learning = self.plugin_config.enable_learning
        self.learning_storage = self.plugin_config.learning_storage
        self.interaction_kpi = self.plugin_config.interaction_kpi
        self.debug = self.plugin_config.debug
        # 同步自定义预设配置
        self.custom_presets = self.plugin_config.custom_presets
        self.current_preset_index = self.plugin_config.current_preset_index
        # 解析自定义预设
        self._parse_custom_presets()
        # 确保预设索引有效
        if self.current_preset_index >= len(self.parsed_custom_presets):
            self.current_preset_index = -1
            self.plugin_config.current_preset_index = -1
        # 同步额外配置
        self.observation_storage = self.plugin_config.observation_storage
        self.max_observations = self.plugin_config.max_observations
        self.interaction_frequency = self.plugin_config.interaction_frequency
        self.image_quality = self.plugin_config.image_quality
        self.system_prompt = self.plugin_config.system_prompt

        # 同步 WebUI 配置
        self.webui_enabled = self.plugin_config.webui.enabled
        self.webui_host = self.plugin_config.webui.host
        self.webui_port = self.plugin_config.webui.port
        self.webui_auth_enabled = self.plugin_config.webui.auth_enabled
        self.webui_password = self.plugin_config.webui.password
        self.webui_session_timeout = self.plugin_config.webui.session_timeout

    def _parse_custom_presets(self) -> list:
        """解析自定义预设配置。"""
        self.parsed_custom_presets = []
        if not self.custom_presets:
            return self.parsed_custom_presets
        
        lines = self.custom_presets.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                try:
                    preset = {
                        "name": parts[0].strip(),
                        "check_interval": max(10, int(parts[1].strip())),
                        "trigger_probability": max(0, min(100, int(parts[2].strip())))
                    }
                    self.parsed_custom_presets.append(preset)
                except ValueError:
                    continue
        return self.parsed_custom_presets

    def _get_current_preset_params(self) -> tuple:
        """获取当前预设的参数，如果未使用预设则返回自定义参数。"""
        if self.current_preset_index >= 0 and self.current_preset_index < len(self.parsed_custom_presets):
            preset = self.parsed_custom_presets[self.current_preset_index]
            return preset["check_interval"], preset["trigger_probability"]
        return self.check_interval, self.trigger_probability

    def _ensure_webui_password(self) -> bool:
        """确保 WebUI 密码已设置，自动生成时返回明文密码供用户查看。"""
        # 检查密码是否已设置（非空且非默认值）
        current_password = str(self.plugin_config.webui.password or "").strip()
        # 只有当认证启用且用户明确要求密码保护时才生成密码
        # 如果用户设置了空密码，尊重用户选择，不生成密码
        if (
            self.plugin_config.webui.enabled
            and self.plugin_config.webui.auth_enabled
            and not current_password
            # 新增检查：只有当认证启用且用户没有明确设置空密码时才生成
            # 如果用户在配置中设置了空密码，不生成新密码
        ):
            # 生成随机密码
            generated = f"{secrets.randbelow(1000000):06d}"
            # 存储密码
            self.plugin_config.webui.password = generated
            self.plugin_config.save_webui_config()
            logger.info(f"WebUI 访问密码已自动生成: {generated}")
            logger.info("请在配置中查看或修改此密码")
            return True
        return False

    def _snapshot_webui_runtime(self) -> tuple[bool, str, int, str, int]:
        """获取当前 WebUI 运行态配置快照。"""
        return (
            getattr(self, "webui_enabled", False),
            getattr(self, "webui_host", "0.0.0.0"),
            getattr(self, "webui_port", 8898),
            getattr(self, "webui_password", ""),
            getattr(self, "webui_session_timeout", 3600),
        )

    def _is_webui_runtime_changed(
        self, old_state: tuple[bool, str, int, str, int]
    ) -> bool:
        return old_state != self._snapshot_webui_runtime()

    async def _restart_webui(self) -> None:
        logger.info("检测到 WebUI 配置变更，正在重启 WebUI...")
        if self.web_server:
            await self.web_server.stop()
            self.web_server = None

        if not self.webui_enabled:
            return

        try:
            self.web_server = WebServer(self, host=self.webui_host, port=self.webui_port)
            await self.web_server.start()
        except Exception as e:
            logger.error(f"重启 WebUI 失败: {e}")

    def _apply_plugin_config_updates(self, config_dict: dict) -> None:
        """将更新字典写回 PluginConfig（包含 webui 嵌套字段兼容）。"""
        for k, v in config_dict.items():
            if k == "webui" and isinstance(v, dict):
                current_webui = self.plugin_config.webui
                # 检查是否明确设置了空密码
                password_set_to_empty = "password" in v and not str(v["password"] or "").strip()
                for wk, wv in v.items():
                    # 如果明确设置了空密码，允许更新
                    if wk == "password" and not str(wv or "").strip():
                        # 允许设置空密码
                        setattr(current_webui, wk, wv)
                    else:
                        setattr(current_webui, wk, wv)
                self.plugin_config.save_webui_config()
            elif k.startswith("webui_"):
                # 兼容旧版扁平 key：webui_enabled -> webui.enabled
                wk = k[6:]
                if hasattr(self.plugin_config.webui, wk):
                    # 如果明确设置了空密码，允许更新
                    if wk == "password" and not str(v or "").strip():
                        # 允许设置空密码
                        setattr(self.plugin_config.webui, wk, v)
                    else:
                        setattr(self.plugin_config.webui, wk, v)
                    self.plugin_config.save_webui_config()
            else:
                setattr(self.plugin_config, k, v)

    def _update_config_from_dict(self, config_dict: dict):
        """从配置字典更新插件配置。"""
        if not config_dict:
            return

        try:
            # 使用配置服务更新配置
            if self.plugin_config:
                old_webui_state = self._snapshot_webui_runtime()
                self._apply_plugin_config_updates(config_dict)

                # 统一同步所有配置
                self._sync_all_config()

                # 检查是否明确设置了空密码
                password_set_to_empty = False
                if "webui" in config_dict and isinstance(config_dict["webui"], dict):
                    password_set_to_empty = "password" in config_dict["webui"] and not str(config_dict["webui"]["password"] or "").strip()
                elif "webui_password" in config_dict:
                    password_set_to_empty = not str(config_dict["webui_password"] or "").strip()
                
                # 只有当没有明确设置空密码时，才确保密码已设置
                if not password_set_to_empty and self._ensure_webui_password():
                    self._sync_all_config()

                # 检查 WebUI 配置是否变化并重启
                if self._is_webui_runtime_changed(old_webui_state):
                    self._safe_create_task(self._restart_webui(), name="restart_webui")

                logger.debug("[Config] 配置已更新")
        except Exception as e:
            logger.error(f"更新配置失败: {e}")

    @staticmethod
    def _safe_create_task(coro, *, name: str = "") -> asyncio.Task:
        """创建 asyncio task 并自动记录未处理异常，避免 fire-and-forget 静默吞异常。"""
        task = asyncio.create_task(coro, name=name or None)

        def _on_done(t: asyncio.Task):
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error(f"后台任务 '{t.get_name()}' 异常: {exc}", exc_info=exc)

        task.add_done_callback(_on_done)
        return task

    def _load_observations(self):
        """加载观察记录"""
        try:
            import json
            import os
            observations_file = os.path.join(self.observation_storage, "observations.json")
            if os.path.exists(observations_file):
                with open(observations_file, "r", encoding="utf-8") as f:
                    self.observations = json.load(f)
                    # 确保只保留最新的max_observations条记录
                    if len(self.observations) > self.max_observations:
                        self.observations = self.observations[-self.max_observations:]
        except Exception as e:
            logger.error(f"加载观察记录失败: {e}")
            self.observations = []

    def _save_observations(self):
        """保存观察记录"""
        try:
            import json
            import os
            observations_file = os.path.join(self.observation_storage, "observations.json")
            # 确保只保存最新的max_observations条记录
            if len(self.observations) > self.max_observations:
                self.observations = self.observations[-self.max_observations:]
            with open(observations_file, "w", encoding="utf-8") as f:
                json.dump(self.observations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存观察记录失败: {e}")

    def _add_observation(self, scene, recognition_text, active_window_title):
        """添加观察记录"""
        import datetime
        observation = {
            "timestamp": datetime.datetime.now().isoformat(),
            "scene": scene,
            "window_title": active_window_title,
            "description": recognition_text[:200]  # 只保存前200个字符
        }
        self.observations.append(observation)
        # 确保只保留最新的max_observations条记录
        if len(self.observations) > self.max_observations:
            self.observations = self.observations[-self.max_observations:]
        # 保存到文件
        self._save_observations()

    def _load_diary_metadata(self):
        """加载日记元数据"""
        try:
            import json
            import os
            if os.path.exists(self.diary_metadata_file):
                with open(self.diary_metadata_file, "r", encoding="utf-8") as f:
                    self.diary_metadata = json.load(f)
        except Exception as e:
            logger.error(f"加载日记元数据失败: {e}")
            self.diary_metadata = {}

    def _save_diary_metadata(self):
        """保存日记元数据"""
        try:
            import json
            import os
            with open(self.diary_metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.diary_metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存日记元数据失败: {e}")

    def _update_diary_view_status(self, date_str):
        """更新日记查看状态"""
        import datetime
        if date_str not in self.diary_metadata:
            self.diary_metadata[date_str] = {}
        self.diary_metadata[date_str]["viewed"] = True
        self.diary_metadata[date_str]["viewed_at"] = datetime.datetime.now().isoformat()
        self._save_diary_metadata()
        logger.info(f"更新日记查看状态: {date_str} - 已查看")

    def _load_long_term_memory(self):
        """加载长期记忆"""
        try:
            import json
            import os
            if os.path.exists(self.long_term_memory_file):
                with open(self.long_term_memory_file, "r", encoding="utf-8") as f:
                    self.long_term_memory = json.load(f)
                logger.info("长期记忆加载成功")
        except Exception as e:
            logger.error(f"加载长期记忆失败: {e}")
            self.long_term_memory = {}

    def _save_long_term_memory(self):
        """保存长期记忆"""
        try:
            import json
            import os
            with open(self.long_term_memory_file, "w", encoding="utf-8") as f:
                json.dump(self.long_term_memory, f, ensure_ascii=False, indent=2)
            logger.info("长期记忆保存成功")
        except Exception as e:
            logger.error(f"保存长期记忆失败: {e}")

    def _update_long_term_memory(self, scene, active_window, duration, user_preferences=None):
        """更新长期记忆"""
        import datetime
        today = datetime.date.today().isoformat()
        
        # 初始化记忆结构
        if "applications" not in self.long_term_memory:
            self.long_term_memory["applications"] = {}
        if "scenes" not in self.long_term_memory:
            self.long_term_memory["scenes"] = {}
        if "user_preferences" not in self.long_term_memory:
            self.long_term_memory["user_preferences"] = {
                "music": {},
                "movies": {},
                "food": {},
                "hobbies": {},
                "other": {}
            }
        if "memory_associations" not in self.long_term_memory:
            self.long_term_memory["memory_associations"] = {}
        if "memory_priorities" not in self.long_term_memory:
            self.long_term_memory["memory_priorities"] = {}
        
        # 更新应用使用频率
        app_name = active_window.split(" - ")[-1] if " - " in active_window else active_window
        if app_name not in self.long_term_memory["applications"]:
            self.long_term_memory["applications"][app_name] = {
                "usage_count": 0,
                "total_duration": 0,
                "last_used": today,
                "scenes": {},
                "priority": 0
            }
        
        app_memory = self.long_term_memory["applications"][app_name]
        app_memory["usage_count"] += 1
        app_memory["total_duration"] += duration
        app_memory["last_used"] = today
        
        if scene not in app_memory["scenes"]:
            app_memory["scenes"][scene] = 0
        app_memory["scenes"][scene] += 1
        
        # 更新场景偏好
        if scene not in self.long_term_memory["scenes"]:
            self.long_term_memory["scenes"][scene] = {
                "usage_count": 0,
                "last_used": today,
                "priority": 0
            }
        self.long_term_memory["scenes"][scene]["usage_count"] += 1
        self.long_term_memory["scenes"][scene]["last_used"] = today
        
        # 更新用户偏好（如果提供）
        if user_preferences:
            for category, preferences in user_preferences.items():
                if category not in self.long_term_memory["user_preferences"]:
                    self.long_term_memory["user_preferences"][category] = {}
                for pref, value in preferences.items():
                    if pref not in self.long_term_memory["user_preferences"][category]:
                        self.long_term_memory["user_preferences"][category][pref] = {
                            "count": 0,
                            "last_mentioned": today,
                            "priority": 0
                        }
                    self.long_term_memory["user_preferences"][category][pref]["count"] += 1
                    self.long_term_memory["user_preferences"][category][pref]["last_mentioned"] = today
        
        # 建立记忆关联
        self._build_memory_associations(scene, app_name)
        
        # 更新记忆优先级
        self._update_memory_priorities()
        
        # 应用记忆衰减
        self._apply_memory_decay()
        
        # 保存长期记忆
        self._save_long_term_memory()

    def _apply_memory_decay(self):
        """应用记忆衰减"""
        import datetime
        today = datetime.date.today()
        
        # 对应用记忆应用衰减
        if "applications" in self.long_term_memory:
            for app_name, app_data in list(self.long_term_memory["applications"].items()):
                last_used_date = datetime.date.fromisoformat(app_data["last_used"])
                days_since_used = (today - last_used_date).days
                
                # 记忆衰减：随着时间推移，使用频率和持续时间逐渐降低
                if days_since_used > 0:
                    decay_factor = 0.95 ** days_since_used
                    app_data["usage_count"] = int(app_data["usage_count"] * decay_factor)
                    app_data["total_duration"] = int(app_data["total_duration"] * decay_factor)
                    app_data["priority"] = int(app_data["priority"] * decay_factor)
                    
                    # 如果记忆太弱，删除
                    if app_data["usage_count"] < 1:
                        del self.long_term_memory["applications"][app_name]
        
        # 对场景记忆应用衰减
        if "scenes" in self.long_term_memory:
            for scene_name, scene_data in list(self.long_term_memory["scenes"].items()):
                last_used_date = datetime.date.fromisoformat(scene_data["last_used"])
                days_since_used = (today - last_used_date).days
                
                if days_since_used > 0:
                    decay_factor = 0.95 ** days_since_used
                    scene_data["usage_count"] = int(scene_data["usage_count"] * decay_factor)
                    scene_data["priority"] = int(scene_data["priority"] * decay_factor)
                    
                    if scene_data["usage_count"] < 1:
                        del self.long_term_memory["scenes"][scene_name]
        
        # 对用户偏好应用衰减
        if "user_preferences" in self.long_term_memory:
            for category, preferences in list(self.long_term_memory["user_preferences"].items()):
                for pref, data in list(preferences.items()):
                    last_mentioned_date = datetime.date.fromisoformat(data["last_mentioned"])
                    days_since_mentioned = (today - last_mentioned_date).days
                    
                    if days_since_mentioned > 0:
                        decay_factor = 0.95 ** days_since_mentioned
                        data["count"] = int(data["count"] * decay_factor)
                        data["priority"] = int(data["priority"] * decay_factor)
                        
                        if data["count"] < 1:
                            del preferences[pref]
                
                # 如果类别为空，删除
                if not preferences:
                    del self.long_term_memory["user_preferences"][category]

    def _build_memory_associations(self, scene, app_name):
        """建立记忆关联"""
        import datetime
        # 关联场景和应用
        association_key = f"{scene}_{app_name}"
        if association_key not in self.long_term_memory["memory_associations"]:
            self.long_term_memory["memory_associations"][association_key] = {
                "count": 0,
                "last_occurred": datetime.date.today().isoformat()
            }
        
        self.long_term_memory["memory_associations"][association_key]["count"] += 1
        self.long_term_memory["memory_associations"][association_key]["last_occurred"] = datetime.date.today().isoformat()

    def _update_memory_priorities(self):
        """更新记忆优先级"""
        import datetime
        today = datetime.date.today()
        
        # 更新应用优先级
        if "applications" in self.long_term_memory:
            for app_name, app_data in self.long_term_memory["applications"].items():
                # 基于使用频率和最近使用时间计算优先级
                last_used_date = datetime.date.fromisoformat(app_data["last_used"])
                days_since_used = (today - last_used_date).days
                
                # 优先级 = 使用频率 * (1 / (1 + 天数))
                priority = app_data["usage_count"] * (1 / (1 + days_since_used))
                app_data["priority"] = int(priority)
        
        # 更新场景优先级
        if "scenes" in self.long_term_memory:
            for scene_name, scene_data in self.long_term_memory["scenes"].items():
                last_used_date = datetime.date.fromisoformat(scene_data["last_used"])
                days_since_used = (today - last_used_date).days
                
                priority = scene_data["usage_count"] * (1 / (1 + days_since_used))
                scene_data["priority"] = int(priority)
        
        # 更新用户偏好优先级
        if "user_preferences" in self.long_term_memory:
            for category, preferences in self.long_term_memory["user_preferences"].items():
                for pref, data in preferences.items():
                    last_mentioned_date = datetime.date.fromisoformat(data["last_mentioned"])
                    days_since_mentioned = (today - last_mentioned_date).days
                    
                    priority = data["count"] * (1 / (1 + days_since_mentioned))
                    data["priority"] = int(priority)

    def _trigger_related_memories(self, scene, app_name):
        """触发相关记忆"""
        related_memories = []
        
        # 基于场景触发记忆
        if "scenes" in self.long_term_memory and scene in self.long_term_memory["scenes"]:
            scene_data = self.long_term_memory["scenes"][scene]
            if scene_data["priority"] > 0:
                related_memories.append(f"场景: {scene} (优先级: {scene_data['priority']})")
        
        # 基于应用触发记忆
        if "applications" in self.long_term_memory and app_name in self.long_term_memory["applications"]:
            app_data = self.long_term_memory["applications"][app_name]
            if app_data["priority"] > 0:
                related_memories.append(f"应用: {app_name} (优先级: {app_data['priority']})")
        
        # 基于关联触发记忆
        association_key = f"{scene}_{app_name}"
        if "memory_associations" in self.long_term_memory and association_key in self.long_term_memory["memory_associations"]:
            association_data = self.long_term_memory["memory_associations"][association_key]
            if association_data["count"] > 1:
                related_memories.append(f"关联: {scene} 和 {app_name} (出现次数: {association_data['count']})")
        
        # 基于用户偏好触发记忆
        if "user_preferences" in self.long_term_memory:
            for category, preferences in self.long_term_memory["user_preferences"].items():
                # 按优先级排序
                sorted_prefs = sorted(preferences.items(), key=lambda x: x[1]["priority"], reverse=True)
                # 取前3个高优先级的偏好
                top_prefs = sorted_prefs[:3]
                for pref, data in top_prefs:
                    if data["priority"] > 0:
                        related_memories.append(f"偏好: {category} - {pref} (优先级: {data['priority']})")
        
        return related_memories

    def _add_user_preference(self, category, preference):
        """添加用户偏好"""
        import datetime
        today = datetime.date.today().isoformat()
        
        if "user_preferences" not in self.long_term_memory:
            self.long_term_memory["user_preferences"] = {
                "music": {},
                "movies": {},
                "food": {},
                "hobbies": {},
                "other": {}
            }
        
        if category not in self.long_term_memory["user_preferences"]:
            self.long_term_memory["user_preferences"][category] = {}
        
        if preference not in self.long_term_memory["user_preferences"][category]:
            self.long_term_memory["user_preferences"][category][preference] = {
                "count": 0,
                "last_mentioned": today,
                "priority": 0
            }
        
        self.long_term_memory["user_preferences"][category][preference]["count"] += 1
        self.long_term_memory["user_preferences"][category][preference]["last_mentioned"] = today
        
        # 更新优先级
        self._update_memory_priorities()
        # 保存记忆
        self._save_long_term_memory()
        
        logger.info(f"已添加用户偏好: {category} - {preference}")

    def _detect_task_completion(self, scene, active_window):
        """检测任务完成"""
        import datetime
        task_key = f"{scene}_{active_window}"
        current_time = datetime.datetime.now()
        
        if task_key in self.active_tasks:
            task_info = self.active_tasks[task_key]
            start_time = task_info["start_time"]
            duration = (current_time - start_time).total_seconds() / 60  # 转换为分钟
            
            # 如果任务持续时间超过5分钟，认为可能完成了一项任务
            if duration > 5:
                del self.active_tasks[task_key]
                return True, duration
        
        # 记录新任务
        self.active_tasks[task_key] = {
            "start_time": current_time,
            "scene": scene,
            "window": active_window
        }
        return False, 0

    def _adjust_interaction_frequency(self, user_response):
        """根据用户回应调整互动频率"""
        # 简单的参与度评估：根据回复长度和内容
        response_length = len(user_response)
        
        # 评估用户参与度
        if response_length > 50:
            engagement = min(10, self.user_engagement + 1)
        elif response_length < 10:
            engagement = max(1, self.user_engagement - 1)
        else:
            engagement = self.user_engagement
        
        # 更新参与度历史
        self.engagement_history.append(engagement)
        if len(self.engagement_history) > 10:
            self.engagement_history.pop(0)
        
        # 计算平均参与度
        avg_engagement = sum(self.engagement_history) / len(self.engagement_history)
        self.user_engagement = int(avg_engagement)
        
        # 根据参与度调整互动频率
        # 参与度越高，互动频率越高
        self.interaction_frequency = max(1, min(10, 5 + (self.user_engagement - 5) * 0.5))
        logger.info(f"用户参与度: {self.user_engagement}, 互动频率: {self.interaction_frequency}")

    def _add_emotion_words(self, response):
        """在回复中添加情绪词汇和语气词"""
        import random
        
        # 随机添加语气词
        if random.random() < 0.3:
            casual_words = self.emotion_words.get("casual", [])
            if casual_words:
                casual_word = random.choice(casual_words)
                response = f"{casual_word}，{response}"
        
        # 根据场景添加情绪词汇
        if "编程" in response or "代码" in response:
            if random.random() < 0.4:
                encouraging_words = self.emotion_words.get("encouraging", [])
                if encouraging_words:
                    encouraging_word = random.choice(encouraging_words)
                    response = f"{response}，{encouraging_word}！"
        
        elif "游戏" in response or "玩" in response:
            if random.random() < 0.4:
                happy_words = self.emotion_words.get("happy", [])
                if happy_words:
                    happy_word = random.choice(happy_words)
                    response = f"{happy_word}！{response}"
        
        return response

    async def stop(self):
        """停止插件，清理所有任务"""
        logger.info("停止屏幕伴侣插件，清理所有任务")
        # 停止所有自动任务
        self.is_running = False
        self.state = "inactive"
        
        # 清理自动任务
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
                logger.info(f"任务 {task_id} 已取消")
            except Exception as e:
                logger.error(f"等待任务 {task_id} 停止时出错: {e}")

        self.auto_tasks.clear()
        logger.info("所有自动任务已停止")
        
        # 清理临时任务
        temp_tasks_to_cancel = list(self.temporary_tasks.items())
        for task_id, task in temp_tasks_to_cancel:
            logger.info(f"取消临时任务 {task_id}")
            task.cancel()

        for task_id, task in temp_tasks_to_cancel:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"等待临时任务 {task_id} 停止超时")
            except asyncio.CancelledError:
                logger.info(f"临时任务 {task_id} 已取消")
            except Exception as e:
                logger.error(f"等待临时任务 {task_id} 停止时出错: {e}")

        self.temporary_tasks.clear()
        logger.info("所有临时任务已停止")

        # 停止麦克风监听任务，但保留日记和自定义任务
        self.enable_mic_monitor = False

        # 取消麦克风监听任务，保留日记和自定义任务
        tasks_to_keep = []
        for task in self.background_tasks:
            # 检查任务名称或类型，保留日记和自定义任务
            # 由于无法直接获取任务名称，我们通过重新启动这些任务来实现
            tasks_to_keep.append(task)

        # 取消所有后台任务
        for task in self.background_tasks:
            logger.info("取消后台任务")
            task.cancel()

        for task in self.background_tasks:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("等待后台任务停止超时")
            except asyncio.CancelledError:
                logger.info("后台任务已取消")
            except Exception as e:
                logger.error(f"等待后台任务停止时出错: {e}")

        self.background_tasks.clear()
        logger.info("所有后台任务已停止")
        
        # 重新启动日记和自定义任务
        self.running = True
        task = asyncio.create_task(self._diary_task())
        self.background_tasks.append(task)
        task = asyncio.create_task(self._custom_tasks_task())
        self.background_tasks.append(task)
        logger.info("已重新启动日记和自定义任务")

    def _check_dependencies(self, check_mic=False):
        """检查并尝试导入必要库，避免在初始化时因缺少库导致整个插件加载失败"""
        """参数:
        check_mic: 是否检查麦克风依赖
        """
        missing_libs = []
        try:
            import pyautogui
        except ImportError:
            missing_libs.append("pyautogui")

        try:
            from PIL import Image as PILImage
        except ImportError:
            missing_libs.append("Pillow")

        if (
            sys.platform == "win32"
            and self.capture_mode == "active_window"
        ):
            try:
                import pygetwindow
            except ImportError:
                missing_libs.append("pygetwindow")

        # 检查麦克风监听依赖
        if check_mic and self.enable_mic_monitor:
            try:
                import pyaudio
            except ImportError:
                missing_libs.append("pyaudio")

            try:
                import numpy
            except ImportError:
                missing_libs.append("numpy")

        if missing_libs:
            return (
                False,
                f"缺少必要依赖库: {', '.join(missing_libs)}。请执行: pip install {' '.join(missing_libs)}",
            )
        return True, ""

    def _check_env(self, check_mic=False):
        """检查桌面环境是否可用"""
        """参数:
        check_mic: 是否检查麦克风依赖
        """
        dep_ok, dep_msg = self._check_dependencies(check_mic=check_mic)
        if not dep_ok:
            return False, dep_msg

        try:
            import pyautogui

            # 检查 Linux 环境下的 Display 环境变量
            if sys.platform.startswith("linux"):
                import os

                if not os.environ.get("DISPLAY") and not os.environ.get(
                    "WAYLAND_DISPLAY"
                ):
                    return (
                        False,
                        "检测到 Linux 环境但未发现图形界面显示。请确保在桌面或 X11 转发环境下运行。",
                    )

            # 验证 GUI 权限与屏幕尺寸
            size = pyautogui.size()
            if size[0] <= 0 or size[1] <= 0:
                return False, "获取到的屏幕尺寸异常，请确保程序有权限访问桌面。"

            return True, ""
        except Exception as e:
            return False, f"环境检查异常: {str(e)}"

    async def _get_persona_prompt(self, umo: str = None) -> str:
        """获取框架人格的系统提示词"""
        try:
            if hasattr(self.context, "persona_manager"):
                persona = await self.context.persona_manager.get_default_persona_v3(
                    umo=umo
                )
                if persona and "prompt" in persona:
                    return persona["prompt"]
        except Exception as e:
            logger.debug(f"获取框架人格失败: {e}")
        
        config_prompt = self.system_prompt
        if config_prompt:
            return config_prompt
        return DEFAULT_SYSTEM_PROMPT

    async def _get_start_response(self) -> str:
        """获取开始监控的回复"""
        mode = self.start_end_mode
        if mode == "preset":
            return self.start_preset
        else:
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt()
                    prompt = self.start_llm_prompt
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=prompt, system_prompt=system_prompt),
                        timeout=60.0
                    )
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        return response.completion_text
                except asyncio.TimeoutError:
                    logger.warning("LLM 生成开始回复超时，使用默认回复")
                except Exception as e:
                    logger.warning(f"LLM 生成开始回复失败: {e}，使用默认回复")
            return "知道啦~我会时不时过来看一眼的"

    async def _get_end_response(self) -> str:
        """获取结束监控的回复"""
        mode = self.start_end_mode
        if mode == "preset":
            return self.end_preset
        else:
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt()
                    prompt = self.end_llm_prompt
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=prompt, system_prompt=system_prompt),
                        timeout=60.0
                    )
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        return response.completion_text
                except asyncio.TimeoutError:
                    logger.warning("LLM 生成结束回复超时，使用默认回复")
                except Exception as e:
                    logger.warning(f"LLM 生成结束回复失败: {e}，使用默认回复")
            return "好啦，我不看了～下次再陪你玩！"

    def _generate_diary_image(self, diary_message: str) -> str:
        """生成日记图片，返回临时文件路径"""
        from PIL import Image, ImageDraw, ImageFont
        import tempfile

        font_size = 20
        line_height = int(font_size * 1.8)
        padding = 50
        max_width = 800

        chinese_fonts = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/STZHONGS.TTF",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]

        font = None
        for font_path in chinese_fonts:
            try:
                font = ImageFont.truetype(font_path, font_size)
                test_draw = ImageDraw.Draw(Image.new('RGB', (100, 100)))
                test_draw.text((0, 0), "测试中文", font=font)
                break
            except Exception:
                continue

        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        def get_text_width(text):
            if font:
                return font.getlength(text)
            return len(text) * font_size

        lines = []
        max_text_width = max_width - padding * 2
        title_count = 0  # 统计标题行数
        
        for paragraph in diary_message.split('\n'):
            if not paragraph:
                lines.append('')
                continue

            current_line = ""
            for char in paragraph:
                test_line = current_line + char
                if get_text_width(test_line) <= max_text_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = char
            if current_line:
                lines.append(current_line)
                # 检查是否是标题行
                if current_line.startswith('【') and '日记' in current_line:
                    title_count += 1

        # 计算总高度，为标题行增加额外空间
        title_extra_height = title_count * 4  # 每个标题额外增加4像素
        total_height = padding * 2 + len(lines) * line_height + title_extra_height + 20
        total_height = max(300, total_height)  # 增加最小高度

        image = Image.new('RGB', (max_width, total_height), color=(255, 253, 245))
        draw = ImageDraw.Draw(image)

        draw.rectangle(
            [(padding - 10, padding - 10), (max_width - padding + 10, total_height - padding + 10)],
            outline=(200, 180, 160),
            width=2
        )

        y = padding
        for line in lines:
            if line.startswith('【') and '日记' in line:
                title_font = None
                for font_path in chinese_fonts:
                    try:
                        title_font = ImageFont.truetype(font_path, font_size + 4)
                        break
                    except Exception:
                        continue
                if title_font is None:
                    title_font = font
                draw.text((padding, y), line, fill=(139, 69, 19), font=title_font)
                y += line_height + 4  # 标题行使用更大的行高
            elif line and line[0].isdigit() and '年' in line:
                draw.text((padding, y), line, fill=(100, 100, 100), font=font)
                y += line_height
            else:
                draw.text((padding, y), line, fill=(60, 60, 60), font=font)
                y += line_height

        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image.save(temp_file, format="PNG")
        temp_file.close()

        return temp_file.name

    async def _capture_screen_bytes(self):
        """执行截图并返回字节流和活动窗口标题。"""
        """返回值: (截图字节流, 活动窗口标题)"""

        def _core_task():
            import os
            from PIL import Image

            # 共享目录路径，优先使用环境变量，默认值为/AstrBot/data/screenshots
            import os
            screenshots_dir = os.environ.get("SCREENSHOT_DIR", "/AstrBot/data/screenshots")
            
            # 检查共享目录是否存在
            if not os.path.exists(screenshots_dir):
                logger.error(f"共享目录不存在: {screenshots_dir}")
                # 回退到容器内截图（如果支持）
                try:
                    import pyautogui
                    screenshot = pyautogui.screenshot()
                    if screenshot.mode != "RGB":
                        screenshot = screenshot.convert("RGB")
                    img_byte_arr = io.BytesIO()
                    quality_val = self.image_quality
                    try:
                        quality = max(10, min(100, int(quality_val)))
                    except (ValueError, TypeError):
                        quality = 70
                    screenshot.save(img_byte_arr, format="JPEG", quality=quality)
                    return img_byte_arr.getvalue(), "容器内截图"
                except Exception as e:
                    logger.error(f"容器内截图也失败: {e}")
                    raise
            
            # 获取所有截图文件
            screenshot_files = [f for f in os.listdir(screenshots_dir) if f.startswith("screenshot_") and f.endswith(".jpg")]
            
            if not screenshot_files:
                logger.error("共享目录中没有截图文件")
                # 回退到容器内截图（如果支持）
                try:
                    import pyautogui
                    screenshot = pyautogui.screenshot()
                    if screenshot.mode != "RGB":
                        screenshot = screenshot.convert("RGB")
                    img_byte_arr = io.BytesIO()
                    quality_val = self.image_quality
                    try:
                        quality = max(10, min(100, int(quality_val)))
                    except (ValueError, TypeError):
                        quality = 70
                    screenshot.save(img_byte_arr, format="JPEG", quality=quality)
                    return img_byte_arr.getvalue(), "容器内截图"
                except Exception as e:
                    logger.error(f"容器内截图也失败: {e}")
                    raise
            
            # 按时间戳排序，获取最新的截图
            screenshot_files.sort(key=lambda x: int(x.split("_")[1].split(".")[0]), reverse=True)
            latest_screenshot = screenshot_files[0]
            screenshot_path = os.path.join(screenshots_dir, latest_screenshot)
            
            logger.info(f"使用最新截图: {screenshot_path}")
            
            # 读取截图文件
            try:
                screenshot = Image.open(screenshot_path)
                if screenshot.mode != "RGB":
                    screenshot = screenshot.convert("RGB")
                
                img_byte_arr = io.BytesIO()
                quality_val = self.image_quality
                try:
                    quality = max(10, min(100, int(quality_val)))
                except (ValueError, TypeError):
                    quality = 70
                
                screenshot.save(img_byte_arr, format="JPEG", quality=quality)
                return img_byte_arr.getvalue(), "宿主机截图"
            except Exception as e:
                logger.error(f"读取截图文件失败: {e}")
                # 回退到容器内截图（如果支持）
                try:
                    import pyautogui
                    screenshot = pyautogui.screenshot()
                    if screenshot.mode != "RGB":
                        screenshot = screenshot.convert("RGB")
                    img_byte_arr = io.BytesIO()
                    quality_val = self.image_quality
                    try:
                        quality = max(10, min(100, int(quality_val)))
                    except (ValueError, TypeError):
                        quality = 70
                    screenshot.save(img_byte_arr, format="JPEG", quality=quality)
                    return img_byte_arr.getvalue(), "容器内截图"
                except Exception as e:
                    logger.error(f"容器内截图也失败: {e}")
                    raise

        result = await asyncio.to_thread(_core_task)
        return result

    async def _call_external_vision_api(self, image_bytes: bytes) -> str:
        """调用外接视觉API进行图像分析"""
        import aiohttp

        # 获取配置
        api_url = self.vision_api_url
        api_key = self.vision_api_key
        api_model = self.vision_api_model
        image_prompt = self.image_prompt

        if not api_url:
            logger.error("未配置视觉API地址")
            return "……好像忘了看什么了……"

        # 构建请求数据
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": api_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": image_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_data}"
                            },
                        },
                    ],
                }
            ],
            "stream": False,
        }

        # 构建请求头
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # 重试机制
        max_retries = 3
        retry_delay = 2  # 秒

        for attempt in range(max_retries):
            try:
                # 发送请求 - 添加超时设置
                timeout = aiohttp.ClientTimeout(total=120.0)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        api_url, json=payload, headers=headers
                    ) as response:
                        if response.status == 200:
                            result = await response.json()
                            # 提取识别结果（根据API返回格式调整）
                            if "choices" in result and len(result["choices"]) > 0:
                                choice = result["choices"][0]
                                if "message" in choice and "content" in choice["message"]:
                                    return choice["message"]["content"]
                                elif "text" in choice:
                                    return choice["text"]
                            elif "response" in result:
                                return result["response"]
                            else:
                                return "……头晕晕的，看不太清……"
                        else:
                            error_text = await response.text()
                            logger.error(
                                f"视觉API调用失败 (尝试 {attempt+1}/{max_retries}): {response.status} - {error_text}"
                            )
                            if attempt < max_retries - 1:
                                logger.info(f"等待 {retry_delay} 秒后重试...")
                                await asyncio.sleep(retry_delay)
                                retry_delay *= 2  # 指数退避
                            else:
                                return "……刚才走神了，再来一次？"
            except asyncio.TimeoutError:
                logger.error(f"视觉API调用超时 (尝试 {attempt+1}/{max_retries})，请检查网络连接")
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    return "……网络好像有点卡……再试一次？"
            except Exception as e:
                logger.error(f"调用视觉API异常 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"等待 {retry_delay} 秒后重试...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    return "……刚才晕了一下，再来？"

    def _identify_scene(self, window_title: str) -> str:
        """增强的场景识别"""
        if not window_title:
            return "未知"

        title_lower = window_title.lower()

        # 编程/开发场景
        coding_keywords = [
            "code",
            "vscode",
            "visual studio",
            "intellij",
            "pycharm",
            "idea",
            "eclipse",
            "sublime",
            "atom",
            "notepad++",
            "vim",
            "emacs",
            "netbeans",
            "phpstorm",
            "webstorm",
            "goland",
            "rider",
            "android studio",
            "xcode",
        ]
        if any(keyword in title_lower for keyword in coding_keywords):
            return "编程"

        # 设计场景
        design_keywords = [
            "photoshop",
            "illustrator",
            "figma",
            "sketch",
            "xd",
            "coreldraw",
            "gimp",
            "inkscape",
            "blender",
            "maya",
            "3ds max",
            "c4d",
            "after effects",
            "premiere",
            "audition",
        ]
        if any(keyword in title_lower for keyword in design_keywords):
            return "设计"

        # 浏览器场景
        browser_keywords = [
            "chrome",
            "firefox",
            "edge",
            "safari",
            "opera",
            "browser",
            "浏览器",
        ]
        if any(keyword in title_lower for keyword in browser_keywords):
            return "浏览"

        # 办公场景
        office_keywords = [
            "word",
            "excel",
            "powerpoint",
            "office",
            "文档",
            "表格",
            "演示",
            "outlook",
            "onenote",
            "wps",
        ]
        if any(keyword in title_lower for keyword in office_keywords):
            return "办公"

        # 游戏场景
        game_keywords = [
            "game",
            "游戏",
            "steam",
            "battle.net",
            "epic",
            "origin",
            "uplay",
            "gog",
            "minecraft",
            "league of legends",
            "valorant",
            "csgo",
            "dota",
            "fortnite",
            "pubg",
            "apex",
            "overwatch",
            "call of duty",
            "fifa",
            "nba",
            "f1",
            "assassin's creed",
            "grand theft auto",
            "the witcher",
            "cyberpunk",
            "red dead redemption",
        ]
        if any(keyword in title_lower for keyword in game_keywords):
            return "游戏"

        # 视频场景
        video_keywords = [
            "youtube",
            "bilibili",
            "视频",
            "movie",
            "film",
            "player",
            "vlc",
            "potplayer",
            "media player",
            "netflix",
            "hulu",
            "disney+",
            "prime video",
        ]
        if any(keyword in title_lower for keyword in video_keywords):
            return "视频"

        # 阅读场景
        reading_keywords = [
            "novel",
            "小说",
            "comic",
            "漫画",
            "reader",
            "阅读器",
            "ebook",
            "电子书",
            "pdf",
            "word",
            "文档",
            "reading",
            "阅读",
        ]
        if any(keyword in title_lower for keyword in reading_keywords):
            return "阅读"

        # 音乐场景
        music_keywords = [
            "spotify",
            "apple music",
            "music",
            "itunes",
            "网易云音乐",
            "qq音乐",
            "酷狗音乐",
            "酷我音乐",
            "foobar2000",
            "winamp",
        ]
        if any(keyword in title_lower for keyword in music_keywords):
            return "音乐"

        # 聊天场景
        chat_keywords = [
            "wechat",
            "qq",
            "discord",
            "slack",
            "teams",
            "skype",
            "whatsapp",
            "telegram",
            "signal",
            "messenger",
        ]
        if any(keyword in title_lower for keyword in chat_keywords):
            return "聊天"

        # 终端/命令行场景
        terminal_keywords = [
            "terminal",
            "cmd",
            "powershell",
            "bash",
            "zsh",
            "command prompt",
            "git bash",
            "wsl",
            "ubuntu",
            "debian",
            "centos",
        ]
        if any(keyword in title_lower for keyword in terminal_keywords):
            return "终端"

        # 邮件场景
        email_keywords = ["outlook", "gmail", "mail", "邮件", "thunderbird", "mailbird"]
        if any(keyword in title_lower for keyword in email_keywords):
            return "邮件"

        return "未知"

    def _get_time_prompt(self) -> str:
        """获取时间感知提示词"""
        now = datetime.datetime.now()
        hour = now.hour

        if 6 <= hour < 12:
            return "现在是早上，用户可能刚开始一天的活动。请提供早上的问候和鼓励。"
        elif 12 <= hour < 18:
            return "现在是下午，用户可能在工作或学习。请根据场景提供相应的互动。"
        elif 18 <= hour < 22:
            return "现在是晚上，用户可能在放松或娱乐。请提供轻松的互动。"
        else:
            return "现在是深夜，用户可能应该休息了。请提醒用户注意休息，不要熬夜。"

    def _get_holiday_prompt(self) -> str:
        """获取节假日提示词"""
        now = datetime.datetime.now()
        date = now.date()
        month = date.month
        day = date.day

        # 常见节假日
        holidays = {
            (1, 1): "今天是元旦节，新年快乐！",
            (2, 14): "今天是情人节，祝你节日快乐！",
            (3, 8): "今天是妇女节，向所有女性致敬！",
            (5, 1): "今天是劳动节，辛苦了！",
            (6, 1): "今天是儿童节，保持童心！",
            (9, 10): "今天是教师节，感谢老师的辛勤付出！",
            (10, 1): "今天是国庆节，祝福祖国繁荣昌盛！",
            (12, 25): "今天是圣诞节，节日快乐！",
        }

        if (month, day) in holidays:
            holiday_prompt = holidays[(month, day)]
            logger.info(f"识别到节假日: {holiday_prompt}")
            return holiday_prompt
        return ""

    def _get_system_status_prompt(self) -> tuple:
        """获取系统状态提示词"""
        system_prompt = ""
        system_high_load = False
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            
            # 电池状态检测
            battery = psutil.sensors_battery()
            if battery and battery.percent < 20:
                system_prompt += "电池电量较低，建议及时充电。"

            if cpu_percent > 80 or memory_percent > 80:
                if system_prompt:
                    system_prompt += " "
                system_prompt += "系统资源使用较高，建议休息一下，让电脑也放松放松。"
                system_high_load = True
                logger.info(
                    f"系统资源使用较高: CPU={cpu_percent}%, 内存={memory_percent}%"
                )
        except ImportError:
            logger.debug("未安装psutil库，跳过系统状态检测")
        except Exception as e:
            logger.debug(f"系统状态检测失败: {e}")
        return system_prompt, system_high_load

    async def _get_weather_prompt(self) -> str:
        """获取天气提示词"""
        weather_prompt = ""
        weather_api_key = self.weather_api_key
        weather_city = self.weather_city

        if weather_api_key and weather_city:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    url = f"http://api.openweathermap.org/data/2.5/weather?q={weather_city}&appid={weather_api_key}&units=metric&lang=zh_cn"
                    async with session.get(url) as response:
                        if response.status == 200:
                            weather_data = await response.json()
                            weather_main = weather_data.get("weather", [{}])[0].get(
                                "main", ""
                            )
                            weather_desc = weather_data.get("weather", [{}])[0].get(
                                "description", ""
                            )
                            temp = weather_data.get("main", {}).get("temp", 0)

                            if weather_main:
                                weather_prompt = (
                                    f"当前天气：{weather_desc}，温度 {temp}°C。"
                                )
                                logger.info(f"获取天气信息成功: {weather_prompt}")
                        else:
                            logger.debug(f"获取天气信息失败: {response.status}")
            except Exception as e:
                logger.debug(f"天气感知失败: {e}")
        return weather_prompt

    async def _analyze_screen(
        self,
        image_bytes: bytes,
        session=None,
        active_window_title: str = "",
        custom_prompt: str = "",
        task_id: str = "unknown",
    ) -> list[BaseMessageComponent]:
        """使用外接视觉API进行图像分析，然后通过AstrBot的LLM进行人格化回复"""
        # 在调用视觉API之前再次检查活跃时间段
        if not self._is_in_active_time_range():
            logger.info(
                f"[任务 {task_id}] 不在活跃时间段内，取消视觉API调用以节省token"
            )
            return [Plain("现在不是我活跃的时间呢，让我休息一下~")]

        provider = self.context.get_using_provider()
        if not provider:
            logger.debug("未检测到已启用的 LLM 提供商")
            return [Plain("未检测到已启用的 LLM 提供商，无法进行视觉分析。")]

        umo = None
        if session and hasattr(session, "unified_msg_origin"):
            umo = session.unified_msg_origin
        
        system_prompt = await self._get_persona_prompt(umo)
        logger.info(f"[任务 {task_id}] 使用人格设定")

        debug_mode = self.debug

        # 预处理：获取各种提示词（非核心功能，失败不影响主流程）
        scene = "未知"
        scene_prompt = ""
        time_prompt = ""
        holiday_prompt = ""
        system_status_prompt = ""
        weather_prompt = ""

        # 场景识别
        if active_window_title:
            try:
                if debug_mode:
                    logger.info(f"识别到活动窗口: {active_window_title}")
                scene = self._identify_scene(active_window_title)
                # 获取场景偏好
                scene_prompt = self._get_scene_preference(scene)
                if debug_mode:
                    logger.info(f"识别场景: {scene}, 场景偏好: {scene_prompt}")
            except Exception as e:
                if debug_mode:
                    logger.debug(f"场景识别失败: {e}")

        # 获取时间提示
        try:
            time_prompt = self._get_time_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"时间感知失败: {e}")

        # 获取节假日提示
        try:
            holiday_prompt = self._get_holiday_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"节假日识别失败: {e}")

        # 获取系统状态提示
        try:
            system_status_prompt, system_high_load = self._get_system_status_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"系统状态检测失败: {e}")

        # 获取天气提示
        try:
            weather_prompt = await self._get_weather_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"天气感知失败: {e}")

        if debug_mode:
            logger.info(f"识别场景: {scene}, 时间提示: {time_prompt}")

        # 核心功能：屏幕识别和LLM交互
        try:
            base64_data = base64.b64encode(image_bytes).decode("utf-8")

            if debug_mode:
                logger.info("开始调用外接视觉API进行屏幕分析")
                logger.debug(f"System prompt: {system_prompt}")
                logger.debug(f"Image size: {len(image_bytes)} bytes")
                logger.debug(f"Base64 data length: {len(base64_data)} characters")

            # 第一阶段：使用外接视觉API识别屏幕内容
            if debug_mode:
                logger.info("使用外接视觉API进行屏幕识别")
            recognition_text = await self._call_external_vision_api(image_bytes)
            if debug_mode:
                logger.info(f"外接API识别结果: {recognition_text}")

            # 第二阶段：基于识别结果通过AstrBot的LLM进行人格化回复
            # 尝试获取对话历史，提供更连贯的交互
            contexts = []
            try:
                if hasattr(self.context, "conversation_manager"):
                    conv_mgr = self.context.conversation_manager
                    # 安全获取uid，处理session可能无效的情况
                    uid = ""
                    try:
                        uid = session.unified_msg_origin if session else ""
                    except Exception as e:
                        logger.debug(f"获取session uid失败: {e}")
                    if uid:
                        try:
                            curr_cid = await conv_mgr.get_curr_conversation_id(uid)
                            if curr_cid:
                                conversation = await conv_mgr.get_conversation(
                                    uid, curr_cid
                                )
                                if conversation and conversation.history:
                                    # 提取最近的对话历史（最多5条）
                                    recent_history = conversation.history[-5:]
                                    for msg in recent_history:
                                        if msg.get("role") == "user":
                                            contexts.append(msg.get("content", ""))
                                        elif msg.get("role") == "assistant":
                                            contexts.append(msg.get("content", ""))
                        except Exception as e:
                            logger.debug(f"获取对话历史失败: {e}")
            except Exception as e:
                logger.debug(f"获取对话历史失败: {e}")

            # 添加观察记录
            self._add_observation(scene, recognition_text, active_window_title)
            
            # 构建交互提示词
            interaction_prompt = f"用户的屏幕显示：{recognition_text}。"
            if custom_prompt:
                interaction_prompt += f" {custom_prompt}"
                if debug_mode:
                    logger.info(f"使用自定义提示词: {custom_prompt}")
            else:
                if scene_prompt:
                    interaction_prompt += f" {scene_prompt}"
                if time_prompt:
                    interaction_prompt += f" {time_prompt}"
                if holiday_prompt:
                    interaction_prompt += f" {holiday_prompt}"
                if weather_prompt:
                    interaction_prompt += f" {weather_prompt}"
                if system_status_prompt:
                    interaction_prompt += f" {system_status_prompt}"
            
            # 触发相关记忆
            related_memories = self._trigger_related_memories(scene, active_window_title)
            if related_memories:
                memory_text = "\n相关记忆："
                for memory in related_memories[:5]:  # 最多显示5个记忆
                    memory_text += f"\n- {memory}"
                interaction_prompt += memory_text
            
            # 注入之前的观察记录
            if self.observations:
                recent_observations = self.observations[-self.max_observations:][::-1]  # 最近的记录在后面
                observation_text = "\n最近的观察记录："
                for obs in recent_observations:
                    observation_text += f"\n- {obs['timestamp'].split('T')[1][:5]} {obs['scene']}: {obs['description']}"
                interaction_prompt += observation_text
            
            if scene == "视频" or scene == "阅读":
                interaction_prompt += f" 请对屏幕内容进行深度分析和思考，对剧情发展、人物关系或主题意义进行猜想和分析。可以提出创意性的见解，预测未来可能的发展方向，或者探讨内容背后的深层含义。最多输出四句话，最好在三句话内完成回复。"
            else:
                interaction_prompt += f" 请直接给出你的评论或互动，不要添加任何引言或开场白。要具体提及屏幕上的内容，针对用户正在进行的操作提供相关的互动。最多输出三句话，最好在两句话内完成回复。"

            # 如果有对话历史，添加到提示词中
            if contexts:
                history_str = "\n最近的对话:\n" + "\n".join(contexts)
                interaction_prompt += history_str

            # 添加超时设置，避免LLM调用卡住
            try:
                interaction_response = await asyncio.wait_for(
                    provider.text_chat(
                        prompt=interaction_prompt, system_prompt=system_prompt
                    ),
                    timeout=60.0  # 60秒超时
                )
            except asyncio.TimeoutError:
                logger.error("LLM调用超时，请检查网络连接和API响应速度")
                return [Plain("分析超时，请稍后再试")]

            # 提取互动回复
            response_text = "我看不太清你的屏幕内容呢。"
            if (
                interaction_response
                and hasattr(interaction_response, "completion_text")
                and interaction_response.completion_text
            ):
                response_text = interaction_response.completion_text
                if debug_mode:
                    logger.info(f"互动回复: {response_text}")
            else:
                if debug_mode:
                    logger.warning("LLM 未返回有效互动回复")
            
            # 检测任务完成并给予鼓励
            task_completed, duration = self._detect_task_completion(scene, active_window_title)
            if task_completed:
                # 添加鼓励性词汇
                import random
                encouraging_words = self.emotion_words.get("encouraging", [])
                if encouraging_words:
                    encouraging_word = random.choice(encouraging_words)
                    response_text = f"{encouraging_word}！你完成了一项任务，真棒！" + " " + response_text
            
            # 更新长期记忆
            self._update_long_term_memory(scene, active_window_title, 1)  # 假设每次互动持续1分钟
            
            # 在回复中添加情绪词汇和语气词
            response_text = self._add_emotion_words(response_text)
            
            # 添加不确定性表达
            response_text = self._add_uncertainty(response_text)
            
            # 调整互动频率（模拟用户回应，实际应根据真实回应调整）
            # 这里使用一个简单的模拟，实际应用中应根据用户的真实回复调整
            self._adjust_interaction_frequency(response_text)

        except Exception as e:
            logger.error(f"核心功能失败: {e}")
            # 如果核心功能失败，返回一个符合角色的默认回复
            error_msg = str(e)
            error_type = "unknown"
            error_text = ""
            
            if "timeout" in error_msg.lower() or "超时" in error_msg:
                error_type = "timeout"
                error_text = "……刚才好像走神了，再来一次？"
            elif "api" in error_msg.lower() or "api" in error_msg:
                error_type = "api"
                error_text = "看不清呢……眼睛有点花……"
            elif "vision" in error_msg.lower():
                error_type = "vision"
                error_text = "晕乎乎的……刚才看到什么了？"
            else:
                error_type = "unknown"
                error_text = "……刚才有点困了，再试一次？"
            
            # 添加日记条目时标记错误类型
            self._add_diary_entry(f"[错误-{error_type}] " + error_text, active_window_title)
            
            return [Plain(error_text)]

        # 保存截图到临时文件
        # 创建临时文件，使用uuid生成唯一文件名
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"screen_shot_{uuid.uuid4()}.jpg")

        # 将base64数据写入临时文件
        with open(temp_file_path, "wb") as f:
            f.write(base64.b64decode(base64_data))

        # 保存截图到本地（如果配置启用）
        if self.save_local:
            try:
                # 确保data目录存在
                data_dir = StarTools.get_data_dir()
                data_dir.mkdir(parents=True, exist_ok=True)

                # 保存截图到data目录
                screenshot_path = str(data_dir / "screen_shot_latest.jpg")
                shutil.copy2(temp_file_path, screenshot_path)
                if debug_mode:
                    logger.info(f"截图已保存到: {screenshot_path}")
            except Exception as e:
                logger.error(f"保存截图失败: {e}")

        try:
            return [Plain(response_text), Image(file=temp_file_path)]
        finally:
            # 发送完成后删除临时文件
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
                    if debug_mode:
                        logger.debug(f"临时文件已删除: {temp_file_path}")
            except Exception as e:
                logger.error(f"删除临时文件失败: {e}")

    @filter.command("kp")
    async def kp(self, event: AstrMessageEvent):
        """立即截取当前屏幕并进行点评。"""
        # 保持原有功能不变，只是修改指令名称
        ok, err_msg = self._check_env()
        if not ok:
            yield event.plain_result(f"⚠️ 无法使用屏幕观察：\n{err_msg}")
            return

        debug_mode = self.debug
        try:
            if debug_mode:
                logger.info("开始截图")
            # 添加超时机制，避免截图过程卡住
            image_bytes, active_window_title = await asyncio.wait_for(
                self._capture_screen_bytes(), timeout=10.0
            )
            if debug_mode:
                logger.info(
                    f"截图完成，大小: {len(image_bytes)} bytes, 活动窗口: {active_window_title}"
                )

            if debug_mode:
                logger.info("[手动任务] 开始分析屏幕")
            # 添加超时机制，避免分析过程卡住
            components = await asyncio.wait_for(
                self._analyze_screen(
                    image_bytes,
                    session=event,
                    active_window_title=active_window_title,
                    task_id="manual",
                ),
                timeout=120.0,
            )
            if debug_mode:
                logger.info(f"分析完成，组件数量: {len(components)}")

            # 提取屏幕识别结果并写入日志
            if components and isinstance(components[0], Plain):
                screen_result = components[0].text
                if debug_mode:
                    logger.info(f"屏幕识别结果: {screen_result}")
                # 自动分段发送消息
                segments = self._split_message(screen_result)

                # 参考 splitter 插件的实现，逐段发送
                if len(segments) > 1:
                    # 发送前 N-1 段
                    for i in range(len(segments) - 1):
                        segment = segments[i]
                        if segment.strip():
                            await self.context.send_message(
                                event.unified_msg_origin, MessageChain([Plain(segment)])
                            )
                            # 添加小延迟，使回复更自然
                            await asyncio.sleep(0.5)
                    # 最后一段通过 yield 交给框架处理
                    if segments[-1].strip():
                        yield event.plain_result(segments[-1])
                else:
                    # 只有一段，直接交给框架处理
                    yield event.plain_result(screen_result)
                if debug_mode:
                    logger.info(f"已发送识别结果，共 {len(segments)} 段")

                # 尝试将消息添加到对话历史
                try:
                    from astrbot.core.agent.message import (
                        AssistantMessageSegment,
                        TextPart,
                        UserMessageSegment,
                    )

                    # 获取对话管理器
                    if hasattr(self.context, "conversation_manager"):
                        conv_mgr = self.context.conversation_manager
                        uid = event.unified_msg_origin
                        curr_cid = await conv_mgr.get_curr_conversation_id(uid)

                        if curr_cid:
                            # 创建用户消息和助手消息
                            user_msg = UserMessageSegment(
                                content=[TextPart(text="/kp")]
                            )
                            assistant_msg = AssistantMessageSegment(
                                content=[TextPart(text=screen_result)]
                            )

                            # 添加消息对到对话历史
                            await conv_mgr.add_message_pair(
                                cid=curr_cid,
                                user_message=user_msg,
                                assistant_message=assistant_msg,
                            )
                            if debug_mode:
                                logger.info("已将消息添加到对话历史")
                except Exception as e:
                    if debug_mode:
                        logger.debug(f"添加对话历史失败: {e}")
            else:
                if debug_mode:
                    logger.warning("未获取到有效识别结果")
                yield event.plain_result("未获取到有效识别结果")

            if debug_mode:
                logger.info("处理完成")
        except asyncio.TimeoutError:
            logger.error("操作超时，请检查系统资源和网络连接")
            yield event.plain_result("操作超时，请检查系统资源和网络连接")
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            import traceback

            logger.error(traceback.format_exc())
            yield event.plain_result("发送消息失败，请检查日志")

    @filter.command("kps")
    async def kps(self, event: AstrMessageEvent):
        """切换自动观察任务状态"""
        if self.state == "active":
            # 从活动状态切换到非活动状态
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
                    logger.info(f"任务 {task_id} 已取消")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

            self.auto_tasks.clear()
            logger.info("所有自动观察任务已停止")
            end_response = await self._get_end_response()
            yield event.plain_result(end_response)
        else:
            # 从非活动状态切换到活动状态
            if not self.enabled:
                yield event.plain_result(
                    "自动截图互动功能未在配置中启用，请先在配置文件中开启该选项。"
                )
                return

            ok, err_msg = self._check_env(check_mic=False)
            if not ok:
                yield event.plain_result(f"启动失败：\n{err_msg}")
                return

            # 检查是否已有自动化任务
            if self.AUTO_TASK_ID in self.auto_tasks or self.is_running:
                logger.info("自动化任务已存在，无需重复启动")
                return

            self.state = "active"
            self.is_running = True
            logger.info(f"启动任务 {self.AUTO_TASK_ID}")
            self.auto_tasks[self.AUTO_TASK_ID] = asyncio.create_task(
                self._auto_screen_task(event, task_id=self.AUTO_TASK_ID)
            )
            start_response = await self._get_start_response()
            yield event.plain_result(start_response)

    @filter.command_group("kpi")
    def kpi_group(self):
        """管理自动观察屏幕任务"""
        pass

    @filter.command("kpi")
    async def kpi_preset_switch(self, event: AstrMessageEvent, preset_index: int = None):
        """切换预设 /kpi [预设序号]"""
        if preset_index is None:
            async for result in self.kpi_presets(event):
                yield result
            return
        
        try:
            preset_index = int(preset_index)
        except ValueError:
            yield event.plain_result("预设序号必须是数字。")
            return
        
        if preset_index < 0:
            self.current_preset_index = -1
            self.plugin_config.current_preset_index = -1
            yield event.plain_result("✅ 已切换到手动配置模式")
            return
        
        if preset_index >= len(self.parsed_custom_presets):
            yield event.plain_result(
                f"预设{preset_index}不存在。\n"
                f"当前有 {len(self.parsed_custom_presets)} 个预设。\n"
                f"用法: /kpi y [序号] [间隔] [概率] 添加预设"
            )
            return
        
        self.current_preset_index = preset_index
        self.plugin_config.current_preset_index = preset_index
        
        if preset_index < len(self.parsed_custom_presets):
            preset = self.parsed_custom_presets[preset_index]
            yield event.plain_result(
                f"✅ 已切换到预设{preset_index}：{preset['name']}，{preset['check_interval']}秒间隔，{preset['trigger_probability']}%触发概率"
            )
        else:
            yield event.plain_result(f"预设{preset_index}不存在。")

    @kpi_group.command("start")
    async def kpi_start(self, event: AstrMessageEvent):
        """启动自动观察任务"""
        if not self.enabled:
            yield event.plain_result(
                "自动截图互动功能未在配置中启用，请先在配置文件中开启该选项。"
            )
            return

        ok, err_msg = self._check_env(check_mic=False)
        if not ok:
            yield event.plain_result(f"启动失败：\n{err_msg}")
            return

        # 检查是否已有自动化任务
        if self.AUTO_TASK_ID in self.auto_tasks:
            logger.info("自动化任务已存在，无需重复启动")
            return

        # 设置为活动状态
        self.state = "active"
        self.is_running = True
        logger.info(f"启动任务 {self.AUTO_TASK_ID}")
        self.auto_tasks[self.AUTO_TASK_ID] = asyncio.create_task(
            self._auto_screen_task(event, task_id=self.AUTO_TASK_ID)
        )
        start_response = await self._get_start_response()
        yield event.plain_result(f"✅ 已启动任务 {self.AUTO_TASK_ID}，{start_response}")

    @kpi_group.command("stop")
    async def kpi_stop(self, event: AstrMessageEvent, task_id: str = None):
        """停止自动观察任务"""
        if task_id:
            if task_id in self.auto_tasks:
                logger.info(f"取消任务 {task_id}")
                task = self.auto_tasks[task_id]
                task.cancel()

                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(f"等待任务 {task_id} 停止超时")
                except asyncio.CancelledError:
                    logger.info(f"任务 {task_id} 已取消")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

                del self.auto_tasks[task_id]
                if not self.auto_tasks:
                    self.is_running = False
                    # 所有任务停止，设置为非活动状态
                    self.state = "inactive"
                yield event.plain_result(f"已停止任务 {task_id}。")
            else:
                yield event.plain_result(f"任务 {task_id} 不存在。")
        else:
            logger.info("正在停止所有自动观察任务...")
            self.is_running = False
            # 设置为非活动状态
            self.state = "inactive"

            # 停止所有自动任务（只停止自动化任务，不停止临时任务）
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
                    logger.info(f"任务 {task_id} 已取消")
                except Exception as e:
                    logger.error(f"等待任务 {task_id} 停止时出错: {e}")

            self.auto_tasks.clear()
            logger.info("所有自动观察任务已停止")
            end_response = await self._get_end_response()
            yield event.plain_result(end_response)

    @kpi_group.command("list")
    async def kpi_list(self, event: AstrMessageEvent):
        """列出所有运行中的任务"""
        if not self.auto_tasks:
            yield event.plain_result("当前没有正在运行的任务。")
        else:
            msg = "当前运行的任务：\n"
            for task_id in self.auto_tasks:
                msg += f"- {task_id}\n"
            yield event.plain_result(msg)

    @kpi_group.command("y")
    async def kpi_y(self, event: AstrMessageEvent, preset_index: int = None, interval: int = None, probability: int = None):
        """添加或修改自定义预设 /kpi y [预设序号] [间隔秒数] [触发概率]"""
        if preset_index is None:
            yield event.plain_result(
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30 表示设置预设1为90秒间隔30%概率触发"
            )
            return
        
        if interval is None or probability is None:
            yield event.plain_result(
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30 表示设置预设1为90秒间隔30%概率触发"
            )
            return
        
        if preset_index < 0:
            yield event.plain_result("预设序号不能为负数。")
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
            f"✅ 已设置预设{preset_index}：{interval}秒检查一次，{probability}%概率触发窥屏"
        )

    @kpi_group.command("presets")
    async def kpi_presets(self, event: AstrMessageEvent):
        """列出所有自定义预设 /kpi presets"""
        if not self.parsed_custom_presets:
            yield event.plain_result(
                "当前没有设置任何自定义预设。\n"
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30"
            )
            return
        
        msg = "当前自定义预设：\n"
        for i, preset in enumerate(self.parsed_custom_presets):
            current_marker = ""
            if i == self.current_preset_index:
                current_marker = " ← 当前使用"
            msg += f"{i}. {preset['name']}: {preset['check_interval']}秒间隔, {preset['trigger_probability']}%触发概率{current_marker}\n"
        
        msg += f"\n当前使用: {'预设' + str(self.current_preset_index) if self.current_preset_index >= 0 else '手动配置'}"
        msg += f"\n切换预设: /kpi [预设序号] (如 /kpi 0)"
        yield event.plain_result(msg)

    @kpi_group.command("p")
    async def kpi_p(self, event: AstrMessageEvent):
        """列出所有自定义预设（简化版）/kpi p"""
        async for result in self.kpi_presets(event):
            yield result

    @kpi_group.command("add")
    async def kpi_add(self, event: AstrMessageEvent, interval: int, *prompt):
        """添加自定义观察任务"""
        # 检查enabled配置
        if not self.enabled:
            yield event.plain_result(
                "自动截图互动功能未在配置中启用，请先在配置文件中开启该选项。"
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
                f"✅ 已添加自定义任务 {task_id}，每 {interval} 秒执行一次。"
            )
        except ValueError:
            yield event.plain_result("用法: /kpi add [间隔秒数] [自定义提示词]")

    @kpi_group.command("diary")
    async def kpi_diary(self, event: AstrMessageEvent, date: str = None):
        """查看特定日期的日记 /kpi diary [YYYY-MM-DD]"""
        async for result in self._handle_diary_command(event, date):
            yield result

    @kpi_group.command("d")
    async def kpi_d(self, event: AstrMessageEvent, date: str = None):
        """查看特定日期的日记（简化版） /kpi d [YYYYMMDD]"""
        async for result in self._handle_diary_command(event, date):
            yield result

    async def _handle_diary_command(self, event: AstrMessageEvent, date: str = None):
        """处理日记查看命令"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("日记功能未启用，请在配置中开启。")
            return

        # 确定要查看的日期
        if date:
            try:
                # 支持两种日期格式：YYYY-MM-DD 和 YYYYMMDD
                date_str = str(date)
                if len(date_str) == 8 and date_str.isdigit():
                    target_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                else:
                    target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                yield event.plain_result(
                    "日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD 格式，例如：/kpi d 20260302"
                )
                return
        else:
            target_date = datetime.date.today()

        # 构建日记文件路径
        diary_filename = f"diary_{target_date.strftime('%Y%m%d')}.md"
        diary_path = os.path.join(self.diary_storage, diary_filename)

        if not os.path.exists(diary_path):
            yield event.plain_result(
                f"未找到 {target_date.strftime('%Y年%m月%d日')} 的日记。"
            )
            return

        try:
            with open(diary_path, encoding="utf-8") as f:
                diary_content = f.read()
            
            # 更新日记查看状态
            date_str = target_date.strftime("%Y%m%d")
            self._update_diary_view_status(date_str)

            # 提取感想部分
            summary_start = diary_content.find("## 今日感想")
            if summary_start != -1:
                summary_content = diary_content[summary_start:]
                # 提取感想文本，去除标题
                summary_lines = summary_content.split('\n')
                summary_text = '\n'.join(summary_lines[2:]).strip()
                # 限制在500字以下
                if len(summary_text) > 500:
                    summary_text = summary_text[:497] + "..."
                diary_message = f"【{self.bot_name}的日记】\n{target_date.strftime('%Y年%m月%d日')}\n\n{summary_text}"
            else:
                # 尝试提取旧格式的总结部分
                summary_start = diary_content.find(f"## {self.bot_name}的总结")
                if summary_start == -1:
                    summary_start = diary_content.find("## 总结")
                if summary_start != -1:
                    summary_content = diary_content[summary_start:]
                    # 提取总结文本，去除标题
                    summary_lines = summary_content.split('\n')
                    summary_text = '\n'.join(summary_lines[2:]).strip()
                    # 限制在500字以下
                    if len(summary_text) > 500:
                        summary_text = summary_text[:497] + "..."
                    diary_message = f"【{self.bot_name}的日记】\n{target_date.strftime('%Y年%m月%d日')}\n\n{summary_text}"
                else:
                    # 尝试从今日观察部分开始提取
                    observation_start = diary_content.find("## 今日观察")
                    if observation_start != -1:
                        observation_content = diary_content[observation_start:]
                        # 提取观察文本，去除标题
                        observation_lines = observation_content.split('\n')
                        observation_text = '\n'.join(observation_lines[2:]).strip()
                        # 限制在500字以下
                        if len(observation_text) > 500:
                            observation_text = observation_text[:497] + "..."
                        diary_message = f"【{self.bot_name}的日记】\n{target_date.strftime('%Y年%m月%d日')}\n\n{observation_text}"
                    else:
                        # 如果没有任何结构化部分，使用空内容
                        diary_message = f"【{self.bot_name}的日记】\n{target_date.strftime('%Y年%m月%d日')}\n\n今天没有记录。"

            # 检查是否需要自动撤回
            if self.diary_auto_recall:
                logger.info(f"日记消息将在 {self.diary_recall_time} 秒后自动撤回")

                # 启动自动撤回任务
                async def recall_message():
                    await asyncio.sleep(self.diary_recall_time)
                    try:
                        logger.info(
                            f"日记消息已达到自动撤回时间: {self.diary_recall_time}秒"
                        )
                    except Exception as e:
                        logger.error(f"自动撤回日志记录失败: {e}")

                # 创建并保存撤回任务
                task = asyncio.create_task(recall_message())
                self.background_tasks.append(task)

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

            # 同时生成日记被偷看的回应（异步进行）
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
                                MessageChain([Plain("喂！你怎么偷看人家的日记啦？真是的...")])
                            )
                    except Exception as e:
                        logger.error(f"生成日记被偷看回应失败: {e}")
                        await self.context.send_message(
                            event.unified_msg_origin, 
                            MessageChain([Plain("喂！你怎么偷看人家的日记啦？真是的...")])
                        )
                else:
                    await self.context.send_message(
                        event.unified_msg_origin, 
                        MessageChain([Plain("喂！你怎么偷看人家的日记啦？真是的...")])
                    )

            # 异步生成责备回应
            blame_task = asyncio.create_task(generate_blame())
            self.background_tasks.append(blame_task)

        except Exception as e:
            logger.error(f"读取日记失败: {e}")
            yield event.plain_result("读取日记失败，请检查日志。")

    @kpi_group.command("correct")
    async def kpi_correct(self, event: AstrMessageEvent, *args):
        """纠正Bot的错误 /kpi correct [原始回复] [纠正后的回复]"""
        if len(args) < 2:
            yield event.plain_result("用法: /kpi correct [原始回复] [纠正后的回复]")
            return
        
        # 提取原始回复和纠正后的回复
        original = args[0]
        corrected = ' '.join(args[1:])
        
        # 记录纠正
        self._learn_from_correction(original, corrected)
        
        yield event.plain_result("谢谢你的纠正，我会记住的！")

    @kpi_group.command("preference")
    async def kpi_preference(self, event: AstrMessageEvent, category: str, *preference):
        """添加用户偏好 /kpi preference [类别] [偏好内容]"""
        if not preference:
            yield event.plain_result("用法: /kpi preference [类别] [偏好内容]")
            yield event.plain_result("支持的类别: music, movies, food, hobbies, other")
            return
        
        # 验证类别
        valid_categories = ["music", "movies", "food", "hobbies", "other"]
        if category not in valid_categories:
            yield event.plain_result(f"无效的类别。支持的类别: {', '.join(valid_categories)}")
            return
        
        # 提取偏好内容
        preference_content = ' '.join(preference)
        
        # 添加偏好
        self._add_user_preference(category, preference_content)
        
        yield event.plain_result(f"已添加偏好: {category} - {preference_content}")

    @kpi_group.command("recent")
    async def kpi_recent(self, event: AstrMessageEvent, days: int = 3):
        """查看近几天的日记 /kpi recent [天数]"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("日记功能未启用，请在配置中开启。")
            return

        days = max(1, min(7, int(days)))  # 限制1-7天

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
            yield event.plain_result(f"近 {days} 天没有找到任何日记。")
            return

        # 检查是否需要自动撤回
        if self.diary_auto_recall:
            logger.info(f"日记消息将在 {self.diary_recall_time} 秒后自动撤回")

            # 启动自动撤回任务
            async def recall_message():
                await asyncio.sleep(self.diary_recall_time)
                try:
                    logger.info(
                        f"日记消息已达到自动撤回时间: {self.diary_recall_time}秒"
                    )
                except Exception as e:
                    logger.error(f"自动撤回日志记录失败: {e}")

            # 创建并保存撤回任务
            task = asyncio.create_task(recall_message())
            self.background_tasks.append(task)

        # 按日期从新到旧发送日记
        for diary in found_diaries:
            # 提取感想部分
            summary_start = diary['content'].find("## 今日感想")
            if summary_start != -1:
                summary_content = diary['content'][summary_start:]
                # 提取感想文本，去除标题
                summary_lines = summary_content.split('\n')
                summary_text = '\n'.join(summary_lines[2:]).strip()
                # 限制在500字以下
                if len(summary_text) > 500:
                    summary_text = summary_text[:497] + "..."
                diary_message = f"【{self.bot_name}的日记】\n{diary['date'].strftime('%Y年%m月%d日')}\n\n{summary_text}"
            else:
                # 尝试提取旧格式的总结部分
                summary_start = diary['content'].find(f"## {self.bot_name}的总结")
                if summary_start == -1:
                    summary_start = diary['content'].find("## 总结")
                if summary_start != -1:
                    summary_content = diary['content'][summary_start:]
                    # 提取总结文本，去除标题
                    summary_lines = summary_content.split('\n')
                    summary_text = '\n'.join(summary_lines[2:]).strip()
                    # 限制在500字以下
                    if len(summary_text) > 500:
                        summary_text = summary_text[:497] + "..."
                    diary_message = f"【{self.bot_name}的日记】\n{diary['date'].strftime('%Y年%m月%d日')}\n\n{summary_text}"
                else:
                    # 如果没有感想或总结部分，使用整个日记内容（限制500字）
                    diary_text = diary['content'].replace(f'# {self.bot_name}的日记', '').replace(f'# {self.bot_name}的观察日记', '').replace(f'{diary["date"].strftime("%Y年%m月%d日")}', '').replace('## 今日观察', '').strip()
                    if len(diary_text) > 500:
                        diary_text = diary_text[:497] + "..."
                    diary_message = f"【{self.bot_name}的日记】\n{diary['date'].strftime('%Y年%m月%d日')}\n\n{diary_text}"
            
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
            
            await asyncio.sleep(0.5)  # 添加小延迟使发送更自然

        # 同时生成日记被偷看的回应（异步进行）
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
                            MessageChain([Plain("喂！你怎么偷看人家这么多天的日记啦？真是的...")])
                        )
                except Exception as e:
                    logger.error(f"生成日记被偷看回应失败: {e}")
                    await self.context.send_message(
                        event.unified_msg_origin, 
                        MessageChain([Plain("喂！你怎么偷看人家这么多天的日记啦？真是的...")])
                    )
            else:
                await self.context.send_message(
                    event.unified_msg_origin, 
                    MessageChain([Plain("喂！你怎么偷看人家这么多天的日记啦？真是的...")])
                )

        # 异步生成责备回应
        blame_task = asyncio.create_task(generate_blame())
        self.background_tasks.append(blame_task)

    @kpi_group.command("debug")
    async def kpi_debug(self, event: AstrMessageEvent, status: str = None):
        """切换调试模式 /kpi debug [on/off]"""
        if status is None:
            # 显示当前状态
            current_status = self.debug
            status_text = "开启" if current_status else "关闭"
            yield event.plain_result(f"当前调试模式状态：{status_text}")
            return
        
        status = status.lower()
        if status == "on":
            self.plugin_config.debug = True
            yield event.plain_result("调试模式已开启，将显示详细日志")
        elif status == "off":
            self.plugin_config.debug = False
            yield event.plain_result("调试模式已关闭，将隐藏大部分日志")
        else:
            yield event.plain_result("用法: /kpi debug [on/off]")

    @kpi_group.command("webui")
    async def kpi_webui(self, event: AstrMessageEvent, action: str = "start"):
        """控制 Web UI /kpi webui [start/stop]"""
        if action.lower() == "start":
            if self.web_server:
                yield event.plain_result("⚠️ Web UI 已经在运行中")
            else:
                await self._start_webui()
                yield event.plain_result(f"✅ Web UI 已启动，访问地址: http://127.0.0.1:{self.webui_port}")
        elif action.lower() == "stop":
            if not self.web_server:
                yield event.plain_result("⚠️ Web UI 未运行")
            else:
                await self._stop_webui()
                self.web_server = None
                yield event.plain_result("✅ Web UI 已停止")
        else:
            yield event.plain_result("❌ 无效的操作，使用 /kpi webui start 或 /kpi webui stop")

    @kpi_group.command("complete")
    async def kpi_complete(self, event: AstrMessageEvent, date: str = None):
        """补写日记 /kpi complete [YYYY-MM-DD]"""
        async for result in self._handle_complete_command(event, date):
            yield result

    @kpi_group.command("cd")
    async def kpi_cd(self, event: AstrMessageEvent, date: str = None):
        """补写日记（简化版） /kpi cd [YYYYMMDD]"""
        async for result in self._handle_complete_command(event, date):
            yield result

    async def _handle_complete_command(self, event: AstrMessageEvent, date: str = None):
        """处理日记补写命令"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("日记功能未启用，请在配置中开启。")
            return

        # 确定要补写的日期
        if date:
            try:
                # 支持两种日期格式：YYYY-MM-DD 和 YYYYMMDD
                date_str = str(date)
                if len(date_str) == 8 and date_str.isdigit():
                    target_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                else:
                    target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                yield event.plain_result(
                    "日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD 格式，例如：/kpi cd 20260302"
                )
                return
        else:
            target_date = datetime.date.today()

        # 检查是否已有日记
        diary_filename = f"diary_{target_date.strftime('%Y%m%d')}.md"
        diary_path = os.path.join(self.diary_storage, diary_filename)

        if os.path.exists(diary_path):
            yield event.plain_result(
                f"{target_date.strftime('%Y年%m月%d日')} 的日记已经存在，无需补写。"
            )
            return

        # 生成补写日记
        provider = self.context.get_using_provider()
        if not provider:
            yield event.plain_result("未检测到已启用的 LLM 提供商，无法生成日记。")
            return

        try:
            system_prompt = await self._get_persona_prompt(event.unified_msg_origin)
            completion_prompt = f"请根据你的性格和之前的日记风格，补写 {target_date.strftime('%Y年%m月%d日')} 的日记。请根据观察记录，写一篇日记总结，记录今天的观察和感受，融入你的性格和情感。不要只是对观察记录的生硬总结，而是要融合你的经历和情感，生成一个更个人化的日记。请字数控制在400字左右。"

            # 参考前几天的日记
            reference_days = []
            for i in range(1, 3):  # 参考前2天
                past_date = target_date - datetime.timedelta(days=i)
                past_diary_filename = f"diary_{past_date.strftime('%Y%m%d')}.md"
                past_diary_path = os.path.join(
                    self.diary_storage, past_diary_filename
                )
                if os.path.exists(past_diary_path):
                    try:
                        with open(past_diary_path, encoding="utf-8") as f:
                            past_diary_content = f.read()
                        reference_days.append(
                            {
                                "date": past_date.strftime("%Y年%m月%d日"),
                                "content": past_diary_content,
                            }
                        )
                    except Exception as e:
                        logger.error(f"读取前几天日记失败: {e}")

            if reference_days:
                completion_prompt += "\n\n参考前几天的日记：\n"
                for day in reference_days:
                    completion_prompt += f"### {day['date']}\n{day['content'][:500]}...\n\n"  # 只取前500字
                completion_prompt += "\n请结合前几天的日记内容，保持日记风格的连贯性，补写出今天的日记。"

            # 生成日记内容
            response = await provider.text_chat(
                prompt=completion_prompt, system_prompt=system_prompt
            )

            if (
                response
                and hasattr(response, "completion_text")
                and response.completion_text
            ):
                # 获取星期
                weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
                weekday = weekdays[target_date.weekday()]

                # 尝试获取天气信息
                weather_info = ""
                try:
                    weather_info = await self._get_weather_prompt()
                except Exception as e:
                    logger.debug(f"获取天气信息失败: {e}")

                # 构建补写日记内容 - 符合标准日记格式
                diary_content = f"# {self.bot_name}的日记\n\n"
                diary_content += f"## {target_date.strftime('%Y年%m月%d日')} {weekday}\n\n"
                if weather_info:
                    diary_content += f"**天气**: {weather_info}\n\n"
                diary_content += "## 今日观察\n\n"
                diary_content += "（补写）今天的具体活动记录缺失\n\n"
                diary_content += "## 今日感想\n\n"
                diary_content += response.completion_text

                # 保存日记文件
                try:
                    with open(diary_path, "w", encoding="utf-8") as f:
                        f.write(diary_content)
                    logger.info(f"补写日记已保存到: {diary_path}")
                    yield event.plain_result(f"已成功补写 {target_date.strftime('%Y年%m月%d日')} 的日记。")
                except Exception as e:
                    logger.error(f"保存补写日记失败: {e}")
                    yield event.plain_result("保存补写日记失败，请检查日志。")
            else:
                yield event.plain_result("生成日记内容失败，请检查日志。")
        except Exception as e:
            logger.error(f"补写日记失败: {e}")
            yield event.plain_result("补写日记失败，请检查日志。")

    def _is_in_active_time_range(self):
        """检查当前时间是否在设定的活跃时间段内"""
        # 使用配置的活跃时间段
        time_range = self.active_time_range

        if not time_range:
            return True

        try:
            import datetime

            now = datetime.datetime.now().time()
            start_str, end_str = time_range.split("-")
            start_hour, start_minute = map(int, start_str.split(":"))
            end_hour, end_minute = map(int, end_str.split(":"))

            start_time = datetime.time(start_hour, start_minute)
            end_time = datetime.time(end_hour, end_minute)

            if start_time <= end_time:
                return start_time <= now <= end_time
            else:
                # 跨午夜的情况
                return now >= start_time or now <= end_time
        except Exception as e:
            logger.error(f"解析时间段失败: {e}")
            return True

    def _add_diary_entry(self, content: str, active_window: str):
        """添加日记条目"""
        if not self.enable_diary:
            return

        import datetime

        now = datetime.datetime.now()
        entry = {
            "time": now.strftime("%H:%M:%S"),
            "content": content,
            "active_window": active_window,
        }
        self.diary_entries.append(entry)
        logger.info(f"添加日记条目: {entry}")

    async def _generate_diary(self):
        """生成日记"""
        if not self.enable_diary or not self.diary_entries:
            return

        import datetime

        today = datetime.date.today()
        # 获取星期
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[today.weekday()]

        # 尝试获取天气信息
        weather_info = ""
        try:
            weather_info = await self._get_weather_prompt()
        except Exception as e:
            logger.debug(f"获取天气信息失败: {e}")

        # 构建日记内容 - 符合标准日记格式
        diary_content = f"# {self.bot_name}的日记\n\n"
        diary_content += f"## {today.strftime('%Y年%m月%d日')} {weekday}\n\n"
        if weather_info:
            diary_content += f"**天气**: {weather_info}\n\n"

        # 添加观察记录
        diary_content += "## 今日观察\n\n"
        for entry in self.diary_entries:
            diary_content += f"### {entry['time']} - {entry['active_window']}\n"
            diary_content += f"{entry['content']}\n\n"

        # 检查最近三次日记的查看状态
        import datetime
        viewed_count = 0
        for i in range(1, 4):
            past_date = today - datetime.timedelta(days=i)
            past_date_str = past_date.strftime("%Y%m%d")
            if past_date_str in self.diary_metadata and self.diary_metadata[past_date_str].get("viewed", False):
                viewed_count += 1
        
        logger.info(f"最近三天日记查看状态: {viewed_count} 次被查看")

        # 生成风格化的总结
        provider = self.context.get_using_provider()
        if provider:
            if len(self.diary_entries) < 2:
                summary_prompt = "今天用户几乎没有给你看屏幕，你想偷看他的日记却被他发现了。抱怨一下：屏幕都不给我看，还想偷看我的日记？字数控制在400字左右。"
            else:
                # 根据查看次数生成不同的提示词
                if viewed_count == 0:
                    # 没有查看过，正常生成日记
                    summary_prompt = f"请根据以下观察记录，写一篇日记总结，记录今天的观察和感受，融入你的性格和情感。字数控制在400字左右。\n\n{diary_content}"
                elif viewed_count == 1:
                    # 查看过1次，感觉有些不对劲
                    summary_prompt = f"请根据以下观察记录，写一篇日记总结，记录今天的观察和感受。注意：你感觉有些不对劲，似乎有人偷看了你的日记。融入你的性格和情感，表达出这种微妙的不安感。字数控制在400字左右。\n\n{diary_content}"
                elif viewed_count == 2:
                    # 查看过2次，确信用户看过自己的日记
                    summary_prompt = f"请根据以下观察记录，写一篇日记总结，记录今天的观察和感受。注意：你确信用户看过你的日记，对此感到有些惊讶和好奇。融入你的性格和情感，表达出这种复杂的情绪。字数控制在400字左右。\n\n{diary_content}"
                else:
                    # 查看过3次，对这一行为表达自己的看法
                    summary_prompt = f"请根据以下观察记录，写一篇日记总结，记录今天的观察和感受。注意：用户已经多次偷看你的日记，你对此有自己的看法。融入你的性格和情感，表达出你对这一行为的态度和想法。字数控制在400字左右。\n\n{diary_content}"

                if self.diary_reference_days > 0:
                    reference_days = []
                    for i in range(1, self.diary_reference_days + 1):
                        past_date = today - datetime.timedelta(days=i)
                        past_diary_filename = f"diary_{past_date.strftime('%Y%m%d')}.md"
                        past_diary_path = os.path.join(
                            self.diary_storage, past_diary_filename
                        )
                        if os.path.exists(past_diary_path):
                            try:
                                with open(past_diary_path, encoding="utf-8") as f:
                                    past_diary_content = f.read()
                                reference_days.append(
                                    {
                                        "date": past_date.strftime("%Y年%m月%d日"),
                                        "content": past_diary_content,
                                    }
                                )
                            except Exception as e:
                                logger.error(f"读取前几天日记失败: {e}")

                    if reference_days:
                        summary_prompt += "\n\n参考前几天的日记：\n"
                        for day in reference_days:
                            summary_prompt += f"### {day['date']}\n{day['content'][:500]}...\n\n"
                        summary_prompt += "\n请结合前几天的日记内容，保持日记风格的连贯性，写出今天的总结。"

            try:
                system_prompt = await self._get_persona_prompt()
                response = await provider.text_chat(
                    prompt=summary_prompt, system_prompt=system_prompt
                )
                if (
                    response
                    and hasattr(response, "completion_text")
                    and response.completion_text
                ):
                    diary_content += "## 今日感想\n\n"
                    diary_content += response.completion_text
            except Exception as e:
                logger.error(f"生成日记总结失败: {e}")

        # 保存日记文件
        diary_filename = f"diary_{today.strftime('%Y%m%d')}.md"
        diary_path = os.path.join(self.diary_storage, diary_filename)

        try:
            with open(diary_path, "w", encoding="utf-8") as f:
                f.write(diary_content)
            logger.info(f"日记已保存到: {diary_path}")

            # 重置日记条目
            self.diary_entries = []
            self.last_diary_date = today

            logger.info("日记生成完成，不自动发送，等待用户指令拉取")
        except Exception as e:
            logger.error(f"保存日记失败: {e}")

    def _parse_user_preferences(self):
        """解析用户偏好设置"""
        self.parsed_preferences = {}
        if not self.user_preferences:
            return

        lines = self.user_preferences.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 解析场景和偏好
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue

            scene, preference = parts
            self.parsed_preferences[scene] = preference

        logger.info(f"解析到 {len(self.parsed_preferences)} 个用户偏好设置")

    def _load_learning_data(self):
        """加载学习数据"""
        try:
            learning_file = os.path.join(self.learning_storage, "learning_data.json")
            if os.path.exists(learning_file):
                with open(learning_file, encoding="utf-8") as f:
                    self.learning_data = json.load(f)
                logger.info("学习数据加载成功")
        except Exception as e:
            logger.error(f"加载学习数据失败: {e}")
            self.learning_data = {}

    async def _start_webui(self):
        """启动 Web UI 服务器"""
        try:
            self.web_server = WebServer(self, host=self.webui_host, port=self.webui_port)
            success = await self.web_server.start()
            if not success:
                logger.error("Web UI 启动失败")
        except Exception as e:
            logger.error(f"启动 Web UI 时出错: {e}")

    async def _stop_webui(self):
        """停止 Web UI 服务器"""
        if self.web_server:
            try:
                await self.web_server.stop()
            except Exception as e:
                logger.error(f"停止 Web UI 时出错: {e}")

    def _save_learning_data(self):
        """保存学习数据"""
        if not self.enable_learning:
            return

        try:
            learning_file = os.path.join(self.learning_storage, "learning_data.json")
            with open(learning_file, "w", encoding="utf-8") as f:
                json.dump(self.learning_data, f, ensure_ascii=False, indent=2)
            logger.info("学习数据保存成功")
        except Exception as e:
            logger.error(f"保存学习数据失败: {e}")

    def _load_corrections(self):
        """加载用户纠正数据"""
        try:
            import json
            import os
            if os.path.exists(self.corrections_file):
                with open(self.corrections_file, "r", encoding="utf-8") as f:
                    self.corrections = json.load(f)
                logger.info("纠正数据加载成功")
        except Exception as e:
            logger.error(f"加载纠正数据失败: {e}")
            self.corrections = {}

    def _save_corrections(self):
        """保存用户纠正数据"""
        try:
            import json
            import os
            with open(self.corrections_file, "w", encoding="utf-8") as f:
                json.dump(self.corrections, f, ensure_ascii=False, indent=2)
            logger.info("纠正数据保存成功")
        except Exception as e:
            logger.error(f"保存纠正数据失败: {e}")

    def _add_uncertainty(self, response):
        """在回复中添加不确定性表达"""
        import random
        
        # 随机添加不确定性词汇
        if random.random() < 0.3:
            uncertainty_word = random.choice(self.uncertainty_words)
            # 根据句子结构选择合适的位置添加
            if response.startswith(('你', '我', '他', '她', '它', '这', '那')):
                # 在句首添加
                response = f"{uncertainty_word}，{response}"
            else:
                # 在句中添加
                sentences = response.split('。')
                if sentences:
                    # 随机选择一个句子并保存其索引
                    target_index = random.randint(0, len(sentences) - 1)
                    target_sentence = sentences[target_index]
                    if target_sentence:
                        words = target_sentence.split(' ')
                        if len(words) > 1:
                            insert_pos = random.randint(0, len(words) - 1)
                            words.insert(insert_pos, uncertainty_word)
                            target_sentence = ' '.join(words)
                        # 使用保存的索引更新句子
                        sentences[target_index] = target_sentence
                    response = '。'.join(sentences)
        
        return response

    def _learn_from_correction(self, original_response, corrected_response):
        """从用户纠正中学习"""
        # 记录纠正信息
        import uuid
        import datetime
        correction_id = str(uuid.uuid4())
        self.corrections[correction_id] = {
            "original": original_response,
            "corrected": corrected_response,
            "timestamp": datetime.datetime.now().isoformat()
        }
        # 保存纠正数据
        self._save_corrections()
        logger.info("已记录用户纠正")

    def _update_learning_data(self, scene, feedback):
        """更新学习数据"""
        if not self.enable_learning:
            return

        if scene not in self.learning_data:
            self.learning_data[scene] = {"feedback": []}

        self.learning_data[scene]["feedback"].append(
            {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "feedback": feedback}
        )

        # 保存学习数据
        self._save_learning_data()

    def _get_scene_preference(self, scene):
        """获取场景的用户偏好"""
        # 优先使用用户配置的偏好
        if scene in self.parsed_preferences:
            return self.parsed_preferences[scene]

        # 其次使用学习到的偏好
        if self.enable_learning and scene in self.learning_data:
            # 简单的偏好学习逻辑
            feedbacks = self.learning_data[scene].get("feedback", [])
            if feedbacks:
                # 这里可以实现更复杂的学习逻辑
                # 暂时返回最后一条反馈
                return feedbacks[-1]["feedback"]

        # 默认偏好
        default_preferences = {
            "编程": "用户正在编程，需要专注，提供简短的鼓励和提醒。",
            "设计": "用户正在设计，需要创意，提供创意相关的鼓励和建议。",
            "浏览": "用户正在浏览网页，根据内容提供相应的互动。",
            "办公": "用户正在办公，需要效率，提供简短的鼓励和提醒。",
            "游戏": "用户正在游戏，需要娱乐，提供活泼的互动，增加参与感。",
            "视频": "用户正在观看视频，需要放松，提供活泼的互动，增加参与感。",
            "阅读": "用户正在阅读，需要沉浸，提供深度的思考和创意的猜想，增加阅读体验。",
            "音乐": "用户正在听音乐，需要放松，提供轻松的互动，不要过多打扰。",
            "聊天": "用户正在聊天，需要交流，提供友好的互动，不要过多打扰。",
            "终端": "用户正在使用终端，需要专注，提供技术相关的鼓励和提醒。",
            "邮件": "用户正在处理邮件，需要效率，提供简短的提醒，不要过多打扰。",
        }

        return default_preferences.get(scene, "")

    async def _task_scheduler(self):
        """任务调度器，限制并发任务数"""
        while self.running:
            try:
                # 从队列中获取任务
                try:
                    task_func, task_args = await asyncio.wait_for(
                        self.task_queue.get(), timeout=1.0
                    )

                    # 使用信号量限制并发
                    async with self.task_semaphore:
                        try:
                            await task_func(*task_args)
                        except Exception as e:
                            logger.error(f"执行任务时出错: {e}")

                    # 标记任务完成
                    self.task_queue.task_done()
                except asyncio.TimeoutError:
                    # 超时，继续循环检查running标志
                    pass
            except Exception as e:
                logger.error(f"任务调度器异常: {e}")
                await asyncio.sleep(1)

    def _parse_custom_tasks(self):
        """解析自定义监控任务"""
        self.parsed_custom_tasks = []
        if not self.custom_tasks:
            return

        lines = self.custom_tasks.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 解析时间和提示词
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue

            time_str, prompt = parts
            try:
                hour, minute = map(int, time_str.split(":"))
                if 0 <= hour < 24 and 0 <= minute < 60:
                    self.parsed_custom_tasks.append(
                        {"hour": hour, "minute": minute, "prompt": prompt}
                    )
            except ValueError:
                pass

        logger.info(f"解析到 {len(self.parsed_custom_tasks)} 个自定义监控任务")

    def _get_microphone_volume(self):
        """获取麦克风音量"""
        try:
            import numpy as np
            import pyaudio

            # 初始化PyAudio
            p = pyaudio.PyAudio()

            # 打开麦克风流
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=44100,
                input=True,
                frames_per_buffer=1024,
            )

            # 读取音频数据
            data = stream.read(1024)

            # 关闭流
            stream.stop_stream()
            stream.close()
            p.terminate()

            # 计算音量
            audio_data = np.frombuffer(data, dtype=np.int16)
            
            # 检查audio_data是否为空
            if len(audio_data) == 0:
                logger.debug("音频数据为空")
                return 0
                
            # 计算均值，处理可能的空数据
            try:
                square_data = np.square(audio_data)
                mean_square = np.mean(square_data)
                
                # 检查mean_square是否为NaN
                if np.isnan(mean_square):
                    logger.debug("均值为NaN")
                    return 0
                    
                rms = np.sqrt(mean_square)
                
                # 检查rms是否为NaN
                if np.isnan(rms):
                    logger.debug("RMS为NaN")
                    return 0

                # 将音量转换为0-100的范围
                volume = min(100, int(rms / 32768 * 100 * 5))
                return volume
            except Exception as e:
                logger.error(f"计算音量时出错: {e}")
                return 0
        except ImportError:
            logger.debug("未安装pyaudio库，跳过麦克风音量检测")
            return 0
        except Exception as e:
            logger.error(f"获取麦克风音量失败: {e}")
            return 0

    async def _mic_monitor_task(self):
        """麦克风监听任务"""
        # 检查麦克风依赖
        mic_deps_ok = False
        try:
            import sys

            logger.info(f"[麦克风依赖检查] Python路径: {sys.path}")
            logger.info(f"[麦克风依赖检查] Python可执行文件: {sys.executable}")

            import pyaudio

            logger.info(f"[麦克风依赖检查] PyAudio已加载: {pyaudio.__version__}")

            import numpy

            logger.info(f"[麦克风依赖检查] NumPy已加载: {numpy.__version__}")

            mic_deps_ok = True
        except ImportError as e:
            logger.warning(f"[麦克风依赖检查] 未安装麦克风监听所需的依赖库: {e}")
            logger.warning("请执行: pip install pyaudio numpy 以启用麦克风监听功能")
            import traceback

            logger.warning(f"[麦克风依赖检查] 详细错误: {traceback.format_exc()}")

        while self.enable_mic_monitor:
            try:
                if not mic_deps_ok:
                    await asyncio.sleep(60)
                    continue

                # 获取当前时间
                current_time = time.time()

                # 检查是否在防抖时间内
                if current_time - self.last_mic_trigger < self.mic_debounce_time:
                    await asyncio.sleep(self.mic_check_interval)
                    continue

                # 获取麦克风音量
                volume = self._get_microphone_volume()
                logger.debug(f"麦克风音量: {volume}")

                # 检查音量是否超过阈值
                if volume > self.mic_threshold:
                    logger.info(f"麦克风音量超过阈值: {volume} > {self.mic_threshold}")

                    # 检查环境
                    ok, err_msg = self._check_env(check_mic=True)
                    if not ok:
                        logger.error(f"麦克风触发失败: {err_msg}")
                        await asyncio.sleep(self.mic_check_interval)
                        continue

                    # 创建临时任务
                    try:
                        # 保存当前状态
                        current_state = self.state
                        # 只有在非活动状态时才设置为临时任务状态
                        if current_state == "inactive":
                            self.state = "temporary"
                        
                        # 创建临时任务ID
                        temp_task_id = f"temp_mic_{int(time.time())}"
                        
                        # 定义临时任务函数
                        async def temp_mic_task():
                            try:
                                # 创建一个虚拟的event对象，用于传递给_analyze_screen
                                class VirtualEvent:
                                    def __init__(self):
                                        self.unified_msg_origin = self._get_default_target()

                                    def _get_default_target(self):
                                        admin_qq = self.admin_qq
                                        if admin_qq:
                                            return f"aiocqhttp:FriendMessage:{admin_qq}"
                                        return ""

                                # 绑定config到VirtualEvent
                                VirtualEvent.config = self.plugin_config

                                event = VirtualEvent()

                                image_bytes, active_window_title = await asyncio.wait_for(
                                    self._capture_screen_bytes(), timeout=10.0
                                )
                                components = await asyncio.wait_for(
                                    self._analyze_screen(
                                        image_bytes,
                                        session=event,
                                        active_window_title=active_window_title,
                                        custom_prompt="我听到你说话声音很大，发生什么事了？",
                                        task_id=temp_task_id,
                                    ),
                                    timeout=120.0,
                                )

                                # 确定消息发送目标
                                target = self.proactive_target
                                if not target:
                                    admin_qq = self.admin_qq
                                    if admin_qq:
                                        target = f"aiocqhttp:FriendMessage:{admin_qq}"

                                if target:
                                    # 提取文本内容并发送
                                    text_content = ""
                                    for comp in components:
                                        if isinstance(comp, Plain):
                                            text_content += comp.text

                                    if text_content:
                                        message = f"【声音提醒】\n{text_content}"
                                        await self.context.send_message(
                                            target, MessageChain([Plain(message)])
                                        )
                                        logger.info("麦克风触发消息已发送")

                                # 更新上次触发时间
                                self.last_mic_trigger = current_time
                            finally:
                                # 任务完成后，清理临时任务
                                if temp_task_id in self.temporary_tasks:
                                    del self.temporary_tasks[temp_task_id]
                                # 如果没有其他任务，恢复到原始状态
                                if not self.auto_tasks and not self.temporary_tasks:
                                    self.state = current_state

                        # 创建并启动临时任务
                        self.temporary_tasks[temp_task_id] = asyncio.create_task(temp_mic_task())
                        logger.info(f"已创建麦克风临时任务: {temp_task_id}")
                    except Exception as e:
                        logger.error(f"创建麦克风临时任务时出错: {e}")
                        # 出错时恢复到原始状态
                        if not self.auto_tasks and not self.temporary_tasks:
                            self.state = current_state

                # 等待检查间隔
                await asyncio.sleep(self.mic_check_interval)
            except Exception as e:
                logger.error(f"麦克风监听任务异常: {e}")
                await asyncio.sleep(self.mic_check_interval)

    async def _custom_tasks_task(self):
        """自定义监控任务"""
        while self.running:
            try:
                now = datetime.datetime.now()
                current_hour = now.hour
                current_minute = now.minute

                # 检查是否有需要执行的自定义任务
                for task in self.parsed_custom_tasks:
                    if (
                        task["hour"] == current_hour
                        and task["minute"] == current_minute
                    ):
                        logger.info(f"执行自定义监控任务: {task['prompt']}")
                        # 检查环境
                        ok, err_msg = self._check_env()
                        if not ok:
                            logger.error(f"自定义任务执行失败: {err_msg}")
                            continue

                        # 创建临时任务
                        try:
                            # 保存当前状态
                            current_state = self.state
                            # 只有在非活动状态时才设置为临时任务状态
                            if current_state == "inactive":
                                self.state = "temporary"
                            
                            # 创建临时任务ID
                            temp_task_id = f"temp_custom_{int(time.time())}"
                            
                            # 定义临时任务函数
                            async def temp_custom_task():
                                try:
                                    image_bytes, active_window_title = await asyncio.wait_for(
                                        self._capture_screen_bytes(), timeout=10.0
                                    )
                                    components = await asyncio.wait_for(
                                        self._analyze_screen(
                                            image_bytes,
                                            active_window_title=active_window_title,
                                            custom_prompt=task["prompt"],
                                            task_id=temp_task_id,
                                        ),
                                        timeout=120.0,
                                    )

                                    # 确定消息发送目标
                                    target = self.proactive_target
                                    if not target:
                                        admin_qq = self.admin_qq
                                        if admin_qq:
                                            target = f"aiocqhttp:FriendMessage:{admin_qq}"

                                    if target:
                                        # 提取文本内容并发送
                                        text_content = ""
                                        for comp in components:
                                            if isinstance(comp, Plain):
                                                text_content += comp.text

                                        if text_content:
                                            message = f"【定时提醒】\n{text_content}"
                                            await self.context.send_message(
                                                target, MessageChain([Plain(message)])
                                            )
                                            logger.info("自定义任务消息已发送")
                                finally:
                                    # 任务完成后，清理临时任务
                                    if temp_task_id in self.temporary_tasks:
                                        del self.temporary_tasks[temp_task_id]
                                    # 如果没有其他任务，恢复到原始状态
                                    if not self.auto_tasks and not self.temporary_tasks:
                                        self.state = current_state

                            # 创建并启动临时任务
                            self.temporary_tasks[temp_task_id] = asyncio.create_task(temp_custom_task())
                            logger.info(f"已创建自定义临时任务: {temp_task_id}")
                        except Exception as e:
                            logger.error(f"创建自定义临时任务时出错: {e}")
                            # 出错时恢复到原始状态
                            if not self.auto_tasks and not self.temporary_tasks:
                                self.state = current_state

                # 等待1分钟，期间检查running标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"自定义任务异常: {e}")
                # 等待1分钟，期间检查running标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)

    async def _diary_task(self):
        """日记任务"""
        while self.running:
            try:
                now = datetime.datetime.now()
                today = now.date()

                # 检查是否需要生成日记
                if self.enable_diary and self.last_diary_date != today:
                    # 解析日记时间
                    try:
                        hour, minute = map(int, self.diary_time.split(":"))
                        if now.hour == hour and now.minute == minute:
                            await self._generate_diary()
                    except Exception as e:
                        logger.error(f"解析日记时间失败: {e}")

                # 等待1分钟，期间检查running标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"日记任务异常: {e}")
                # 等待1分钟，期间检查running标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)

    async def _auto_screen_task(
        self,
        event: AstrMessageEvent,
        task_id: str = "default",
        custom_prompt: str = "",
        interval: int = None,
    ):
        """后台自动截图分析任务"""
        """参数:
        task_id: 任务ID
        custom_prompt: 自定义提示词
        interval: 自定义检查间隔（秒）
        """
        logger.info(f"[任务 {task_id}] 启动任务")
        try:
            while self.is_running and self.state == "active":
                if not self._is_in_active_time_range():
                    logger.info(f"[任务 {task_id}] 当前时间不在活跃时间段内，停止任务")
                    # 清理任务
                    if task_id in self.auto_tasks:
                        del self.auto_tasks[task_id]
                    # 检查是否还有其他任务在运行
                    if not self.auto_tasks:
                        self.is_running = False
                        self.state = "inactive"
                    break

                # 获取当前预设参数
                current_check_interval, current_trigger_probability = self._get_current_preset_params()
                
                # 使用预设参数
                check_interval = current_check_interval
                probability = current_trigger_probability

                # 首先检查是否有自定义间隔（任务级别的覆盖）
                if interval is not None:
                    check_interval = interval
                    logger.info(f"[任务 {task_id}] 使用自定义间隔: {check_interval} 秒")
                else:
                    logger.info(f"[任务 {task_id}] 使用检查间隔: {check_interval} 秒")

                # 等待检查间隔，期间定期检查is_running标志和任务取消状态
                logger.info(f"[任务 {task_id}] 等待 {check_interval} 秒后进行触发判定")
                elapsed = 0
                while elapsed < check_interval:
                    if not self.is_running or self.state != "active":
                        logger.info(f"[任务 {task_id}] 检测到停止标志或状态变更，退出等待")
                        break
                    try:
                        if elapsed > 0 and elapsed % 10 == 0 and interval is None:
                            new_check_interval, new_probability = self._get_current_preset_params()
                            if new_check_interval != check_interval:
                                check_interval = new_check_interval
                                logger.info(
                                    f"[任务 {task_id}] 预设参数已更新，检查间隔为 {check_interval} 秒"
                                )
                                if elapsed >= check_interval:
                                    logger.info(
                                        f"[任务 {task_id}] 新间隔已生效，提前进行触发判定"
                                    )
                                    break
                            if new_probability != probability:
                                probability = new_probability
                                logger.info(
                                    f"[任务 {task_id}] 预设参数已更新，触发概率为 {probability}%"
                                )
                        await asyncio.sleep(1)
                        elapsed += 1
                    except asyncio.CancelledError:
                        logger.info(f"[任务 {task_id}] 等待期间收到取消信号")
                        raise

                # 检查状态：每次判定前都进行状态检查
                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务停止标志被设置或状态变更，退出任务")
                    break

                # 再次检查是否在活跃时间段内
                if not self._is_in_active_time_range():
                    logger.info(f"[任务 {task_id}] 当前时间不在活跃时间段内，停止任务")
                    # 清理任务
                    if task_id in self.auto_tasks:
                        del self.auto_tasks[task_id]
                    # 检查是否还有其他任务在运行
                    if not self.auto_tasks:
                        self.is_running = False
                        self.state = "inactive"
                    break

                # 再次检查状态
                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务停止标志被设置或状态变更，退出任务")
                    break

                # 系统状态检测
                system_high_load = False
                try:
                    import psutil

                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    memory_percent = memory.percent

                    if cpu_percent > 80 or memory_percent > 80:
                        system_high_load = True
                        logger.info(
                            f"[任务 {task_id}] 系统资源使用较高: CPU={cpu_percent}%, 内存={memory_percent}%"
                        )
                except ImportError:
                    logger.debug(f"[任务 {task_id}] 未安装psutil库，跳过系统状态检测")
                except Exception as e:
                    logger.debug(f"[任务 {task_id}] 系统状态检测失败: {e}")

                # 系统资源使用高时强制触发
                trigger = False
                if system_high_load:
                    trigger = True
                    logger.info(f"[任务 {task_id}] 系统资源使用高，强制触发窥屏")
                else:
                    # 获取当前预设参数
                    check_interval, probability = self._get_current_preset_params()
                    
                    # 进行触发判定
                    import random

                    logger.info(f"[任务 {task_id}] 触发概率 {probability}%")

                    logger.info(f"[任务 {task_id}] 开始进行触发判定")
                    # 生成随机数，判断是否触发
                    random_number = random.randint(1, 100)
                    logger.info(
                        f"[任务 {task_id}] 触发判定详情: 随机数={random_number}, 触发概率={probability}%"
                    )

                    if random_number <= probability:
                        trigger = True

                # 检查是否被停止
                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务停止标志被设置或状态变更，退出任务")
                    break

                # 再次检查状态
                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务停止标志被设置或状态变更，退出任务")
                    break

                if trigger:
                    logger.info(f"[任务 {task_id}] 触发判定通过，开始执行屏幕分析")
                    try:
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务停止标志被设置，取消屏幕分析"
                            )
                            break

                        # 再次检查是否在活跃时间段内，确保在触发判定后时间没有超出范围
                        if not self._is_in_active_time_range():
                            logger.info(
                                f"[任务 {task_id}] 当前时间不在活跃时间段内，停止任务"
                            )
                            # 清理任务
                            if task_id in self.auto_tasks:
                                del self.auto_tasks[task_id]
                            # 检查是否还有其他任务在运行
                            if not self.auto_tasks:
                                self.is_running = False
                            break

                        # 检查是否被停止
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务停止标志被设置，取消屏幕分析"
                            )
                            break

                        image_bytes, active_window_title = await asyncio.wait_for(
                            self._capture_screen_bytes(), timeout=10.0
                        )

                        # 检查是否被停止
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务停止标志被设置，取消屏幕分析"
                            )
                            break

                        components = await asyncio.wait_for(
                            self._analyze_screen(
                                image_bytes,
                                session=event,
                                active_window_title=active_window_title,
                                custom_prompt=custom_prompt,
                                task_id=task_id,
                            ),
                            timeout=120.0,
                        )

                        # 检查是否被停止
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务停止标志被设置，取消发送消息"
                            )
                            break

                        chain = MessageChain()
                        for comp in components:
                            chain.chain.append(comp)

                        # 确定消息发送目标
                        target = self.proactive_target
                        if not target:
                            admin_qq = self.admin_qq
                            if admin_qq:
                                # 使用管理员QQ号构建目标
                                target = f"aiocqhttp:FriendMessage:{admin_qq}"
                                logger.info(f"使用管理员QQ号构建消息目标: {target}")
                            else:
                                # 回退到原始事件的目标
                                try:
                                    target = event.unified_msg_origin
                                    logger.info(f"使用原始事件目标: {target}")
                                except Exception as e:
                                    logger.error(f"获取原始事件目标失败: {e}")
                                    # 使用默认目标
                                    target = (
                                        f"aiocqhttp:FriendMessage:{admin_qq}"
                                        if admin_qq
                                        else ""
                                    )
                                    logger.info(f"使用默认目标: {target}")

                        # 提取文本内容并分段发送
                        text_content = ""
                        for comp in components:
                            if isinstance(comp, Plain):
                                text_content += comp.text

                        # 添加日记条目
                        self._add_diary_entry(text_content, active_window_title)

                        # 自动分段发送，参考 splitter 插件实现
                        if text_content:
                            segments = self._split_message(text_content)
                            logger.info(
                                f"准备发送消息，目标: {target}, 文本内容: {text_content}"
                            )
                            if len(segments) > 1:
                                for i in range(len(segments) - 1):
                                    if not self.is_running:
                                        break
                                    segment = segments[i]
                                    if segment.strip():
                                        await self.context.send_message(
                                            target,
                                            MessageChain([Plain(segment)]),
                                        )
                                        await asyncio.sleep(0.5)
                                if (
                                    self.is_running
                                    and segments[-1].strip()
                                ):
                                    await self.context.send_message(
                                        target,
                                        MessageChain([Plain(segments[-1])]),
                                    )
                            else:
                                if self.is_running:
                                    await self.context.send_message(
                                        target,
                                        MessageChain([Plain(text_content)]),
                                    )
                        else:
                            if self.is_running:
                                await self.context.send_message(
                                    target, chain
                                )

                        # 尝试将消息添加到对话历史
                        try:
                            from astrbot.core.agent.message import (
                                AssistantMessageSegment,
                                TextPart,
                                UserMessageSegment,
                            )

                            # 获取对话管理器
                            if hasattr(self.context, "conversation_manager"):
                                conv_mgr = self.context.conversation_manager
                                uid = event.unified_msg_origin
                                curr_cid = await conv_mgr.get_curr_conversation_id(uid)

                                if curr_cid:
                                    # 创建用户消息和助手消息
                                    user_msg = UserMessageSegment(
                                        content=[TextPart(text="[自动观察]")]
                                    )
                                    assistant_msg = AssistantMessageSegment(
                                        content=[TextPart(text=text_content)]
                                    )

                                    # 添加消息对到对话历史
                                    await conv_mgr.add_message_pair(
                                        cid=curr_cid,
                                        user_message=user_msg,
                                        assistant_message=assistant_msg,
                                    )
                                    logger.info("已将消息添加到对话历史")
                        except Exception as e:
                            logger.debug(f"添加对话历史失败: {e}")
                    except asyncio.TimeoutError:
                        logger.error("操作超时，请检查系统资源和网络连接")
                    except Exception as e:
                        logger.error(f"自动观察任务执行失败: {e}")
                        import traceback

                        logger.error(traceback.format_exc())
        except asyncio.CancelledError:
            logger.info(f"任务 {task_id} 已被取消")
        except Exception as e:
            logger.error(f"任务 {task_id} 异常: {e}")
        finally:
            # 清理任务，确保从auto_tasks中删除
            if task_id in self.auto_tasks:
                del self.auto_tasks[task_id]
                logger.info(f"任务 {task_id} 已从任务列表中删除")
            # 检查是否还有其他任务在运行
            if not self.auto_tasks:
                self.is_running = False
                logger.info("所有自动观察任务已结束")
            logger.info(f"任务 {task_id} 结束")

    def _split_message(self, text: str, max_length: int = 1000) -> list[str]:
        """将消息分割成多个部分，每个部分不超过最大长度"""
        segments = []
        current_segment = ""

        for line in text.split("\n"):
            if len(current_segment) + len(line) + 1 <= max_length:
                if current_segment:
                    current_segment += "\n" + line
                else:
                    current_segment = line
            else:
                if current_segment:
                    segments.append(current_segment)
                    current_segment = line
                else:
                    # 单行长于最大长度，强制分割
                    while len(line) > max_length:
                        segments.append(line[:max_length])
                        line = line[max_length:]
                    current_segment = line

        if current_segment:
            segments.append(current_segment)

        return segments

