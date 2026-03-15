import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field, field_validator
from enum import Enum

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, StarTools


# 枚举类型定义
# 已移除 WatchMode 枚举类型，改为布尔值开关

class InteractionMode(str, Enum):
    CUSTOM = "自定义"
    AUTO = "自动"
    MANUAL = "手动"

# 已移除 CaptureMode 和 StartEndMode 枚举类型，改为布尔值开关

class WebuiConfig(BaseModel):
    enabled: bool = Field(default=False, description="是否启用 WebUI")
    host: str = Field(default="0.0.0.0", description="WebUI 监听地址")
    port: int = Field(default=6314, ge=1, le=65535, description="WebUI 监听端口")
    auth_enabled: bool = Field(default=True, description="是否启用认证")
    password: str = Field(default="", description="WebUI 访问密码")
    session_timeout: int = Field(default=3600, ge=60, le=86400, description="WebUI 会话有效期（秒）")
    allow_external_api: bool = Field(default=False, description="是否允许外部 API 访问")


class PluginConfig(BaseModel):
    # === 基础功能 ===
    bot_name: str = "屏幕助手"
    enabled: bool = False
    interaction_mode: InteractionMode = InteractionMode.CUSTOM
    check_interval: int = 300
    trigger_probability: int = 30
    active_time_range: str = ""
    # === 自定义预设配置 ===
    custom_presets: str = ""  # 格式: 预设1名称|间隔|概率,预设2名称|间隔|概率
    current_preset_index: int = 0  # 当前使用的预设索引
    use_companion_mode: bool = False  # 是否使用陪伴模式（开启为陪伴模式，关闭为偷看模式）
    companion_prompt: str = "你需要想象自己真实地将持续待在用户身边并与用户一起观看其屏幕内容，并实时地与用户进行互动。"
    capture_active_window: bool = False  # 是否只截取活动窗口
    bot_vision_quality: int = 85
    image_prompt: str = "请用尽量少的字分析这张屏幕截图，只输出高价值信息。优先判断：1. 用户当前在做什么任务 2. 进行到哪一步 3. 画面里最关键的线索或异常 4. 如果需要互动，最值得给出的一个任务相关建议点。避免大段描述界面，不要重复无意义细节，控制在4行内。"
    screen_recognition_mode: bool = False
    ffmpeg_path: str = ""
    recording_fps: float = 1.0
    recording_duration_seconds: int = 10
    use_external_vision: bool = True
    allow_unsafe_video_direct_fallback: bool = False
    vision_api_url: str = ""
    vision_api_key: str = ""
    vision_api_model: str = ""
    # 备用视觉API配置
    vision_api_url_backup: str = ""
    vision_api_key_backup: str = ""
    vision_api_model_backup: str = ""
    user_preferences: str = "游戏 专业的游戏高手，指导玩家提升水平"
    use_llm_for_start_end: bool = True  # 是否使用LLM回复开始和结束消息
    start_preset: str = "知道啦~我会时不时过来看一眼的"
    end_preset: str = "好啦，我不看了～下次再陪你玩！"
    start_llm_prompt: str = "以你的性格向用户表达你会开始偶尔地偷看用户的屏幕了，尽可能简短，保持在一句话内。"
    end_llm_prompt: str = "以你的性格向用户表达你停止看用户的屏幕了，尽可能简短，保持在一句话内。"
    enable_diary: bool = True
    diary_time: str = "22:00"
    diary_storage: str = ""
    diary_reference_days: int = 2
    diary_auto_recall: bool = False
    diary_recall_time: int = 30
    diary_send_as_image: bool = False
    diary_generation_prompt: str = "请根据今天的观察记录，写一篇日记总结，记录今天的观察和感受，融入你的性格和情感。不要只是对观察记录的生硬总结，而是要融合你的经历和情感，生成一个更个人化的日记。请字数控制在400字左右。"
    weather_api_key: str = ""
    weather_city: str = ""
    enable_mic_monitor: bool = False
    mic_threshold: int = 60
    mic_check_interval: int = 5
    admin_qq: str = ""
    proactive_target: str = ""
    save_local: bool = True
    enable_natural_language_screen_assist: bool = False
    enable_window_companion: bool = False
    window_companion_targets: str = ""
    window_companion_check_interval: int = 5
    use_shared_screenshot_dir: bool = False
    shared_screenshot_dir: str = ""
    custom_tasks: str = ""
    rest_time_range: str = "22:00-06:00"
    enable_learning: bool = True
    learning_storage: str = ""
    interaction_kpi: int = 3
    debug: bool = False
    # === 额外配置 ===
    observation_storage: str = ""
    max_observations: int = 9
    interaction_frequency: int = 5
    image_quality: int = 70
    system_prompt: str = "你需要想象自己真实地为了满足好奇心而偷偷查看了一眼用户的屏幕，然后与用户进行互动。"
    bot_appearance: str = ""  # Bot的外形描述，用于在屏幕中识别自己

    # === WebUI 管理界面 ===
    webui: WebuiConfig = Field(default_factory=WebuiConfig)

    # 验证器
    @field_validator("screen_recognition_mode", mode="before")
    @classmethod
    def validate_screen_recognition_mode(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"recording", "video", "true", "1", "yes", "on"}:
                return True
            if normalized in {"screenshot", "image", "false", "0", "no", "off"}:
                return False
        return bool(v)

    @field_validator('check_interval')
    @classmethod
    def validate_check_interval(cls, v):
        if v < 10:
            raise ValueError('check_interval 不能小于 10 秒')
        return v

    @field_validator('trigger_probability')
    @classmethod
    def validate_trigger_probability(cls, v):
        if v < 0 or v > 100:
            raise ValueError('trigger_probability 必须在 0-100 之间')
        return v

    @field_validator('bot_vision_quality')
    @classmethod
    def validate_bot_vision_quality(cls, v):
        if v < 0 or v > 100:
            raise ValueError('bot_vision_quality 必须在 0-100 之间')
        return v

    @field_validator('recording_fps')
    @classmethod
    def validate_recording_fps(cls, v):
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                raise ValueError('recording_fps 必须是数字')
        if v < 0.01 or v > 30:
            raise ValueError('recording_fps 必须在 0.01-30 之间')
        return v

    @field_validator('recording_duration_seconds')
    @classmethod
    def validate_recording_duration_seconds(cls, v):
        if v < 1 or v > 300:
            raise ValueError('recording_duration_seconds 必须在 1-300 之间')
        return v

    @field_validator('image_quality')
    @classmethod
    def validate_image_quality(cls, v):
        if v < 0 or v > 100:
            raise ValueError('image_quality 必须在 0-100 之间')
        return v

    @field_validator('diary_reference_days')
    @classmethod
    def validate_diary_reference_days(cls, v):
        if v < 0:
            raise ValueError('diary_reference_days 不能小于 0')
        return v

    @field_validator('diary_recall_time')
    @classmethod
    def validate_diary_recall_time(cls, v):
        if v < 0:
            raise ValueError('diary_recall_time 不能小于 0')
        return v

    @field_validator('mic_threshold')
    @classmethod
    def validate_mic_threshold(cls, v):
        if v < 0 or v > 100:
            raise ValueError('mic_threshold 必须在 0-100 之间')
        return v

    @field_validator('mic_check_interval')
    @classmethod
    def validate_mic_check_interval(cls, v):
        if v < 1:
            raise ValueError('mic_check_interval 不能小于 1 秒')
        return v

    @field_validator('window_companion_check_interval')
    @classmethod
    def validate_window_companion_check_interval(cls, v):
        if v < 1:
            raise ValueError('window_companion_check_interval 不能小于 1 秒')
        return v

    @field_validator('max_observations')
    @classmethod
    def validate_max_observations(cls, v):
        if v < 1:
            raise ValueError('max_observations 不能小于 1')
        return v

    @field_validator('interaction_frequency')
    @classmethod
    def validate_interaction_frequency(cls, v):
        if v < 1 or v > 10:
            raise ValueError('interaction_frequency 必须在 1-10 之间')
        return v

    @field_validator('interaction_kpi')
    @classmethod
    def validate_interaction_kpi(cls, v):
        if v < 0:
            raise ValueError('interaction_kpi 不能小于 0')
        return v

    # === 忽略额外字段 ===
    class Config:
        extra = "ignore"
        arbitrary_types_allowed = True

    def __init__(self, config: AstrBotConfig | None, context: Context | None = None):
        # 1. 初始化 Pydantic 模型
        initial_data = config if config else {}
        super().__init__(**initial_data)

        # 2. 保存 AstrBotConfig 引用以便回写
        object.__setattr__(self, "_data", config)
        object.__setattr__(self, "_plugin_name", "astrbot_plugin_screen_companion")

        # 3. 初始化路径和目录
        data_dir = StarTools.get_data_dir(self._plugin_name)
        object.__setattr__(self, "data_dir", data_dir)
        object.__setattr__(self, "observations_dir", data_dir / "observations")
        object.__setattr__(self, "diary_dir", data_dir / "diary")
        object.__setattr__(self, "learning_dir", data_dir / "learning")

        # 确保目录存在
        self.ensure_base_dirs()

    def _read_json_file(self, path: Path):
        try:
            if not path.exists():
                return None
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"[Config] JSON 解析失败 {path}: {e}")
            return None
        except Exception as e:
            logger.debug(f"[Config] 读取文件失败 {path}: {e}")
            return None

    def _write_json_file(self, path: Path, data: Any) -> bool:
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except PermissionError as e:
            logger.error(f"[Config] 权限不足，无法写入文件 {path}: {e}")
            return False
        except OSError as e:
            logger.error(f"[Config] 写入文件失败 {path}: {e}")
            return False
        except Exception as e:
            logger.error(f"[Config] 写入 JSON 文件时发生未知错误 {path}: {e}")
            return False

    def save_webui_config(self) -> None:
        """保存 WebUI 配置。"""
        if hasattr(self, "_data") and hasattr(self._data, "save_config"):
            self._data.save_config({"webui": self.webui.model_dump()})

    def __setattr__(self, key: str, value: Any):
        # 更新 Pydantic 模型
        super().__setattr__(key, value)

        # 如果是私有属性或路径属性，跳过回写
        if key.startswith("_") or key in (
            "data_dir",
            "observations_dir",
            "diary_dir",
            "learning_dir",
        ):
            return

        # 回写到 AstrBotConfig
        if hasattr(self, "_data") and self._data is not None:
            if hasattr(self._data, "save_config"):
                try:
                    # 对于 webui 这种嵌套模型，如果是直接替换整个 webui 对象，这里可以处理
                    # 但如果是修改 webui.port，不会触发这里的 __setattr__
                    # 需要手动调用 save_webui_config
                    if key == "webui" and isinstance(value, WebuiConfig):
                        self._data.save_config({key: value.model_dump()})
                    else:
                        self._data.save_config({key: value})
                except Exception:
                    pass
            elif isinstance(self._data, dict):
                self._data[key] = value

    def update_config(self, updates: dict) -> bool:
        """批量更新配置项。"""
        try:
            for key, value in updates.items():
                setattr(self, key, value)

            # 回写到 AstrBotConfig
            if hasattr(self, "_data") and self._data is not None:
                if hasattr(self._data, "save_config"):
                    self._data.save_config(updates)
                elif isinstance(self._data, dict):
                    self._data.update(updates)
            return True
        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return False

    def ensure_base_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.observations_dir.mkdir(parents=True, exist_ok=True)
        self.diary_dir.mkdir(parents=True, exist_ok=True)
        self.learning_dir.mkdir(parents=True, exist_ok=True)

    def get_group_id(self, event: AstrMessageEvent) -> str:
        """获取群号。"""
        try:
            return event.get_group_id()
        except Exception:
            return ""
