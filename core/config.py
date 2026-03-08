import json
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, StarTools


class WebuiConfig(BaseModel):
    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8898
    auth_enabled: bool = True
    password: str = ""
    session_timeout: int = 3600
    allow_external_api: bool = False


class PluginConfig(BaseModel):
    # === 基础功能 ===
    bot_name: str = "屏幕助手"
    enabled: bool = False
    interaction_mode: str = "自定义"
    check_interval: int = 300
    trigger_probability: int = 30
    active_time_range: str = ""
    # === 自定义预设配置 ===
    custom_presets: str = ""  # 格式: 预设1名称|间隔|概率,预设2名称|间隔|概率
    current_preset_index: int = 0  # 当前使用的预设索引
    watch_mode: str = "偷看"
    capture_mode: str = "fullscreen"
    bot_vision_quality: int = 85
    image_prompt: str = "请详细分析这张屏幕截图，捕捉以下细节：1. 屏幕上的具体应用程序、窗口和界面元素 2. 用户正在进行的具体操作和任务 3. 屏幕上的详细文字、图片、图标等内容 4. 用户的操作习惯和行为模式 5. 任何可能被忽略的细节信息。请提供详细的分析结果，重点突出用户当前活动的具体细节，以便我能准确了解用户正在做什么。"
    use_external_vision: bool = True
    vision_api_url: str = ""
    vision_api_key: str = ""
    vision_api_model: str = ""
    user_preferences: str = "游戏 专业的游戏高手，指导玩家提升水平"
    start_end_mode: str = "llm"
    start_preset: str = "知道啦~我会时不时过来看一眼的"
    end_preset: str = "好啦，我不看了～下次再陪你玩！"
    start_llm_prompt: str = "以你的性格向用户表达你会开始偶尔地偷看用户的屏幕了，尽可能简短，保持在一句话内。"
    end_llm_prompt: str = "以你的性格向用户表达你停止看用户的屏幕了，尽可能简短，保持在一句话内。"
    enable_diary: bool = True
    diary_time: str = "22:00"
    diary_storage: str = "E:\\astrbot\\小日记"
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
    custom_tasks: str = ""
    rest_time_range: str = "22:00-06:00"
    enable_learning: bool = True
    learning_storage: str = ""
    interaction_kpi: int = 3
    debug: bool = False
    # === 额外配置 ===
    observation_storage: str = ""
    max_observations: int = 5
    interaction_frequency: int = 5
    image_quality: int = 70
    system_prompt: str = "角色设定：窥屏助手\n把你正在使用的人格复制到这里"

    # === WebUI 管理界面 ===
    webui: WebuiConfig = Field(default_factory=WebuiConfig)

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
