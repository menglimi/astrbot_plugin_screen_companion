# -*- coding: utf-8 -*-
from __future__ import annotations

import datetime
import json
import os
import random
import re
import time
import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from .app_descriptions import extract_app_name


class ScreenCompanionMemoryMixin:
    ACTIVITY_INPUT_GRACE_SECONDS = 5 * 60
    ACTIVITY_BROWSER_APP_ALIASES = (
        ("Chrome", ("google chrome", "chrome.exe", "chrome")),
        ("Edge", ("microsoft edge", "msedge", "edge.exe", "edge")),
        ("Firefox", ("firefox.exe", "firefox")),
        ("Safari", ("safari",)),
        ("Opera", ("opera gx", "opera.exe", "opera")),
        ("Brave", ("brave.exe", "brave")),
        ("Arc", ("arc.exe", " arc ")),
        ("Vivaldi", ("vivaldi.exe", "vivaldi")),
        ("QQ浏览器", ("qqbrowser", "qq browser", "qq浏览器")),
        ("360浏览器", ("360chrome", "360se", "360浏览器")),
    )
    ACTIVITY_APP_ALIASES = ACTIVITY_BROWSER_APP_ALIASES + (
        ("VS Code", ("visual studio code", "code.exe", "vscode", "code - insiders")),
        ("Visual Studio", ("devenv.exe", "visual studio")),
        ("PyCharm", ("pycharm",)),
        ("IntelliJ IDEA", ("intellij", "idea64", "idea")),
        ("WebStorm", ("webstorm",)),
        ("GoLand", ("goland",)),
        ("Rider", ("rider64", "jetbrains rider")),
        ("Android Studio", ("android studio", "studio64.exe")),
        ("Cursor", ("cursor.exe", "cursor")),
        ("Windsurf", ("windsurf",)),
        ("微信", ("wechat", "weixin", "微信")),
        ("QQ", ("qq.exe", "tencent qq", "qq ")),
        ("企业微信", ("wecom", "wxwork", "企业微信")),
        ("飞书", ("feishu", "lark", "飞书")),
        ("钉钉", ("dingtalk", "钉钉")),
        ("Slack", ("slack",)),
        ("Discord", ("discord",)),
        ("Telegram", ("telegram",)),
        ("Outlook", ("outlook",)),
        ("Word", ("winword", "microsoft word", "word")),
        ("Excel", ("excel.exe", "microsoft excel", "excel")),
        ("PowerPoint", ("powerpnt", "powerpoint")),
        ("WPS", ("wps", "wps office")),
        ("Notion", ("notion",)),
        ("Obsidian", ("obsidian",)),
        ("Typora", ("typora",)),
        ("Terminal", ("powershell", "cmd.exe", "terminal", "windows terminal", "bash", "zsh")),
        ("Steam", ("steam",)),
        ("PotPlayer", ("potplayer",)),
        ("VLC", ("vlc",)),
    )
    ACTIVITY_GENERIC_BROWSER_SEGMENTS = frozenset(
        {
            "new tab",
            "新标签页",
            "about:blank",
            "start page",
            "主页",
            "home",
            "work",
            "personal",
            "guest",
            "profile",
            "people",
            "browser",
            "网页",
            "网页浏览",
            "标签页",
            "标签",
        }
    )
    ACTIVITY_KNOWN_SITES = (
        ("github.com", "GitHub", ("github", "pull request", "commit", "issue · github")),
        ("gitlab.com", "GitLab", ("gitlab",)),
        ("gitee.com", "Gitee", ("gitee",)),
        ("stackoverflow.com", "Stack Overflow", ("stackoverflow", "stack exchange")),
        ("leetcode.com", "LeetCode", ("leetcode", "力扣")),
        ("juejin.cn", "稀土掘金", ("juejin", "掘金")),
        ("zhihu.com", "知乎", ("zhihu", "知乎")),
        ("notion.so", "Notion", ("notion",)),
        ("figma.com", "Figma", ("figma",)),
        ("feishu.cn", "飞书", ("feishu", "lark", "飞书")),
        ("docs.qq.com", "腾讯文档", ("腾讯文档", "docs.qq")),
        ("doc.weixin.qq.com", "微信文档", ("微信文档", "doc.weixin")),
        ("yuque.com", "语雀", ("yuque", "语雀")),
        ("confluence.com", "Confluence", ("confluence",)),
        ("atlassian.net", "Jira", ("jira", "atlassian")),
        ("linear.app", "Linear", ("linear",)),
        ("trello.com", "Trello", ("trello",)),
        ("asana.com", "Asana", ("asana",)),
        ("docs.google.com", "Google Docs", ("docs.google", "google docs")),
        ("drive.google.com", "Google Drive", ("drive.google", "google drive")),
        ("mail.google.com", "Gmail", ("gmail",)),
        ("outlook.com", "Outlook", ("outlook", "office outlook")),
        ("slack.com", "Slack", ("slack",)),
        ("discord.com", "Discord", ("discord",)),
        ("teams.microsoft.com", "Teams", ("microsoft teams", "teams")),
        ("bilibili.com", "Bilibili", ("bilibili", "哔哩哔哩", "b站")),
        ("youtube.com", "YouTube", ("youtube",)),
        ("netflix.com", "Netflix", ("netflix",)),
        ("x.com", "X", (" twitter ", "x.com", "tweet")),
        ("weibo.com", "微博", ("weibo", "微博")),
        ("xiaohongshu.com", "小红书", ("xiaohongshu", "小红书")),
        ("taobao.com", "淘宝", ("taobao", "淘宝")),
        ("jd.com", "京东", ("jd.com", "京东")),
        ("douban.com", "豆瓣", ("douban", "豆瓣")),
    )
    BACKGROUND_ACTIVITY_APP_SCENES = {
        "VS Code": "编程",
        "Visual Studio": "编程",
        "PyCharm": "编程",
        "IntelliJ IDEA": "编程",
        "WebStorm": "编程",
        "GoLand": "编程",
        "Rider": "编程",
        "Android Studio": "编程",
        "Cursor": "编程",
        "Windsurf": "编程",
        "Terminal": "编程",
        "Word": "办公",
        "Excel": "办公",
        "PowerPoint": "办公",
        "WPS": "办公",
        "Outlook": "邮件",
        "Notion": "办公",
        "Obsidian": "阅读",
        "Typora": "阅读",
        "微信": "社交",
        "QQ": "社交",
        "企业微信": "社交",
        "飞书": "社交",
        "钉钉": "社交",
        "Slack": "社交",
        "Discord": "社交",
        "Telegram": "社交",
        "Steam": "游戏",
        "PotPlayer": "视频",
        "VLC": "视频",
    }
    BACKGROUND_ACTIVITY_WORK_SITES = frozenset(
        {
            "GitHub",
            "GitLab",
            "Gitee",
            "Stack Overflow",
            "LeetCode",
            "稀土掘金",
            "Notion",
            "Figma",
            "飞书",
            "腾讯文档",
            "微信文档",
            "语雀",
            "Confluence",
            "Jira",
            "Linear",
            "Trello",
            "Asana",
            "Google Docs",
            "Google Drive",
        }
    )
    BACKGROUND_ACTIVITY_MAIL_SITES = frozenset({"Gmail", "Outlook"})
    BACKGROUND_ACTIVITY_SOCIAL_SITES = frozenset({"Slack", "Discord", "Teams", "X", "微博", "小红书"})
    BACKGROUND_ACTIVITY_ENTERTAINMENT_SITES = frozenset(
        {"Bilibili", "YouTube", "Netflix", "淘宝", "京东", "豆瓣"}
    )

    def _load_observations(self):
        """加载观察记录。"""
        try:
            import json
            import os
            observations_file = os.path.join(self.observation_storage, "observations.json")
            if os.path.exists(observations_file):
                with open(observations_file, "r", encoding="utf-8") as f:
                    self.observations = json.load(f)
                    if len(self.observations) > self.max_observations:
                        # 每次达到上限时删除5条，保留15条
                        self.observations = self.observations[-15:]
        except Exception as e:
            logger.error(f"加载观察记录失败: {e}")
            self.observations = []

    def _save_observations(self):
        """保存观察记录。"""
        try:
            import json
            import os
            observations_file = os.path.join(self.observation_storage, "observations.json")
            if len(self.observations) > self.max_observations:
                # 每次达到上限时删除6条，保留3天的记录（每天最多3条）
                self.observations = self.observations[-9:]
            # 整理和补正未知观察记录
            self._cleanup_unknown_observations()
            with open(observations_file, "w", encoding="utf-8") as f:
                json.dump(self.observations, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存观察记录失败: {e}")

    def _cleanup_unknown_observations(self):
        """整理和补正观察记录中的"未知"场景。"""
        if not self.observations:
            return
        
        # 统计未知场景的数量
        unknown_count = sum(1 for obs in self.observations if obs.get("scene", "") == "未知")
        
        # 如果未知场景数量较多，进行整理
        if unknown_count > 5:
            logger.info(f"开始整理未知观察记录，共 {unknown_count} 条")
            
            # 遍历观察记录，尝试补正未知场景
            for obs in self.observations:
                if obs.get("scene", "") == "未知":
                    # 尝试根据窗口标题和描述补正场景
                    window_title = obs.get("window_title", "")
                    description = obs.get("description", "")
                    
                    # 首先尝试根据窗口标题识别场景
                    if window_title:
                        scene = self._identify_scene(window_title)
                        if scene != "未知":
                            obs["scene"] = scene
                            logger.info(f"已补正场景: {window_title} -> {scene}")
                            continue
                    
                    # 如果窗口标题识别失败，尝试根据描述识别场景
                    if description:
                        # 简单的描述匹配
                        description_lower = description.lower()
                        scene_keywords = {
                            "编程": ["code", "program", "开发", "编程", "debug", "代码"],
                            "设计": ["design", "设计", "美术", "绘图", "创意"],
                            "办公": ["document", "excel", "word", "办公", "工作"],
                            "游戏": ["game", "游戏", "play", "玩家", "关卡"],
                            "视频": ["video", "电影", "视频", "播放", "tv"],
                            "阅读": ["read", "book", "阅读", "书籍", "文档"],
                            "音乐": ["music", "歌曲", "音乐", "audio"],
                            "社交": ["chat", "社交", "聊天", "message"],
                        }
                        
                        for scene, keywords in scene_keywords.items():
                            if any(keyword in description_lower for keyword in keywords):
                                obs["scene"] = scene
                                logger.info(f"已根据描述补正场景: {description[:50]} -> {scene}")
                                break
        
        # 清理后再次统计未知场景数量
        new_unknown_count = sum(1 for obs in self.observations if obs.get("scene", "") == "未知")
        if new_unknown_count < unknown_count:
            logger.info(f"未知场景整理完成，从 {unknown_count} 条减少到 {new_unknown_count} 条")

    def _add_observation(
        self,
        scene,
        recognition_text,
        active_window_title,
        extra: dict[str, Any] | None = None,
    ):
        """添加一条观察记录。"""
        import datetime
        scene = self._normalize_scene_label(scene)
        active_window_title = self._normalize_window_title(active_window_title)
        should_store, reason = self._should_store_observation(
            scene, recognition_text, active_window_title
        )
        if not should_store:
            logger.info(f"跳过观察记录写入: {reason}")
            return False
        observation = {
            "timestamp": datetime.datetime.now().isoformat(),
            "scene": scene,
            "window_title": active_window_title,
            "description": recognition_text[:200],
        }
        if isinstance(extra, dict):
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                observation[key] = value
        self.observations.append(observation)
        if len(self.observations) > self.max_observations:
            # 每次达到上限时删除6条，保留3天的记录（每天最多3条）
            self.observations = self.observations[-9:]
        self._save_observations()
        return True

    def _load_diary_metadata(self):
        """加载日记元数据。"""
        self.diary_metadata = {}
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
        """保存日记元数据。"""
        try:
            import json
            import os
            with open(self.diary_metadata_file, "w", encoding="utf-8") as f:
                json.dump(self.diary_metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存日记元数据失败: {e}")

    def _update_diary_view_status(self, date_str):
        """记录某天日记已被查看。"""
        import datetime
        if date_str not in self.diary_metadata:
            self.diary_metadata[date_str] = {}
        self.diary_metadata[date_str]["viewed"] = True
        self.diary_metadata[date_str]["viewed_at"] = datetime.datetime.now().isoformat()
        self._save_diary_metadata()
        logger.info(f"更新日记查看状态: {date_str} - 已查看")

    def _load_long_term_memory(self):
        """加载长期记忆。"""
        try:
            import json
            import os
            if os.path.exists(self.long_term_memory_file):
                with open(self.long_term_memory_file, "r", encoding="utf-8") as f:
                    self.long_term_memory = json.load(f)
                self._clean_long_term_memory_noise()
                logger.info("长期记忆加载成功")
        except Exception as e:
            logger.error(f"加载长期记忆失败: {e}")
            self.long_term_memory = {}

    def _save_long_term_memory(self):
        """保存长期记忆。"""
        try:
            import json
            import os
            self._clean_long_term_memory_noise()
            with open(self.long_term_memory_file, "w", encoding="utf-8") as f:
                json.dump(self.long_term_memory, f, ensure_ascii=False, indent=2)
            logger.info("长期记忆保存成功")
        except Exception as e:
            logger.error(f"保存长期记忆失败: {e}")

    @staticmethod
    def _normalize_scene_label(scene: str) -> str:
        scene = str(scene or "").strip()
        invalid_labels = {"", "??", "unknown", "???", "?????", "none", "null", "未知"}
        return "" if scene.lower() in invalid_labels or scene in invalid_labels else scene

    @staticmethod
    def _normalize_window_title(window_title: str) -> str:
        window_title = str(window_title or "").strip()
        invalid_titles = {"", "未知", "unknown", "宿主机截图", "none", "null"}
        if window_title.lower() in invalid_titles or window_title in invalid_titles:
            return ""
        return window_title

    @staticmethod
    def _normalize_record_text(text: str) -> str:
        import re

        text = str(text or "").strip().lower()
        if not text:
            return ""
        text = re.sub(r"```[\s\S]*?```", " ", text)
        text = re.sub(r"`[^`]+`", " ", text)
        text = re.sub(r"[*#>\-_=~]+", " ", text)
        text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_shared_activity_summary(summary: str) -> str:
        import re

        summary = str(summary or "").strip()
        if not summary:
            return ""
        summary = re.sub(r"\s+", " ", summary)
        return summary[:60]

    def _ensure_long_term_memory_defaults(self) -> None:
        """确保长期记忆结构完整。"""
        if not isinstance(self.long_term_memory, dict):
            self.long_term_memory = {}

        self.long_term_memory.setdefault("applications", {})
        self.long_term_memory.setdefault("scenes", {})
        self.long_term_memory.setdefault(
            "user_preferences",
            {
                "music": {},
                "movies": {},
                "food": {},
                "hobbies": {},
                "other": {},
            },
        )
        self.long_term_memory.setdefault("memory_associations", {})
        self.long_term_memory.setdefault("memory_priorities", {})
        self.long_term_memory.setdefault("shared_activities", {})
        self.long_term_memory.setdefault("episodic_memories", [])
        self.long_term_memory.setdefault("focus_patterns", {})

    @staticmethod
    def _user_preference_category_label(category: str) -> str:
        labels = {
            "music": "偏爱的音乐",
            "movies": "喜欢的内容",
            "food": "偏好的食物",
            "hobbies": "平时爱做的事",
            "other": "你在意的点",
        }
        return labels.get(str(category or "").strip(), "偏好")

    @staticmethod
    def _map_preference_category(category: str) -> str:
        category = str(category or "").strip()
        category_map = {
            "watch_media": "movies",
            "game": "hobbies",
            "test": "other",
        }
        return category_map.get(category, category or "other")

    @staticmethod
    def _clip_preference_fragment(text: str, limit: int = 24) -> str:
        fragment = " ".join(str(text or "").split()).strip("，,；;。.!！?？:： ")
        if fragment.startswith("是"):
            fragment = fragment[1:].strip()
        if len(fragment) <= limit:
            return fragment
        return fragment[:limit].rstrip("，,；;。.!！?？:： ") + "..."

    def _compact_user_preference_text(self, category: str, preference: str) -> str:
        import re

        mapped_category = self._map_preference_category(category)
        text = " ".join(str(preference or "").split()).strip()
        if not text:
            return ""

        wrapper_match = re.match(
            r"^(?:一起看内容|一起玩游戏|一起做测试|这次共同体验)\s+.+?时提到[:：]\s*(.+)$",
            text,
        )
        if wrapper_match:
            text = wrapper_match.group(1).strip()

        pattern_builders = [
            (r"(?:我)?最?喜欢(.{1,24})", lambda value: f"偏爱{value}"),
            (r"印象最深(?:的)?(?:是)?(.{1,24})", lambda value: f"对{value}印象最深"),
            (r"最戳(?:我)?(?:的)?(?:是)?(.{1,24})", lambda value: f"偏爱{value}"),
            (r"最有感觉(?:的)?(?:是)?(.{1,24})", lambda value: f"偏爱{value}"),
            (r"最好看(?:的)?(?:是)?(.{1,24})", lambda value: f"偏爱{value}"),
            (r"不喜欢(.{1,24})", lambda value: f"不喜欢{value}"),
        ]
        for pattern, builder in pattern_builders:
            match = re.search(pattern, text)
            if not match:
                continue
            fragment = self._clip_preference_fragment(match.group(1))
            if fragment:
                text = builder(fragment)
                break

        if mapped_category == "movies":
            movie_markers = ("角色", "反转", "配乐", "节奏", "氛围", "台词", "镜头", "结局")
            if not text.startswith(("偏爱", "不喜欢", "对")) and any(marker in text for marker in movie_markers):
                text = f"偏爱{text}"
        elif mapped_category == "hobbies":
            game_markers = ("角色", "英雄", "操作", "团战", "翻盘", "对线", "手感", "配合", "节奏")
            if not text.startswith(("游戏里偏爱", "不喜欢", "更在意")) and any(marker in text for marker in game_markers):
                text = f"游戏里偏爱{text}"
        elif mapped_category == "other":
            test_markers = ("结果", "题", "题目", "描述", "分析", "准", "不像我", "像我")
            if not text.startswith(("更在意", "更认同", "不喜欢")) and any(marker in text for marker in test_markers):
                text = f"更在意{text}"

        text = self._clip_preference_fragment(text, limit=32)
        if mapped_category == "hobbies" and text.startswith("偏爱"):
            text = "游戏里" + text
        if mapped_category == "other" and text.startswith("偏爱"):
            text = "更在意" + text[2:]
        return text

    def _merge_preference_items(self, category: str, values: dict[str, Any]) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        if not isinstance(values, dict):
            return merged

        fingerprint_map: dict[str, str] = {}

        for raw_name, raw_data in values.items():
            normalized_name = self._compact_user_preference_text(category, raw_name)
            if not normalized_name:
                continue
            if self._is_low_value_preference_text(category, normalized_name):
                continue

            fingerprint = self._build_preference_fingerprint(category, normalized_name)
            merged_key = fingerprint_map.get(fingerprint, normalized_name)
            if merged_key not in merged:
                fingerprint_map[fingerprint] = merged_key
            elif len(normalized_name) < len(merged_key) and not self._is_low_value_preference_text(category, normalized_name):
                merged[normalized_name] = merged.pop(merged_key)
                fingerprint_map[fingerprint] = normalized_name
                merged_key = normalized_name

            data = dict(raw_data or {})
            item = merged.setdefault(
                merged_key,
                {
                    "count": 0,
                    "last_mentioned": "",
                    "priority": 0,
                },
            )
            item["count"] = int(item.get("count", 0) or 0) + int(data.get("count", 0) or 0)
            current_last = str(item.get("last_mentioned", "") or "")
            incoming_last = str(data.get("last_mentioned", "") or "")
            item["last_mentioned"] = max(current_last, incoming_last)
            item["priority"] = max(
                int(item.get("priority", 0) or 0),
                int(data.get("priority", 0) or 0),
            )
        return merged

    def _build_preference_fingerprint(self, category: str, preference: str) -> str:
        import re

        mapped_category = self._map_preference_category(category)
        text = str(preference or "").strip()
        normalized = self._normalize_record_text(text)
        if not normalized:
            return f"{mapped_category}:empty"

        sentiment = "neg" if normalized.startswith("不喜欢") else "pos"
        replacements = {
            "游戏里偏爱": "",
            "偏爱": "",
            "更在意": "",
            "对": "",
            "印象最深": "",
            "最喜欢": "",
            "我最喜欢": "",
            "我喜欢": "",
        }
        for source, target in replacements.items():
            normalized = normalized.replace(self._normalize_record_text(source), target).strip()

        normalized = re.sub(r"(那个角色|这角色)", "角色", normalized)
        normalized = re.sub(r"(那一段|这一段|中间那段)", "某段内容", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return f"{mapped_category}:{sentiment}:{normalized}"

    def _is_low_value_preference_text(self, category: str, preference: str) -> bool:
        mapped_category = self._map_preference_category(category)
        normalized = self._normalize_record_text(preference)
        if not normalized:
            return True
        if len(normalized) <= 1:
            return True

        generic_values = {
            "偏爱",
            "更在意",
            "游戏里偏爱",
            "喜欢",
            "最喜欢",
            "这个",
            "那个",
            "角色",
            "结果",
            "题目",
            "某段内容",
        }
        if normalized in {self._normalize_record_text(item) for item in generic_values}:
            return True

        if mapped_category == "movies" and normalized in {
            self._normalize_record_text(item)
            for item in ("偏爱角色", "偏爱某段内容", "偏爱氛围")
        }:
            return True
        if mapped_category == "hobbies" and normalized in {
            self._normalize_record_text(item)
            for item in ("游戏里偏爱角色", "游戏里偏爱操作")
        }:
            return True
        if mapped_category == "other" and normalized in {
            self._normalize_record_text(item)
            for item in ("更在意结果", "更在意题目")
        }:
            return True
        return False

    def _get_scene_preference_category_weights(self, scene: str) -> dict[str, int]:
        profile = self._get_scene_behavior_profile(scene)
        if profile["category"] == "entertainment":
            return {
                "music": 5,
                "movies": 5,
                "hobbies": 4,
                "other": 4,
                "food": 2,
            }
        if profile["category"] == "work":
            return {
                "other": 5,
                "hobbies": 3,
                "food": 2,
                "movies": 1,
                "music": 1,
            }
        return {
            "other": 5,
            "hobbies": 4,
            "food": 3,
            "music": 2,
            "movies": 2,
        }

    def _get_user_preference_memory_hints(
        self,
        scene: str,
        active_window_title: str = "",
        *,
        limit: int = 3,
    ) -> list[str]:
        self._ensure_long_term_memory_defaults()
        user_preferences = self.long_term_memory.get("user_preferences", {}) or {}
        if not isinstance(user_preferences, dict):
            return []

        normalized_scene = self._normalize_scene_label(scene)
        normalized_window = self._normalize_window_title(active_window_title)
        context_text = self._normalize_record_text(f"{normalized_scene} {normalized_window}")
        category_weights = self._get_scene_preference_category_weights(normalized_scene)
        ranked_candidates: list[tuple[float, str]] = []

        for category, weight in category_weights.items():
            preferences = user_preferences.get(category, {}) or {}
            if not isinstance(preferences, dict):
                continue

            for pref_name, pref_data in preferences.items():
                pref_name = str(pref_name or "").strip()
                if not pref_name:
                    continue

                pref_priority = int((pref_data or {}).get("priority", 0) or 0)
                pref_count = int((pref_data or {}).get("count", 0) or 0)
                if pref_priority <= 0 and pref_count <= 0:
                    continue

                score = weight * 10 + pref_priority * 4 + pref_count
                normalized_pref = self._normalize_record_text(pref_name)
                if normalized_pref and context_text and normalized_pref in context_text:
                    score += 8

                label = self._user_preference_category_label(category)
                ranked_candidates.append((score, f"可以顺手呼应用户{label}：{pref_name}。"))

        deduped: list[str] = []
        seen = set()
        for _, summary in sorted(ranked_candidates, key=lambda item: item[0], reverse=True):
            normalized_summary = self._normalize_record_text(summary)
            if not normalized_summary or normalized_summary in seen:
                continue
            seen.add(normalized_summary)
            deduped.append(summary)
            if len(deduped) >= limit:
                break
        return deduped

    def _extract_memory_focus(self, text: str, max_length: int = 48) -> str:
        summary = self._compress_recognition_text(text, max_length=max_length)
        summary = str(summary or "").strip().strip(" .。!！?？,，:：;；")
        if not summary:
            return ""
        return summary[:max_length]

    def _remember_episodic_memory(
        self,
        *,
        scene: str,
        active_window: str,
        summary: str,
        response_preview: str = "",
        kind: str = "screen_observation",
    ) -> bool:
        normalized_summary = self._extract_memory_focus(summary, max_length=72)
        if not normalized_summary or self._is_low_value_record_text(normalized_summary):
            return False

        self._ensure_long_term_memory_defaults()
        scene = self._normalize_scene_label(scene)
        active_window = self._normalize_window_title(active_window)
        today = datetime.date.today().isoformat()
        now_ts = datetime.datetime.now().isoformat()
        memories = list(self.long_term_memory.get("episodic_memories", []) or [])

        matched_index = None
        for index, item in enumerate(memories):
            if not isinstance(item, dict):
                continue
            previous_scene = self._normalize_scene_label(item.get("scene", ""))
            previous_window = self._normalize_window_title(item.get("active_window", ""))
            previous_summary = self._extract_memory_focus(item.get("summary", ""), max_length=72)
            if scene and previous_scene and scene != previous_scene:
                continue
            if active_window and previous_window and active_window != previous_window:
                continue
            if self._is_similar_record(normalized_summary, previous_summary, threshold=0.82):
                matched_index = index
                break

        if matched_index is None:
            memories.append(
                {
                    "scene": scene,
                    "active_window": active_window,
                    "summary": normalized_summary,
                    "response_preview": self._truncate_preview_text(response_preview, limit=120),
                    "kind": str(kind or "screen_observation"),
                    "count": 1,
                    "first_seen": today,
                    "last_seen": today,
                    "updated_at": now_ts,
                    "priority": 1,
                }
            )
        else:
            target = memories[matched_index]
            target["count"] = int(target.get("count", 0) or 0) + 1
            target["last_seen"] = today
            target["updated_at"] = now_ts
            if response_preview:
                target["response_preview"] = self._truncate_preview_text(response_preview, limit=120)
            if not target.get("summary"):
                target["summary"] = normalized_summary

        self.long_term_memory["episodic_memories"] = memories
        return True

    def _remember_focus_pattern(
        self,
        *,
        scene: str,
        active_window: str,
        summary: str,
    ) -> bool:
        focus_text = self._extract_memory_focus(summary, max_length=40)
        if not focus_text or self._is_low_value_record_text(focus_text):
            return False

        self._ensure_long_term_memory_defaults()
        scene = self._normalize_scene_label(scene)
        active_window = self._normalize_window_title(active_window)
        if not scene and not active_window:
            return False

        pattern_key = f"{scene or 'general'}::{active_window or 'window'}::{focus_text}"
        today = datetime.date.today().isoformat()
        focus_patterns = self.long_term_memory.setdefault("focus_patterns", {})
        item = focus_patterns.setdefault(
            pattern_key,
            {
                "scene": scene,
                "active_window": active_window,
                "summary": focus_text,
                "count": 0,
                "last_seen": today,
                "priority": 0,
            },
        )
        item["count"] = int(item.get("count", 0) or 0) + 1
        item["last_seen"] = today
        return True

    def _is_low_value_record_text(self, text: str) -> bool:
        normalized = self._normalize_record_text(text)
        if len(normalized) < 12:
            return True

        if self._is_screen_error_text(normalized):
            return True

        low_value_patterns = (
            "看不清",
            "无法识别",
            "识别失败",
            "内容较少",
            "没有明显内容",
            "一个窗口",
            "一个界面",
            "屏幕截图",
            "当前屏幕",
            "未发现明确信息",
            "暂无更多信息",
            "未知内容",
            "不确定",
        )
        return any(pattern in normalized for pattern in low_value_patterns)

    def _is_screen_error_text(self, text: str) -> bool:
        normalized = self._normalize_record_text(text)
        if not normalized:
            return False

        error_patterns = (
            "[识屏异常",
            "识屏异常",
            "外部接口调用失败",
            "视觉分析服务暂时不可用",
            "当前模型暂时不支持这次多模态识别",
            "这次视觉分析没有成功",
            "vision api timeout",
            "vision api",
            "api调用失败",
            "检查配置或稍后再试",
        )
        return any(pattern in normalized for pattern in error_patterns)

    def _is_similar_record(self, current_text: str, previous_text: str, threshold: float = 0.98) -> bool:
        import difflib

        current = self._normalize_record_text(current_text)
        previous = self._normalize_record_text(previous_text)
        if not current or not previous:
            return False
        if current == previous:
            return True
        return difflib.SequenceMatcher(None, current, previous).ratio() >= threshold

    @staticmethod
    def _compress_recognition_text(text: str, max_length: int = 800) -> str:
        import re

        compressed = str(text or "").replace("\r\n", "\n").strip()
        if not compressed:
            return compressed

        compressed = re.sub(r"\n{3,}", "\n\n", compressed)
        lines = [line.strip() for line in compressed.split("\n") if line.strip()]
        if len(lines) > 8:
            compressed = "\n".join(lines[:8])
        else:
            compressed = "\n".join(lines)

        if len(compressed) > max_length:
            compressed = compressed[: max_length - 1].rstrip() + "…"

        return compressed

    def _should_store_observation(self, scene: str, recognition_text: str, active_window_title: str) -> tuple[bool, str]:
        normalized_scene = self._normalize_scene_label(scene)
        normalized_window = self._normalize_window_title(active_window_title)
        normalized_text = self._normalize_record_text(recognition_text)

        if self._is_low_value_record_text(normalized_text):
            return False, "low_value"

        recent_observations = list(getattr(self, "observations", []) or [])[-5:]
        for observation in reversed(recent_observations):
            previous_scene = self._normalize_scene_label(observation.get("scene", ""))
            previous_window = self._normalize_window_title(
                observation.get("active_window") or observation.get("window_title") or ""
            )
            previous_text = (
                observation.get("content")
                or observation.get("description")
                or observation.get("recognition")
                or ""
            )

            same_context = False
            if normalized_window and previous_window and normalized_window == previous_window:
                if normalized_scene and previous_scene and normalized_scene == previous_scene:
                    same_context = True

            if same_context and self._is_similar_record(normalized_text, previous_text):
                return False, "duplicate_observation"

        return True, "ok"

    def _should_store_diary_entry(self, content: str, active_window: str) -> tuple[bool, str]:
        normalized_window = self._normalize_window_title(active_window)
        if self._is_screen_error_text(content):
            return False, "screen_error"
        if self._is_low_value_record_text(content):
            return False, "low_value"

        target_date = self._resolve_diary_target_date().isoformat()
        recent_entries = [
            entry
            for entry in list(getattr(self, "diary_entries", []) or [])
            if str(entry.get("date", target_date) or target_date).strip() == target_date
        ][-3:]
        for entry in reversed(recent_entries):
            previous_window = self._normalize_window_title(entry.get("active_window", ""))
            if normalized_window and previous_window and normalized_window != previous_window:
                continue
            if self._is_similar_record(content, entry.get("content", ""), threshold=0.9):
                return False, "duplicate_diary_entry"

        return True, "ok"

    @staticmethod
    def _limit_ranked_dict_items(items: dict, limit: int, score_keys: tuple[str, ...]) -> dict:
        if not isinstance(items, dict) or len(items) <= limit:
            return items

        def score(entry: tuple[str, Any]) -> tuple:
            _, data = entry
            if not isinstance(data, dict):
                return (0,)
            return tuple(int(data.get(key, 0) or 0) for key in score_keys)

        ranked = sorted(items.items(), key=score, reverse=True)
        return dict(ranked[:limit])

    @staticmethod
    def _sanitize_diary_section_text(text: str) -> str:
        """清理日记段落中的重复标题和无效空行。"""
        import re

        normalized_text = str(text or "")
        normalized_text = re.sub(r"&lt;\s*br\s*/?\s*&gt;", "\n", normalized_text, flags=re.IGNORECASE)
        normalized_text = re.sub(r"<\s*br\s*/?\s*>", "\n", normalized_text, flags=re.IGNORECASE)
        normalized_text = re.sub(r"[〈＜]\s*br\s*/?\s*[〉＞]", "\n", normalized_text, flags=re.IGNORECASE)

        lines = normalized_text.replace("\r\n", "\n").split("\n")
        cleaned_lines = []
        skip_heading_patterns = [
            re.compile(r"^\s*#\s*.+日记\s*$"),
            re.compile(r"^\s*##\s*\d{4}年\d{1,2}月\d{1,2}日.*$"),
            re.compile(r"^\s*##\s*今日感想\s*$"),
            re.compile(r"^\s*##\s*今日观察\s*$"),
            re.compile(r"^\s*天气[:：]\s*.*$"),
            re.compile(r"^\s*[—-]{1,2}\s*\d{4}年\d{1,2}月\d{1,2}日.*$"),
        ]

        for raw_line in lines:
            line = raw_line.strip()
            if not line and not cleaned_lines:
                continue
            if any(pattern.match(line) for pattern in skip_heading_patterns):
                continue
            cleaned_lines.append(raw_line)

        cleaned_text = "\n".join(cleaned_lines).strip()
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
        return cleaned_text

    @staticmethod
    def _parse_clock_to_minutes(value: str) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parts = text.split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            return hour * 60 + minute
        except Exception:
            return None

    @staticmethod
    def _format_diary_duration_label(seconds: float | int) -> str:
        total_seconds = max(0, int(float(seconds or 0)))
        return f"{int(total_seconds // 60)}分{int(total_seconds % 60)}秒"

    @staticmethod
    def _format_diary_clock_label(timestamp_value: float | int | None) -> str:
        try:
            timestamp = float(timestamp_value or 0)
        except Exception:
            timestamp = 0.0
        if timestamp <= 0:
            return ""
        return datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")

    def _get_diary_activity_history_for_date(
        self,
        target_date: datetime.date,
    ) -> list[dict[str, Any]]:
        if hasattr(self, "_get_activity_history_for_stats"):
            activity_history = self._get_activity_history_for_stats() or []
        else:
            activity_history = list(getattr(self, "activity_history", []) or [])

        prepared_history = list(activity_history)
        web_server = getattr(self, "web_server", None)
        if web_server and hasattr(web_server, "_prepare_activity_history_for_display"):
            try:
                prepared_history = web_server._prepare_activity_history_for_display(
                    activity_history
                )
            except Exception as e:
                logger.debug(f"为日记准备活动历史失败: {e}")
                prepared_history = list(activity_history)

        filtered_history: list[dict[str, Any]] = []
        for item in prepared_history or []:
            if not isinstance(item, dict):
                continue
            start_ts = float(item.get("start_time", 0) or 0)
            if start_ts <= 0:
                continue
            try:
                bucket_date = self._resolve_diary_target_date(
                    datetime.datetime.fromtimestamp(start_ts)
                )
            except Exception:
                continue
            if bucket_date != target_date:
                continue

            raw_duration = max(
                0.0,
                float(item.get("raw_duration", item.get("duration", 0)) or 0),
            )
            effective_duration = max(
                0.0,
                float(item.get("effective_duration", raw_duration) or raw_duration),
            )
            if raw_duration <= 0 and effective_duration <= 0:
                continue
            filtered_history.append(dict(item))

        return sorted(
            filtered_history,
            key=lambda item: float(item.get("start_time", 0) or 0),
        )

    def _build_diary_activity_fallback_entries(
        self,
        target_date: datetime.date,
        *,
        max_items: int = 3,
        min_duration_seconds: int = 3 * 60,
        merge_gap_seconds: int = 15 * 60,
    ) -> list[dict[str, str]]:
        day_history = self._get_diary_activity_history_for_date(target_date)
        if not day_history:
            return []

        merged_groups: list[dict[str, Any]] = []
        for item in day_history:
            start_ts = float(item.get("start_time", 0) or 0)
            end_ts = float(item.get("end_time", 0) or 0)
            raw_duration = max(
                0.0,
                float(item.get("raw_duration", item.get("duration", 0)) or 0),
            )
            effective_duration = max(
                0.0,
                float(item.get("effective_duration", raw_duration) or raw_duration),
            )
            display_duration = effective_duration if effective_duration > 0 else raw_duration
            if display_duration < max(0, int(min_duration_seconds or 0)):
                continue
            if end_ts <= start_ts:
                end_ts = start_ts + max(raw_duration, display_duration)

            window = self._normalize_window_title(item.get("window") or "")
            app_name = str(item.get("app_name", "") or "").strip()
            site_label = str(item.get("site_label", "") or "").strip()
            page_title = str(item.get("page_title", "") or "").strip()
            scene = self._normalize_scene_label(item.get("scene") or "")
            idle_trimmed_seconds = max(
                0.0,
                float(item.get("idle_trimmed_seconds", 0) or 0),
            )
            has_input_estimate = bool(item.get("has_input_estimate", False))

            if page_title and site_label:
                focus_label = f"{site_label} 的《{page_title}》"
            elif page_title and app_name:
                focus_label = f"{app_name} 里的《{page_title}》"
            elif page_title:
                focus_label = f"《{page_title}》"
            elif site_label:
                focus_label = site_label
            elif app_name:
                focus_label = app_name
            else:
                focus_label = window or "当前窗口"

            normalized_window = window or focus_label
            group_key = (normalized_window, focus_label, scene)

            if merged_groups:
                previous = merged_groups[-1]
                gap_seconds = start_ts - float(previous.get("end_ts", 0) or 0)
                if (
                    previous.get("group_key") == group_key
                    and 0 <= gap_seconds <= max(0, int(merge_gap_seconds or 0))
                ):
                    previous["end_ts"] = max(
                        float(previous.get("end_ts", 0) or 0),
                        end_ts,
                    )
                    previous["raw_duration"] = float(
                        previous.get("raw_duration", 0) or 0
                    ) + raw_duration
                    previous["effective_duration"] = float(
                        previous.get("effective_duration", 0) or 0
                    ) + display_duration
                    previous["idle_trimmed_seconds"] = float(
                        previous.get("idle_trimmed_seconds", 0) or 0
                    ) + idle_trimmed_seconds
                    previous["has_input_estimate"] = bool(
                        previous.get("has_input_estimate", False)
                        or has_input_estimate
                    )
                    continue

            merged_groups.append(
                {
                    "group_key": group_key,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "raw_duration": raw_duration,
                    "effective_duration": display_duration,
                    "idle_trimmed_seconds": idle_trimmed_seconds,
                    "has_input_estimate": has_input_estimate,
                    "window": normalized_window,
                    "focus_label": focus_label,
                    "scene": scene,
                }
            )

        if not merged_groups:
            return []

        max_items = max(1, int(max_items or 1))
        selected_indexes = sorted(
            sorted(
                range(len(merged_groups)),
                key=lambda idx: (
                    float(merged_groups[idx].get("effective_duration", 0) or 0),
                    float(merged_groups[idx].get("raw_duration", 0) or 0),
                ),
                reverse=True,
            )[:max_items],
            key=lambda idx: float(merged_groups[idx].get("start_ts", 0) or 0),
        )

        fallback_entries: list[dict[str, str]] = []
        for idx in selected_indexes:
            group = merged_groups[idx]
            window = str(group.get("window", "") or "").strip() or "当前窗口"
            focus_label = str(group.get("focus_label", "") or "").strip() or window
            scene = str(group.get("scene", "") or "").strip()
            display_duration = float(group.get("effective_duration", 0) or 0)
            raw_duration = float(group.get("raw_duration", 0) or 0)
            idle_trimmed_seconds = float(group.get("idle_trimmed_seconds", 0) or 0)
            has_input_estimate = bool(group.get("has_input_estimate", False))

            content = (
                f"从窗口轨迹看，你在 {focus_label} 停留了约 "
                f"{self._format_diary_duration_label(display_duration)}"
            )
            if window and focus_label != window:
                content += f"，窗口是《{window}》"
            if scene:
                content += f"，当时更像在{scene}"
            if has_input_estimate and idle_trimmed_seconds >= 3 * 60:
                content += (
                    f"，按本地输入估算，真正有操作的大约是 "
                    f"{self._format_diary_duration_label(max(0.0, raw_duration - idle_trimmed_seconds))}"
                )
            content += "。"

            start_ts = float(group.get("start_ts", 0) or 0)
            clock_label = self._format_diary_clock_label(start_ts) or "00:00"
            fallback_entries.append(
                {
                    "date": target_date.isoformat(),
                    "time": f"{clock_label}:00" if len(clock_label) == 5 else clock_label,
                    "timestamp": datetime.datetime.fromtimestamp(start_ts).isoformat(
                        timespec="seconds"
                    )
                    if start_ts > 0
                    else f"{target_date.isoformat()}T{clock_label[:5]}:00",
                    "content": content,
                    "active_window": window,
                }
            )

        return fallback_entries

    def _build_diary_activity_fallback_context(
        self,
        entries: list[dict[str, Any]] | None,
    ) -> str:
        valid_entries = [
            entry for entry in (entries or []) if isinstance(entry, dict)
        ]
        if not valid_entries:
            return ""

        lines = ["当天窗口轨迹补充："]
        for index, entry in enumerate(valid_entries, 1):
            time_label = str(entry.get("time", "") or "").strip()[:5]
            prefix = f"{index}. [{time_label}] " if time_label else f"{index}. "
            lines.append(prefix + str(entry.get("content", "") or "").strip())
        return "\n".join(lines).strip()

    def _compact_diary_entries(self, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compacted: list[dict[str, Any]] = []
        for raw_entry in entries or []:
            entry_text = str(raw_entry.get("content") or "").strip()
            normalized_text = self._normalize_record_text(entry_text)
            if self._is_low_value_record_text(normalized_text):
                continue

            active_window = self._normalize_window_title(raw_entry.get("active_window") or "") or "当前窗口"
            time_text = str(raw_entry.get("time") or "").strip() or "--:--"
            entry_minutes = self._parse_clock_to_minutes(time_text)

            if compacted:
                previous = compacted[-1]
                same_window = previous["active_window"] == active_window
                last_minutes = previous.get("last_minutes")
                close_in_time = (
                    entry_minutes is not None
                    and last_minutes is not None
                    and 0 <= entry_minutes - last_minutes <= 12
                )
                similar_to_previous = self._is_similar_record(
                    normalized_text,
                    previous.get("last_text", ""),
                    threshold=0.82,
                )
                if same_window and close_in_time and similar_to_previous:
                    previous["end_time"] = time_text
                    previous["last_minutes"] = entry_minutes
                    if not previous["points"] or not self._is_similar_record(
                        normalized_text,
                        previous["points"][-1],
                        threshold=0.9,
                    ):
                        previous["points"].append(entry_text)
                    previous["last_text"] = normalized_text
                    continue

            compacted.append(
                {
                    "start_time": time_text,
                    "end_time": time_text,
                    "active_window": active_window,
                    "points": [entry_text],
                    "last_text": normalized_text,
                    "last_minutes": entry_minutes,
                }
            )

        return compacted

    def _is_continuing_memory_context(self, scene: str, active_window: str) -> bool:
        normalized_scene = self._normalize_scene_label(scene)
        normalized_window = self._normalize_window_title(active_window)
        app_name = normalized_window.split(" - ")[-1] if " - " in normalized_window else normalized_window
        app_name = self._normalize_window_title(app_name)

        recent_observations = list(getattr(self, "observations", []) or [])[-3:]
        if len(recent_observations) < 3:
            return False

        for observation in recent_observations:
            previous_scene = self._normalize_scene_label(observation.get("scene", ""))
            previous_window = self._normalize_window_title(
                observation.get("active_window") or observation.get("window_title") or ""
            )
            previous_app = previous_window.split(" - ")[-1] if " - " in previous_window else previous_window
            previous_app = self._normalize_window_title(previous_app)

            if normalized_scene and previous_scene != normalized_scene:
                return False
            if app_name and previous_app != app_name:
                return False

        return bool(normalized_scene or app_name)

    def _build_diary_reflection_prompt(
        self,
        observation_text: str,
        viewed_count: int,
        reference_days: list[dict] | None = None,
    ) -> str:
        reference_days = reference_days or []
        mood_hint = {
            0: "今天还没有被查看过，语气可以更像刚写好的当日心绪。",
            1: "今天已经被查看过一次，语气自然一些，不要太用力重复。",
            2: "今天已经被查看过多次，重点放在新的感受和更有价值的总结。",
        }.get(viewed_count, "今天这篇日记已经被看过很多次了，请避免重复表达。")

        prompt_parts = [
            "请根据今天的观察记录，写一段更像私人日记的“今日感想”。",
            "口吻要像陪在用户身边的人，夜里回头想想今天，而不是写工作复盘、日报或任务总结。",
            "控制在 2 到 3 段，挑 1 到 2 个最具体的瞬间来写，允许有情绪，但不要端着，也不要堆分析术语。",
            "可以轻轻提到卡住的地方或明天的延续点，但不要布置任务，不要写成“建议你现在就”“最好立刻”这种命令句。",
            "避免过度夸张、过度吹捧或像旁白一样点评用户，不要写“效率高得让人惊喜”“感同身受”“精准打磨”“近乎偏执”“挺迷人”这类悬浮表达。",
            "不要使用加粗、HTML 标签、条目列表或小标题，直接写正文。",
            "字数控制在 180 到 320 字。",
            f"额外要求：{mood_hint}",
            "",
            "今日观察：",
            observation_text or "今天没有留下有效观察，请写得更克制一些。",
        ]

        if reference_days:
            prompt_parts.extend(["", "可参考前几天的日记风格："])
            for day in reference_days:
                prompt_parts.append(f"### {day['date']}")
                prompt_parts.append(str(day.get('content') or '')[:500])

        return "\n".join(prompt_parts)

    def _build_vision_prompt(self, scene: str, active_window_title: str = "") -> str:
        base_prompt = str(self.image_prompt or "").strip()
        normalized_scene = self._normalize_scene_label(scene)
        normalized_window = self._normalize_window_title(active_window_title)

        prompt_parts = []
        if base_prompt:
            prompt_parts.append(base_prompt)

        if normalized_window:
            prompt_parts.append(f"当前窗口标题：{normalized_window}")

        bot_self_info = []
        if hasattr(self, 'bot_appearance') and self.bot_appearance:
            bot_self_info.append(f"Bot的外形描述：{self.bot_appearance}")

        if hasattr(self, 'long_term_memory') and self.long_term_memory.get('self_image'):
            self_image_memories = self.long_term_memory['self_image']
            sorted_memories = sorted(self_image_memories, key=lambda x: x.get('count', 0), reverse=True)[:3]
            if sorted_memories:
                bot_self_info.append("关于Bot自身的已知信息：")
                for memory in sorted_memories:
                    bot_self_info.append(f"- {memory['content']}")

        if bot_self_info:
            prompt_parts.extend(bot_self_info)
            prompt_parts.append("如果在屏幕中发现符合Bot外形描述的元素，请识别为Bot自己。")

        scene_prompts = {
            "编程": "重点识别当前文件、报错、代码修改点、运行结果或卡住的位置，优先给能直接落地的下一步建议。",
            "设计": "重点识别当前画板、组件、布局变化和明显的视觉问题，建议只给一条最值得先改的点。",
            "浏览": "重点识别当前页面类型、正在查看的信息和最关键的一处内容，不要把整页都复述一遍。",
            "办公": "重点识别当前文档、表格、邮件或会议页面里最关键的任务进度与异常。",
            "游戏": "重点识别能明确看清的游戏事实。只有当英雄名、模式名、装备名、比分或战况在画面里清晰可读时才可以提；看不清就直接写未看清，不要按常见套路猜。",
            "视频": "重点识别当前视频内容或播放器状态，语气保持轻，不要打断沉浸感。",
            "阅读": "重点识别正在读的材料主题、当前段落或页面位置，不要扩展成泛泛的总结。",
        }

        prompt_parts.extend(
            [
                scene_prompts.get(
                    normalized_scene,
                    "重点识别当前正在进行的活动、最关键的确定线索，以及此刻是否有明显异常或下一步。",
                ),
                "输出要求：",
                "1. 只写你能从当前画面直接确认的事实。",
                "2. 如果某个细节不能确认，明确标注“未看清”或“不确定”。",
                "3. 不要为了显得具体而编造细节，不要把猜测写成已发生事实。",
                "4. 不要输出大段界面描写，不要复述每一个按钮和装饰元素。",
                "5. 最后一行如需建议，只给一句最值得的建议；没有必要就不写。",
            ]
        )

        return "\n".join(part for part in prompt_parts if part).strip()

    def _extract_screen_assist_prompt(self, message: str, *, allow_implicit: bool = True) -> str:
        import re

        text = str(message or "").strip()
        normalized = re.sub(r"\s+", "", text.lower())
        if not normalized or normalized.startswith("/"):
            return ""

        # 提取并忽略bot名称
        bot_name = getattr(self, "bot_name", "").strip().lower()
        if bot_name and bot_name in normalized:
            # 移除bot名称部分
            normalized = normalized.replace(bot_name, "")
            # 同时处理原文本，移除bot名称
            text = re.sub(re.escape(bot_name), "", text, flags=re.IGNORECASE)
            text = text.strip()
            normalized = re.sub(r"\s+", "", text.lower())

        request_prefixes = (
            "帮我",
            "你帮我",
            "请帮我",
            "麻烦帮我",
            "麻烦你帮我",
            "可以帮我",
            "能不能帮我",
        )
        has_request_prefix = any(normalized.startswith(prefix) for prefix in request_prefixes)

        request_markers = (
            "帮我看看",
            "帮我看下",
            "帮我看一下",
            "你帮我看看",
            "你帮我看下",
            "你帮我看一下",
            "帮忙看看",
            "帮忙看下",
            "帮我分析",
            "帮我分析一下",
            "帮我分析下",
            "分析一下",
            "分析下",
            "给点建议",
            "帮我看看屏幕",
            "帮我看下屏幕",
            "帮我看一下屏幕",
            "帮我看看截图",
            "帮我看下截图",
            "帮我看看报错",
            "帮我看看代码",
            "帮我看看题目",
            "看看屏幕",
            "看下屏幕",
            "看一下屏幕",
            "看看截图",
            "看下截图",
        )
        screen_context_markers = (
            "屏幕",
            "画面",
            "窗口",
            "截图",
            "识屏",
            "界面",
            "页面",
        )
        task_context_markers = (
            "报错",
            "代码",
            "文档",
            "作业",
            "游戏",
            "题目",
            "插件",
            "网页",
            "装备",
            "日志",
        )
        # 应用启动器相关的排除标记，避免与应用启动器插件冲突。
        # 这里改成“更像启动器请求时才排除”，避免把“帮我看看这个网页报错”之类正常识屏求助误杀。
        app_launcher_action_markers = (
            "打开",
            "启动",
            "运行",
            "开启",
            "搜索",
            "查找",
            "查询",
            "搜一下",
            "查一下",
            "打开一下",
            "启动一下",
            "运行一下",
        )
        app_launcher_target_markers = (
            "浏览器",
            "网页",
            "网站",
            "网址",
            "网页链接",
            "网站链接",
            "http://",
            "https://",
            ".com",
            ".cn",
            ".org",
            ".net",
            ".io",
            "百度",
            "直播间",
            "直播页",
            "动态页",
            "最新动态",
            "最新视频",
            "投稿",
            "应用",
            "程序",
            "软件",
            "app",
        )
        negative_markers = (
            "不用看",
            "别看",
            "不用截图",
            "别截图",
            "不用识屏",
            "不要识屏",
            "别帮我",
            "不用帮我",
            "不要帮我",
        )

        # 先检查否定标记，避免误触发
        if any(marker in normalized for marker in negative_markers):
            return ""

        has_request = has_request_prefix or any(marker in normalized for marker in request_markers)
        has_screen_context = any(marker in normalized for marker in screen_context_markers)
        has_task_context = any(marker in normalized for marker in task_context_markers)
        looks_like_launcher_request = (
            has_request_prefix
            and any(marker in normalized for marker in app_launcher_action_markers)
            and any(marker in normalized for marker in app_launcher_target_markers)
            and not has_screen_context
            and not has_task_context
        )
        if looks_like_launcher_request:
            return ""

        implicit_patterns = (
            r"我(现在)?(在干嘛|在做什么)",
            r"(这|当前|现在).{0,8}(一步|页面|页|界面|题|关|关卡).{0,12}(怎么|怎么办|该怎么|该点哪里|点哪里)",
            r"(这个|这条|这段)(报错|错误).{0,12}(什么意思|怎么解决|怎么办|咋办)",
            r"(我)?(现在)?卡(住了|哪了|在哪|在这|这里)",
            r"(问题出在哪|哪里有问题|哪错了|哪里不对)",
            r"(接下来|下一步).{0,8}(怎么|怎么办|该怎么)",
            r"我(现在)?该怎么办",
            r"(这里|这一页|这页|这个界面).{0,10}(该点哪里|点哪里|看哪里)",
        )
        explicit_scene_questions = (
            "我现在在干嘛",
            "我现在在做什么",
            "我在干嘛",
            "我在做什么",
            "我卡住了",
            "我卡哪了",
            "我卡在哪",
            "这一步怎么做",
            "接下来怎么做",
            "下一步怎么做",
            "这个报错什么意思",
            "这个错误什么意思",
            "这一步该点哪里",
            "这一页该点哪里",
            "这页该点哪里",
            "我现在该怎么办",
        )
        strict_visual_markers = (
            "现在",
            "当前",
            "这一步",
            "这里",
            "这个",
            "这页",
            "这一页",
            "界面",
            "页面",
            "屏幕",
            "画面",
            "窗口",
            "截图",
            "卡住了",
            "卡哪了",
            "卡在哪",
        )
        short_message_limit = 36
        implicit_matched = any(
            marker in normalized for marker in explicit_scene_questions
        ) or any(re.search(pattern, normalized) for pattern in implicit_patterns)
        has_visual_anchor = any(marker in normalized for marker in strict_visual_markers)
        has_implicit_request = (
            allow_implicit
            and len(normalized) <= short_message_limit
            and implicit_matched
            and has_visual_anchor
        )

        if not has_request and not has_implicit_request:
            return ""

        if not has_implicit_request and not (has_screen_context or has_task_context):
            return ""

        return text[:160]

    def _build_diary_document(
        self,
        target_date,
        weekday: str,
        observation_text: str,
        reflection_text: str,
        structured_summary: dict[str, Any] | None = None,
        weather_info: str = "",
    ) -> str:
        observation_text = self._sanitize_diary_section_text(observation_text)
        reflection_text = self._sanitize_diary_section_text(reflection_text)
        structured_summary = structured_summary or {}

        parts = []
        if weather_info:
            parts.extend([f"天气：{weather_info}", ""])

        parts.extend(
            [
                "## 今日感想",
                "",
                reflection_text,
            ]
        )

        summary_lines = self._build_diary_summary_markdown(structured_summary)
        if summary_lines:
            parts.extend(["", "## 今日概览", "", *summary_lines])

        if observation_text:
            parts.extend(["", "## 今日观察", "", observation_text])

        parts.extend(["", f"—— {target_date.strftime('%Y年%m月%d日')} {weekday}"])
        return "\n".join(parts).strip() + "\n"

    def _extract_actionable_suggestions(
        self,
        reflection_text: str,
        *,
        limit: int = 3,
    ) -> list[str]:
        text = str(reflection_text or "").strip()
        if not text:
            return []

        import re

        raw_sentences = [
            sentence.strip()
            for sentence in re.split(r"[。\n！？!?\r]+", text)
            if sentence.strip()
        ]
        prioritized = []
        fallback = []
        keywords = ("建议", "记得", "可以", "优先", "先", "下次", "别忘了", "不如")
        for sentence in raw_sentences:
            clean_sentence = sentence.lstrip("-• ").strip()
            if not clean_sentence:
                continue
            if any(keyword in clean_sentence for keyword in keywords):
                prioritized.append(clean_sentence)
            else:
                fallback.append(clean_sentence)

        picked = prioritized[:limit]
        if len(picked) < limit:
            picked.extend(fallback[: max(0, limit - len(picked))])

        deduped = []
        seen = set()
        for sentence in picked:
            normalized = self._normalize_record_text(sentence)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(sentence[:80])
        return deduped[:limit]

    def _build_diary_structured_summary(
        self,
        compacted_entries: list[dict[str, Any]],
        reflection_text: str,
    ) -> dict[str, Any]:
        summary = {
            "main_windows": [],
            "longest_task": {},
            "repeated_focuses": [],
            "suggestion_items": self._extract_actionable_suggestions(reflection_text, limit=3),
            "entry_count": len(compacted_entries or []),
        }
        if not compacted_entries:
            return summary

        window_stats: dict[str, dict[str, Any]] = {}
        repeated_focuses = []
        longest_task = None
        longest_span = -1

        for entry in compacted_entries:
            window_title = self._normalize_window_title(entry.get("active_window") or "") or "当前窗口"
            start_minutes = self._parse_clock_to_minutes(entry.get("start_time"))
            end_minutes = self._parse_clock_to_minutes(entry.get("end_time"))
            duration_minutes = 0
            if start_minutes is not None and end_minutes is not None and end_minutes >= start_minutes:
                duration_minutes = end_minutes - start_minutes

            stats = window_stats.setdefault(
                window_title,
                {"groups": 0, "duration_minutes": 0, "points": 0},
            )
            stats["groups"] += 1
            stats["duration_minutes"] += max(1, duration_minutes)
            stats["points"] += len(entry.get("points", []) or [])

            if duration_minutes > longest_span:
                longest_span = duration_minutes
                longest_task = {
                    "window_title": window_title,
                    "time_range": (
                        entry.get("start_time")
                        if entry.get("start_time") == entry.get("end_time")
                        else f"{entry.get('start_time')}-{entry.get('end_time')}"
                    ),
                    "focus": str((entry.get("points", []) or [""])[0] or "").strip()[:90],
                    "duration_minutes": max(1, duration_minutes),
                }

            if stats["groups"] >= 2 or len(entry.get("points", []) or []) >= 2:
                repeated_focuses.append(
                    {
                        "window_title": window_title,
                        "note": str((entry.get("points", []) or [""])[0] or "").strip()[:90],
                    }
                )

        ranked_windows = sorted(
            window_stats.items(),
            key=lambda item: (
                int((item[1] or {}).get("duration_minutes", 0) or 0),
                int((item[1] or {}).get("points", 0) or 0),
                int((item[1] or {}).get("groups", 0) or 0),
            ),
            reverse=True,
        )[:4]
        summary["main_windows"] = [
            {
                "window_title": window_title,
                "duration_minutes": data.get("duration_minutes", 0),
                "groups": data.get("groups", 0),
                "points": data.get("points", 0),
            }
            for window_title, data in ranked_windows
        ]
        summary["longest_task"] = longest_task or {}

        deduped_focuses = []
        seen_focuses = set()
        for item in repeated_focuses:
            key = self._normalize_record_text(
                f"{item.get('window_title', '')} {item.get('note', '')}"
            )
            if not key or key in seen_focuses:
                continue
            seen_focuses.add(key)
            deduped_focuses.append(item)
            if len(deduped_focuses) >= 3:
                break
        summary["repeated_focuses"] = deduped_focuses
        return summary

    def _build_diary_summary_markdown(self, structured_summary: dict[str, Any]) -> list[str]:
        if not isinstance(structured_summary, dict):
            return []

        lines = []
        main_windows = structured_summary.get("main_windows", []) or []
        if main_windows:
            main_window_text = "、".join(
                f"{item.get('window_title', '当前窗口')}（约 {int(item.get('duration_minutes', 0) or 0)} 分钟）"
                for item in main_windows[:3]
            )
            lines.append(f"- 今天大多待在：{main_window_text}")

        longest_task = structured_summary.get("longest_task", {}) or {}
        if longest_task.get("window_title"):
            longest_focus = str(longest_task.get("focus", "") or "").strip()
            longest_line = (
                f"- 待得最久的地方：{longest_task.get('window_title')}，大约 {int(longest_task.get('duration_minutes', 0) or 0)} 分钟"
            )
            if longest_focus:
                longest_line += f"，当时主要在：{longest_focus}"
            lines.append(longest_line)

        repeated_focuses = structured_summary.get("repeated_focuses", []) or []
        if repeated_focuses:
            repeated_text = "；".join(
                f"{item.get('window_title', '当前窗口')}：{item.get('note', '')}"
                for item in repeated_focuses[:2]
            )
            lines.append(f"- 老是绕回来的点：{repeated_text}")

        suggestion_items = structured_summary.get("suggestion_items", []) or []
        if suggestion_items:
            lines.append("- 留给明天：")
            for item in suggestion_items[:3]:
                lines.append(f"  - {item}")

        return lines

    def _build_diary_reflection_fallback(
        self,
        observation_text: str,
        structured_summary: dict[str, Any] | None = None,
    ) -> str:
        structured_summary = structured_summary or {}

        def _clean_text(value: str, limit: int = 90) -> str:
            import re

            text = str(value or "").strip()
            if not text:
                return ""
            text = re.sub(r"^[-*#\s]+", "", text)
            text = re.sub(r"\s+", " ", text).strip(" .。!！?？,，:：;；")
            return text[:limit]

        paragraphs: list[str] = []
        main_windows = structured_summary.get("main_windows", []) or []
        longest_task = structured_summary.get("longest_task", {}) or {}
        repeated_focuses = structured_summary.get("repeated_focuses", []) or []
        suggestion_items = structured_summary.get("suggestion_items", []) or []

        if main_windows:
            window_text = "、".join(
                f"《{item.get('window_title') or '当前窗口'}》"
                for item in main_windows[:2]
            )
            paragraphs.append(
                f"今天大半时间都在 {window_text} 之间来回打转，节奏基本也被这些事牵着走。"
            )

        if longest_task.get("window_title"):
            duration = int(longest_task.get("duration_minutes", 0) or 0)
            focus_text = _clean_text(longest_task.get("focus", ""))
            detail = f"待得最久的还是《{longest_task.get('window_title')}》"
            if duration > 0:
                detail += f"，前后大概磨了 {duration} 分钟"
            if focus_text:
                detail += f"，大多心思都耗在：{focus_text}"
            paragraphs.append(detail + "。")

        if repeated_focuses:
            focus_text = "；".join(
                f"《{item.get('window_title') or '当前窗口'}》里的 {_clean_text(item.get('note', ''), limit=50) or '同类问题'}"
                for item in repeated_focuses[:2]
            )
            paragraphs.append(f"有些地方还是会反复绕回来，主要集中在 {focus_text}。")

        if suggestion_items:
            suggestion_text = "；".join(_clean_text(item, limit=60) for item in suggestion_items[:2] if _clean_text(item, limit=60))
            if suggestion_text:
                paragraphs.append(f"如果明天还接着往下走，先从 {suggestion_text} 这类地方收一收，应该会顺一点。")

        if not paragraphs:
            first_observation = ""
            for raw_line in str(observation_text or "").splitlines():
                cleaned = _clean_text(raw_line, limit=80)
                if cleaned:
                    first_observation = cleaned
                    break
            if first_observation:
                paragraphs.append(
                    f"今天留下来的片段不算多，不过大致还是能拼出一条线，差不多都围着“{first_observation}”这一类事在转。"
                )
            else:
                paragraphs.append(
                    "今天留下来的记录有点零散，还拼不出特别完整的一整段故事，不过那些细碎的推进感还是在。"
                )

        if len(paragraphs) == 1:
            paragraphs.append("先把最明显的那点心绪记下来，等明天再回头看，应该还能顺着今天这口气接上。")

        return "\n\n".join(paragraphs[:3]).strip()

    def _polish_diary_reflection_text(self, text: str) -> str:
        import re

        polished = self._sanitize_diary_section_text(text)
        if not polished:
            return ""

        polished = re.sub(r"</?strong>", "", polished, flags=re.IGNORECASE)
        polished = re.sub(r"</?b>", "", polished, flags=re.IGNORECASE)
        polished = re.sub(r"<[^>]+>", "", polished)

        replacements = [
            ("建议你现在就", "如果之后还想继续，也许可以先"),
            ("建议你立刻", "如果之后还想继续，也许可以先"),
            ("建议你", "如果之后还想继续，也许可以"),
            ("最好立刻", "找个顺手的时候先"),
            ("感同身受", "我也有点被带进那股节奏里"),
            ("看着你", "那会儿"),
            ("高得让人惊喜", "挺顺"),
            ("精准打磨", "继续打磨"),
            ("近乎偏执的追求", "那股认真劲"),
            ("挺迷人的", "让我记了下来"),
        ]
        for source, target in replacements:
            polished = polished.replace(source, target)

        polished = re.sub(r"(?<!\n)-\s+", "", polished)
        polished = re.sub(r"\*\*(.*?)\*\*", r"\1", polished)
        polished = re.sub(r"\n{3,}", "\n\n", polished).strip()
        return polished

    def _ensure_diary_reflection_text(
        self,
        reflection_text: str,
        observation_text: str,
        structured_summary: dict[str, Any] | None = None,
    ) -> str:
        cleaned = self._polish_diary_reflection_text(reflection_text)
        if cleaned:
            return cleaned
        return self._polish_diary_reflection_text(
            self._build_diary_reflection_fallback(
            observation_text=observation_text,
            structured_summary=structured_summary,
            )
        )

    def _extract_diary_preview_text(self, diary_content: str) -> str:
        import re

        text = str(diary_content or "").replace("\r\n", "\n").strip()
        if not text:
            return ""

        section_patterns = [
            r"##\s*今日感想\s*([\s\S]*?)(?=\n##\s*[^\n]+|$)",
            r"##\s*[^ \n]*总结\s*([\s\S]*?)(?=\n##\s*[^\n]+|$)",
            r"##\s*今日观察\s*([\s\S]*?)(?=\n##\s*[^\n]+|$)",
        ]
        for pattern in section_patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            section_text = self._sanitize_diary_section_text(match.group(1))
            if section_text:
                return section_text[:500]

        lines = []
        skip_patterns = [
            re.compile(r"^\s*#\s*.+日记\s*$"),
            re.compile(r"^\s*##\s*\d{4}年\d{1,2}月\d{1,2}日.*$"),
            re.compile(r"^\s*\*\*天气\*\*:\s*.*$"),
            re.compile(r"^\s*天气[:：]\s*.*$"),
            re.compile(r"^\s*##\s*今日概览\s*$"),
            re.compile(r"^\s*##\s*今日观察\s*$"),
            re.compile(r"^\s*##\s*今日感想\s*$"),
            re.compile(r"^\s*[—-]{1,2}\s*\d{4}年\d{1,2}月\d{1,2}日.*$"),
        ]
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            if any(pattern.match(line) for pattern in skip_patterns):
                continue
            lines.append(raw_line)

        return "\n".join(lines).strip()[:500]

    def _format_diary_preview_message(
        self,
        target_date: datetime.date,
        diary_content: str,
    ) -> str:
        preview_text = self._extract_diary_preview_text(diary_content)
        if len(preview_text) > 500:
            preview_text = preview_text[:497] + "..."
        return (
            f"{self.bot_name} 的日记\n"
            f"{target_date.strftime('%Y年%m月%d日')}\n\n"
            f"{preview_text or '这篇日记里还没有可展示的内容。'}"
        )

    def _get_diary_summary_path(self, target_date: datetime.date) -> str:
        return os.path.join(
            self.diary_storage,
            f"diary_{target_date.strftime('%Y%m%d')}.summary.json",
        )

    def _load_diary_structured_summary(self, target_date: datetime.date) -> dict[str, Any]:
        summary_path = self._get_diary_summary_path(target_date)
        if not os.path.exists(summary_path):
            return {}
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.debug(f"读取日记结构化摘要失败: {e}")
            return {}

    def _save_diary_structured_summary(
        self,
        target_date: datetime.date,
        structured_summary: dict[str, Any],
    ) -> None:
        summary_path = self._get_diary_summary_path(target_date)
        try:
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(structured_summary, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存日记结构化摘要失败: {e}")

    def _remember_diary_summary_memories(
        self,
        target_date: datetime.date,
        structured_summary: dict[str, Any],
    ) -> None:
        if not isinstance(structured_summary, dict):
            return

        diary_date = target_date.isoformat()
        main_windows = structured_summary.get("main_windows", []) or []
        for item in main_windows[:3]:
            window_title = self._normalize_window_title(item.get("window_title", ""))
            if not window_title:
                continue
            duration_minutes = int(item.get("duration_minutes", 0) or 0)
            focus_text = self._extract_memory_focus(item.get("focus", ""), max_length=56)
            summary = f"{diary_date} 主要停留在《{window_title}》约 {duration_minutes} 分钟"
            if focus_text:
                summary += f"，当时在处理：{focus_text}"
            self._remember_episodic_memory(
                scene="",
                active_window=window_title,
                summary=summary,
                kind="diary_summary",
            )
            if focus_text:
                self._remember_focus_pattern(
                    scene="",
                    active_window=window_title,
                    summary=focus_text,
                )

        longest_task = structured_summary.get("longest_task", {}) or {}
        if isinstance(longest_task, dict) and longest_task.get("window_title"):
            longest_summary = (
                f"{diary_date} 最长停留任务是《{longest_task.get('window_title')}》"
            )
            focus_text = self._extract_memory_focus(longest_task.get("focus", ""), max_length=56)
            if focus_text:
                longest_summary += f"，主要在：{focus_text}"
            self._remember_episodic_memory(
                scene="",
                active_window=str(longest_task.get("window_title", "") or ""),
                summary=longest_summary,
                kind="diary_summary",
            )

        repeated_focuses = structured_summary.get("repeated_focuses", []) or []
        for item in repeated_focuses[:3]:
            note_text = self._extract_memory_focus(item.get("note", ""), max_length=48)
            window_title = self._normalize_window_title(item.get("window_title", ""))
            if not note_text:
                continue
            self._remember_focus_pattern(
                scene="",
                active_window=window_title,
                summary=note_text,
            )

    def _clean_long_term_memory_noise(self):
        """Remove low-value labels from long-term memory."""
        memory = getattr(self, "long_term_memory", None)
        if not isinstance(memory, dict):
            return
        self._ensure_long_term_memory_defaults()

        # 保留 self_image 记忆
        self_image_memory = memory.get("self_image", [])

        applications = memory.get("applications", {})
        if isinstance(applications, dict):
            cleaned_applications = {}
            for app_name, data in applications.items():
                normalized_app = self._normalize_window_title(app_name)
                if not normalized_app:
                    continue
                app_data = dict(data or {})
                raw_scenes = app_data.get("scenes", {}) or {}
                cleaned_scenes = {}
                for scene_name, count in raw_scenes.items():
                    normalized_scene = self._normalize_scene_label(scene_name)
                    if normalized_scene:
                        cleaned_scenes[normalized_scene] = count
                app_data["scenes"] = self._limit_ranked_dict_items(
                    cleaned_scenes,
                    limit=20,
                    score_keys=("priority", "usage_count", "count"),
                )
                cleaned_applications[normalized_app] = app_data
            memory["applications"] = self._limit_ranked_dict_items(
                cleaned_applications,
                limit=80,
                score_keys=("priority", "usage_count", "total_duration"),
            )

        scenes = memory.get("scenes", {})
        if isinstance(scenes, dict):
            cleaned_scenes = {}
            for scene_name, data in scenes.items():
                normalized_scene = self._normalize_scene_label(scene_name)
                if normalized_scene:
                    scene_data = dict(data or {})
                    if "usage_count" not in scene_data and "count" in scene_data:
                        scene_data["usage_count"] = int(scene_data.get("count", 0) or 0)
                    cleaned_scenes[normalized_scene] = scene_data
            memory["scenes"] = self._limit_ranked_dict_items(
                cleaned_scenes,
                limit=40,
                score_keys=("priority", "usage_count"),
            )

        associations = memory.get("memory_associations", {})
        if isinstance(associations, dict):
            cleaned_associations = {}
            for assoc_name, data in associations.items():
                if "_" not in assoc_name:
                    continue
                scene_name, app_name = assoc_name.split("_", 1)
                normalized_scene = self._normalize_scene_label(scene_name)
                normalized_app = self._normalize_window_title(app_name)
                if normalized_scene and normalized_app:
                    cleaned_associations[f"{normalized_scene}_{normalized_app}"] = data
            memory["memory_associations"] = self._limit_ranked_dict_items(
                cleaned_associations,
                limit=120,
                score_keys=("count",),
            )

        preferences = memory.get("user_preferences", {})
        if isinstance(preferences, dict):
            cleaned_preferences = {}
            for category, values in preferences.items():
                mapped_category = self._map_preference_category(category)
                filtered = self._merge_preference_items(mapped_category, values)
                if not filtered:
                    continue
                merged_values = dict(cleaned_preferences.get(mapped_category, {}) or {})
                for pref_name, pref_data in filtered.items():
                    target = merged_values.setdefault(
                        pref_name,
                        {
                            "count": 0,
                            "last_mentioned": "",
                            "priority": 0,
                        },
                    )
                    target["count"] = int(target.get("count", 0) or 0) + int(
                        (pref_data or {}).get("count", 0) or 0
                    )
                    target["last_mentioned"] = max(
                        str(target.get("last_mentioned", "") or ""),
                        str((pref_data or {}).get("last_mentioned", "") or ""),
                    )
                    target["priority"] = max(
                        int(target.get("priority", 0) or 0),
                        int((pref_data or {}).get("priority", 0) or 0),
                    )
                cleaned_preferences[mapped_category] = self._limit_ranked_dict_items(
                    merged_values,
                    limit=30,
                    score_keys=("priority", "count"),
                )
            memory["user_preferences"] = cleaned_preferences

        shared_activities = memory.get("shared_activities", {})
        if isinstance(shared_activities, dict):
            cleaned_shared_activities = {}
            for activity_name, data in shared_activities.items():
                normalized_activity = self._normalize_shared_activity_summary(activity_name)
                if not normalized_activity:
                    continue
                activity_data = dict(data or {})
                activity_data["category"] = str(activity_data.get("category", "other") or "other")
                cleaned_shared_activities[normalized_activity] = activity_data
            memory["shared_activities"] = self._limit_ranked_dict_items(
                cleaned_shared_activities,
                limit=60,
                score_keys=("priority", "count"),
            )

        episodic_memories = memory.get("episodic_memories", [])
        if isinstance(episodic_memories, list):
            cleaned_episodes = []
            seen_episode_keys = set()
            for item in episodic_memories:
                if not isinstance(item, dict):
                    continue
                summary = self._extract_memory_focus(item.get("summary", ""), max_length=72)
                if not summary:
                    continue
                scene = self._normalize_scene_label(item.get("scene", ""))
                active_window = self._normalize_window_title(item.get("active_window", ""))
                dedupe_key = (
                    scene.casefold(),
                    active_window.casefold(),
                    self._normalize_record_text(summary),
                )
                if dedupe_key in seen_episode_keys:
                    continue
                seen_episode_keys.add(dedupe_key)
                cleaned_episodes.append(
                    {
                        "scene": scene,
                        "active_window": active_window,
                        "summary": summary,
                        "response_preview": self._truncate_preview_text(
                            item.get("response_preview", ""),
                            limit=120,
                        ),
                        "kind": str(item.get("kind", "screen_observation") or "screen_observation"),
                        "count": int(item.get("count", 0) or 0),
                        "first_seen": str(item.get("first_seen", "") or ""),
                        "last_seen": str(item.get("last_seen", "") or ""),
                        "updated_at": str(item.get("updated_at", "") or ""),
                        "priority": int(item.get("priority", 0) or 0),
                    }
                )
            cleaned_episodes.sort(
                key=lambda item: (
                    int(item.get("priority", 0) or 0),
                    int(item.get("count", 0) or 0),
                    str(item.get("last_seen", "") or ""),
                ),
                reverse=True,
            )
            memory["episodic_memories"] = cleaned_episodes[: self.EPISODIC_MEMORY_LIMIT]

        focus_patterns = memory.get("focus_patterns", {})
        if isinstance(focus_patterns, dict):
            cleaned_focus_patterns = {}
            for pattern_key, data in focus_patterns.items():
                if not isinstance(data, dict):
                    continue
                summary = self._extract_memory_focus(data.get("summary", ""), max_length=48)
                scene = self._normalize_scene_label(data.get("scene", ""))
                active_window = self._normalize_window_title(data.get("active_window", ""))
                if not summary:
                    continue
                normalized_key = f"{scene or 'general'}::{active_window or 'window'}::{summary}"
                cleaned_focus_patterns[normalized_key] = {
                    "scene": scene,
                    "active_window": active_window,
                    "summary": summary,
                    "count": int(data.get("count", 0) or 0),
                    "last_seen": str(data.get("last_seen", "") or ""),
                    "priority": int(data.get("priority", 0) or 0),
                }
            memory["focus_patterns"] = self._limit_ranked_dict_items(
                cleaned_focus_patterns,
                limit=self.FOCUS_PATTERN_LIMIT,
                score_keys=("priority", "count"),
            )
        
        # 恢复 self_image 记忆
        if self_image_memory:
            memory["self_image"] = self_image_memory
        else:
            memory.pop("self_image", None)

    def _update_long_term_memory(
        self,
        scene,
        active_window,
        duration,
        user_preferences=None,
        memory_summary: str = "",
        response_preview: str = "",
    ):
        """更新长期记忆。"""
        import datetime
        today = datetime.date.today().isoformat()
        scene = self._normalize_scene_label(scene)
        active_window = self._normalize_window_title(active_window)

        self._ensure_long_term_memory_defaults()

        app_name = active_window.split(" - ")[-1] if " - " in active_window else active_window
        app_name = self._normalize_window_title(app_name)
        continuing_context = self._is_continuing_memory_context(scene, active_window)

        # 更新应用使用频率
        if app_name:
            if app_name not in self.long_term_memory["applications"]:
                self.long_term_memory["applications"][app_name] = {
                    "usage_count": 0,
                    "total_duration": 0,
                    "last_used": today,
                    "scenes": {},
                    "priority": 0
                }

            app_memory = self.long_term_memory["applications"][app_name]
            if not continuing_context:
                app_memory["usage_count"] += 1
            app_memory["total_duration"] += duration
            app_memory["last_used"] = today

            if scene:
                if scene not in app_memory["scenes"]:
                    app_memory["scenes"][scene] = 0
                if not continuing_context:
                    app_memory["scenes"][scene] += 1

        # 更新场景偏好
        if scene:
            if scene not in self.long_term_memory["scenes"]:
                self.long_term_memory["scenes"][scene] = {
                    "usage_count": 0,
                    "last_used": today,
                    "priority": 0
                }
            if not continuing_context:
                self.long_term_memory["scenes"][scene]["usage_count"] += 1
            self.long_term_memory["scenes"][scene]["last_used"] = today
        
        # 更新用户偏好（如果有）
        if user_preferences:
            for category, preferences in user_preferences.items():
                mapped_category = self._map_preference_category(category)
                if mapped_category not in self.long_term_memory["user_preferences"]:
                    self.long_term_memory["user_preferences"][mapped_category] = {}
                for pref, value in preferences.items():
                    normalized_pref = self._compact_user_preference_text(mapped_category, pref)
                    if not normalized_pref:
                        continue
                    if normalized_pref not in self.long_term_memory["user_preferences"][mapped_category]:
                        self.long_term_memory["user_preferences"][mapped_category][normalized_pref] = {
                            "count": 0,
                            "last_mentioned": today,
                            "priority": 0
                        }
                    self.long_term_memory["user_preferences"][mapped_category][normalized_pref]["count"] += 1
                    self.long_term_memory["user_preferences"][mapped_category][normalized_pref]["last_mentioned"] = today
        
        # 建立记忆关联
        if scene and app_name and not continuing_context:
            self._build_memory_associations(scene, app_name)

        if memory_summary:
            self._remember_episodic_memory(
                scene=scene,
                active_window=active_window,
                summary=memory_summary,
                response_preview=response_preview,
            )
            self._remember_focus_pattern(
                scene=scene,
                active_window=active_window,
                summary=memory_summary,
            )
        
        self._update_memory_priorities()
        
        # 应用记忆衰减
        self._apply_memory_decay()
        
        # 保存长期记忆
        self._save_long_term_memory()

    def _apply_memory_decay(self):
        """对长期记忆做温和清理，避免短期未使用就被抹掉。"""
        import datetime
        today = datetime.date.today()

        if "applications" in self.long_term_memory:
            for app_name, app_data in list(self.long_term_memory["applications"].items()):
                last_used_text = str(app_data.get("last_used", "") or "").strip()
                if not last_used_text:
                    continue
                try:
                    last_used_date = datetime.date.fromisoformat(last_used_text)
                except ValueError:
                    continue

                days_since_used = (today - last_used_date).days
                usage_count = int(app_data.get("usage_count", 0) or 0)
                total_duration = int(app_data.get("total_duration", 0) or 0)
                if (
                    days_since_used > self.LONG_TERM_MEMORY_RETENTION_DAYS
                    and usage_count <= 1
                    and total_duration <= 5
                ):
                    del self.long_term_memory["applications"][app_name]

        if "scenes" in self.long_term_memory:
            for scene_name, scene_data in list(self.long_term_memory["scenes"].items()):
                last_used_text = str(scene_data.get("last_used", "") or "").strip()
                if not last_used_text:
                    continue
                try:
                    last_used_date = datetime.date.fromisoformat(last_used_text)
                except ValueError:
                    continue

                days_since_used = (today - last_used_date).days
                usage_count = int(scene_data.get("usage_count", 0) or 0)
                if (
                    days_since_used > self.LONG_TERM_MEMORY_RETENTION_DAYS
                    and usage_count <= 1
                ):
                    del self.long_term_memory["scenes"][scene_name]

        if "user_preferences" in self.long_term_memory:
            for category, preferences in list(self.long_term_memory["user_preferences"].items()):
                for pref, data in list(preferences.items()):
                    if self._is_low_value_preference_text(category, pref):
                        del preferences[pref]
                        continue
                    last_mentioned_text = str(data.get("last_mentioned", "") or "").strip()
                    if not last_mentioned_text:
                        continue
                    try:
                        last_mentioned_date = datetime.date.fromisoformat(last_mentioned_text)
                    except ValueError:
                        continue
                    days_since_mentioned = (today - last_mentioned_date).days

                    if (
                        days_since_mentioned > self.LIGHT_MEMORY_RETENTION_DAYS
                        and int(data.get("count", 0) or 0) <= 1
                    ):
                        del preferences[pref]
                        continue

                    if days_since_mentioned > 30 and int(data.get("count", 0) or 0) <= 2:
                        data["count"] = max(1, int(data.get("count", 0) or 0) - 1)

                if not preferences:
                    del self.long_term_memory["user_preferences"][category]

        if "shared_activities" in self.long_term_memory:
            for activity_name, activity_data in list(self.long_term_memory["shared_activities"].items()):
                last_shared = str(activity_data.get("last_shared", "") or "").strip()
                if not last_shared:
                    continue
                try:
                    last_shared_date = datetime.date.fromisoformat(last_shared)
                except ValueError:
                    continue

                days_since_shared = (today - last_shared_date).days
                if (
                    days_since_shared > self.LIGHT_MEMORY_RETENTION_DAYS
                    and int(activity_data.get("count", 0) or 0) <= 1
                ):
                    del self.long_term_memory["shared_activities"][activity_name]
                    continue
                if days_since_shared > 30 and int(activity_data.get("count", 0) or 0) <= 2:
                    activity_data["count"] = max(1, int(activity_data.get("count", 0) or 0) - 1)

        episodic_memories = self.long_term_memory.get("episodic_memories", [])
        if isinstance(episodic_memories, list):
            retained_episodes = []
            for item in episodic_memories:
                if not isinstance(item, dict):
                    continue
                last_seen_text = str(item.get("last_seen", "") or "").strip()
                if not last_seen_text:
                    retained_episodes.append(item)
                    continue
                try:
                    last_seen_date = datetime.date.fromisoformat(last_seen_text)
                except ValueError:
                    retained_episodes.append(item)
                    continue
                days_since_seen = (today - last_seen_date).days
                if (
                    days_since_seen > self.LIGHT_MEMORY_RETENTION_DAYS
                    and int(item.get("count", 0) or 0) <= 1
                ):
                    continue
                retained_episodes.append(item)
            self.long_term_memory["episodic_memories"] = retained_episodes

        focus_patterns = self.long_term_memory.get("focus_patterns", {})
        if isinstance(focus_patterns, dict):
            for pattern_key, item in list(focus_patterns.items()):
                if not isinstance(item, dict):
                    del focus_patterns[pattern_key]
                    continue
                last_seen_text = str(item.get("last_seen", "") or "").strip()
                if not last_seen_text:
                    continue
                try:
                    last_seen_date = datetime.date.fromisoformat(last_seen_text)
                except ValueError:
                    continue
                days_since_seen = (today - last_seen_date).days
                if (
                    days_since_seen > self.LIGHT_MEMORY_RETENTION_DAYS
                    and int(item.get("count", 0) or 0) <= 1
                ):
                    del focus_patterns[pattern_key]

    @staticmethod
    def _build_memory_priority_value(base_count: int | float, days_since: int) -> int:
        count = float(base_count or 0)
        days = max(0, int(days_since or 0))
        if count <= 0:
            return 0
        score = count * (1 / (1 + days))
        return max(1, int(round(score)))

    def _build_memory_associations(self, scene, app_name):
        """建立场景与应用之间的记忆关联。"""
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

    def _build_companion_response_guide(self, scene: str, recognition_text: str, custom_prompt: str, context_count: int) -> str:
        """构建同伴响应指南"""
        guide_parts = [
            "用自然聊天的方式回应，不要写成分析报告、客服通知或固定模板。",
            "优先解决用户这轮问题，不要被自己的固定说法带偏。",
            "不要编造，不要过度延伸到当前判断之外的话题。",
            "不要使用 Markdown、加粗、标题、分点或括号旁白。",
            "少用夸张语气词、重复感叹和机械鼓劲，宁可自然一点也不要像脚本播报。",
            "避免每次都用相同开场；尤其不要反复写“原来你在……”“原来在……呀”“刚才那波……好激烈”“我就在这里陪着你”“加油加油”这类套话。",
            "如果这一轮只有一条小观察，就直接说重点，不必硬凑成两三句完整播报。",
            "不要把模糊观察硬写成非常具体的人名、角色名、道具名、地点名或技能名。",
            "默认不要先解释自己看到了什么，而是把观察消化成判断后直接接话。",
        ]

        if bool(getattr(self, "use_companion_mode", False)):
            guide_parts.append(
                "陪伴模式下，更关注一段时间内的状态延续；你的主要任务是知道用户在做什么、状态如何，再顺着聊天自然回应。"
            )
            guide_parts.append(
                "必要时可以顺手引用最近的电脑使用状态，但它只是理解背景，不要喧宾夺主，也不要写成观察播报。"
            )
        if bool(getattr(self, "stealth_watch_mode", False)):
            guide_parts.append(
                "偷看模式下，重点是对用户的行为变化做出反应，比如卡住、切窗口、停顿、结束一局、进入新阶段。"
            )
            guide_parts.append(
                "尽量减少直白监控腔，不要反复写“我看到你”“我刚刚看见你在……”；更像悄悄注意到一点变化后顺口说一句。"
            )

        if scene in ("视频", "阅读"):
            guide_parts.append(
                "当前场景更适合轻一点，别打断用户的沉浸感。"
            )
        elif scene == "游戏":
            guide_parts.append(
                "当前是游戏场景时，优先说看得清的阶段和状态，比如选项界面、对局中、商店里、团战中；不要凭模糊画面猜具体英雄、强化、装备、队友或战术。"
            )
            guide_parts.append(
                "除非用户明确在问攻略，否则不要一上来就教连招、配装、阵容配合；更不要根据猜测下指导。"
            )
        else:
            guide_parts.append(
                "更关注用户眼前的问题和真正有帮助的信息。"
            )

        if context_count > 0:
            guide_parts.append(
                "参考最近对话保持连贯，不要把上一条又换个说法重讲一遍。"
            )

        if custom_prompt:
            guide_parts.append(
                "用户这轮有明确要求时，优先贴着用户的问题回答。"
            )

        if recognition_text:
            guide_parts.append(
                "如果识屏结果里存在“未看清”“不确定”之类的提示，回复里要保留这种不确定性，不要在成文时把它补成肯定句。"
            )

        guide_parts.append(
            "更像一起看屏幕时顺手说的一句话：能具体就具体，没必要就别热场。"
        )
        if scene in ("游戏", "视频", "音乐", "浏览-娱乐"):
            guide_parts.append(
                "娱乐场景下，默认压到 1 到 2 句，别凑成整段夸夸其谈。"
            )

        return "\n".join(guide_parts)

    def _update_memory_priorities(self):
        """根据近期活跃度重新计算记忆优先级。"""
        import datetime
        today = datetime.date.today()
        
        if "applications" in self.long_term_memory:
            for app_name, app_data in self.long_term_memory["applications"].items():
                # 基于使用频率和最近使用时间计算优先级
                last_used_date = datetime.date.fromisoformat(app_data["last_used"])
                days_since_used = (today - last_used_date).days

                app_data["priority"] = self._build_memory_priority_value(
                    app_data.get("usage_count", 0),
                    days_since_used,
                )
        
        if "scenes" in self.long_term_memory:
            for scene_name, scene_data in self.long_term_memory["scenes"].items():
                last_used_date = datetime.date.fromisoformat(scene_data["last_used"])
                days_since_used = (today - last_used_date).days

                scene_data["priority"] = self._build_memory_priority_value(
                    scene_data.get("usage_count", 0),
                    days_since_used,
                )
        
        if "user_preferences" in self.long_term_memory:
            for category, preferences in self.long_term_memory["user_preferences"].items():
                for pref, data in preferences.items():
                    last_mentioned_date = datetime.date.fromisoformat(data["last_mentioned"])
                    days_since_mentioned = (today - last_mentioned_date).days

                    data["priority"] = self._build_memory_priority_value(
                        data.get("count", 0),
                        days_since_mentioned,
                    )

        if "shared_activities" in self.long_term_memory:
            for activity_name, data in self.long_term_memory["shared_activities"].items():
                last_shared = str(data.get("last_shared", "") or "").strip()
                if not last_shared:
                    data["priority"] = int(data.get("count", 0) or 0)
                    continue
                try:
                    last_shared_date = datetime.date.fromisoformat(last_shared)
                except ValueError:
                    data["priority"] = int(data.get("count", 0) or 0)
                    continue

                days_since_shared = (today - last_shared_date).days
                data["priority"] = self._build_memory_priority_value(
                    data.get("count", 0),
                    days_since_shared,
                )

        episodic_memories = self.long_term_memory.get("episodic_memories", [])
        if isinstance(episodic_memories, list):
            for item in episodic_memories:
                if not isinstance(item, dict):
                    continue
                last_seen_text = str(item.get("last_seen", "") or "").strip()
                if not last_seen_text:
                    item["priority"] = int(item.get("count", 0) or 0)
                    continue
                try:
                    last_seen_date = datetime.date.fromisoformat(last_seen_text)
                except ValueError:
                    item["priority"] = int(item.get("count", 0) or 0)
                    continue
                item["priority"] = self._build_memory_priority_value(
                    item.get("count", 0),
                    (today - last_seen_date).days,
                )

        focus_patterns = self.long_term_memory.get("focus_patterns", {})
        if isinstance(focus_patterns, dict):
            for _, item in focus_patterns.items():
                if not isinstance(item, dict):
                    continue
                last_seen_text = str(item.get("last_seen", "") or "").strip()
                if not last_seen_text:
                    item["priority"] = int(item.get("count", 0) or 0)
                    continue
                try:
                    last_seen_date = datetime.date.fromisoformat(last_seen_text)
                except ValueError:
                    item["priority"] = int(item.get("count", 0) or 0)
                    continue
                item["priority"] = self._build_memory_priority_value(
                    item.get("count", 0),
                    (today - last_seen_date).days,
                )

    def _trigger_related_memories(self, scene, app_name):
        """触发与当前场景相关的记忆。"""
        self._ensure_long_term_memory_defaults()
        normalized_scene = self._normalize_scene_label(scene)
        normalized_app = self._normalize_window_title(app_name)
        memory_candidates: list[tuple[float, str]] = []

        episodic_memories = self.long_term_memory.get("episodic_memories", []) or []
        for item in episodic_memories:
            if not isinstance(item, dict):
                continue
            item_scene = self._normalize_scene_label(item.get("scene", ""))
            item_window = self._normalize_window_title(item.get("active_window", ""))
            if normalized_scene and item_scene and normalized_scene != item_scene:
                continue
            if normalized_app and item_window and normalized_app != item_window:
                continue
            summary = self._extract_memory_focus(item.get("summary", ""), max_length=72)
            if not summary:
                continue
            count = int(item.get("count", 0) or 0)
            priority = int(item.get("priority", 0) or 0)
            if count <= 0 and priority <= 0:
                continue
            score = priority * 4 + count * 2
            if normalized_app and item_window and normalized_app == item_window:
                score += 3
            if normalized_scene and item_scene and normalized_scene == item_scene:
                score += 2
            memory_candidates.append(
                (
                    score,
                    f"你前几次在《{item_window or normalized_app or '这个窗口'}》里也在处理：{summary}。",
                )
            )

        focus_patterns = self.long_term_memory.get("focus_patterns", {}) or {}
        for _, item in focus_patterns.items():
            if not isinstance(item, dict):
                continue
            item_scene = self._normalize_scene_label(item.get("scene", ""))
            item_window = self._normalize_window_title(item.get("active_window", ""))
            if normalized_scene and item_scene and normalized_scene != item_scene:
                continue
            if normalized_app and item_window and normalized_app != item_window:
                continue
            summary = self._extract_memory_focus(item.get("summary", ""), max_length=48)
            if not summary:
                continue
            count = int(item.get("count", 0) or 0)
            priority = int(item.get("priority", 0) or 0)
            if count < 2 and priority <= 1:
                continue
            score = priority * 3 + count
            memory_candidates.append(
                (
                    score,
                    f"这个场景里你反复会关注：{summary}。",
                )
            )

        scene_memory = self.long_term_memory.get("scenes", {}).get(normalized_scene, {})
        if normalized_scene and isinstance(scene_memory, dict):
            usage_count = int(scene_memory.get("usage_count", 0) or 0)
            priority = int(scene_memory.get("priority", 0) or 0)
            if usage_count > 0 or priority > 0:
                score = priority * 2 + usage_count
                memory_candidates.append(
                    (
                        score,
                        f"你最近经常处在「{normalized_scene}」场景，适合沿着当前任务继续往前推。",
                    )
                )

        app_memory = self.long_term_memory.get("applications", {}).get(normalized_app, {})
        if normalized_app and isinstance(app_memory, dict):
            usage_count = int(app_memory.get("usage_count", 0) or 0)
            total_duration = int(app_memory.get("total_duration", 0) or 0)
            top_scenes = sorted(
                (app_memory.get("scenes", {}) or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )[:2]
            top_scene_text = "、".join(name for name, _ in top_scenes if name)
            if usage_count > 0 or total_duration > 0:
                score = int(app_memory.get("priority", 0) or 0) * 3 + usage_count + total_duration / 60
                summary = f"你之前经常在《{normalized_app}》里处理{top_scene_text or '当前这类'}任务。"
                memory_candidates.append((score, summary))

        association_key = f"{normalized_scene}_{normalized_app}"
        association_data = self.long_term_memory.get("memory_associations", {}).get(
            association_key,
            {},
        )
        if normalized_scene and normalized_app and isinstance(association_data, dict):
            association_count = int(association_data.get("count", 0) or 0)
            if association_count > 1:
                memory_candidates.append(
                    (
                        association_count * 4,
                        f"「{normalized_scene} + {normalized_app}」这个组合你最近反复出现，可能就是今天的主要任务线。",
                    )
                )

        for preference_hint in self._get_user_preference_memory_hints(
            normalized_scene,
            normalized_app,
            limit=3,
        ):
            memory_candidates.append((3, preference_hint))

        deduped = []
        seen = set()
        for _, summary in sorted(memory_candidates, key=lambda item: item[0], reverse=True):
            normalized_summary = self._normalize_record_text(summary)
            if not normalized_summary or normalized_summary in seen:
                continue
            seen.add(normalized_summary)
            deduped.append(summary)
            if len(deduped) >= 4:
                break

        return deduped

    def _add_user_preference(self, category, preference):
        """添加一条用户偏好。"""
        import datetime
        today = datetime.date.today().isoformat()

        mapped_category = self._map_preference_category(category)
        normalized_preference = self._compact_user_preference_text(
            mapped_category,
            preference,
        )
        if not normalized_preference:
            return

        self._ensure_long_term_memory_defaults()
        if mapped_category not in self.long_term_memory["user_preferences"]:
            self.long_term_memory["user_preferences"][mapped_category] = {}

        if normalized_preference not in self.long_term_memory["user_preferences"][mapped_category]:
            self.long_term_memory["user_preferences"][mapped_category][normalized_preference] = {
                "count": 0,
                "last_mentioned": today,
                "priority": 0
            }

        self.long_term_memory["user_preferences"][mapped_category][normalized_preference]["count"] += 1
        self.long_term_memory["user_preferences"][mapped_category][normalized_preference]["last_mentioned"] = today

        self._update_memory_priorities()
        # 保存记忆
        self._save_long_term_memory()

        logger.info(f"已添加用户偏好: {mapped_category} - {normalized_preference}")

    @staticmethod
    def _shared_activity_category_label(category: str) -> str:
        labels = {
            "watch_media": "一起看过",
            "game": "一起玩过",
            "test": "一起做过测试",
            "screen_interaction": "一起进行过识屏互动",
            "other": "一起做过",
        }
        return labels.get(str(category or "other"), "一起做过")

    def _get_relevant_shared_activities(self, scene: str, limit: int = 3) -> list[tuple[str, dict]]:
        shared_activities = self.long_term_memory.get("shared_activities", {})
        if not isinstance(shared_activities, dict) or not shared_activities:
            return []

        scene = self._normalize_scene_label(scene)
        category_map = {
            "视频": {"watch_media", "screen_interaction"},
            "阅读": {"watch_media", "screen_interaction", "test"},
            "游戏": {"game", "screen_interaction"},
            "学习": {"test", "screen_interaction"},
            "浏览": {"watch_media", "screen_interaction", "test"},
            "浏览-娱乐": {"watch_media", "game", "screen_interaction"},
            "社交": {"screen_interaction"},
        }
        wanted_categories = category_map.get(scene, set())

        ranked_items = sorted(
            shared_activities.items(),
            key=lambda item: (
                int((item[1] or {}).get("priority", 0) or 0),
                int((item[1] or {}).get("count", 0) or 0),
                str((item[1] or {}).get("last_shared", "") or ""),
            ),
            reverse=True,
        )

        matched = []
        fallback = []
        for activity_name, data in ranked_items:
            if not isinstance(data, dict):
                continue
            if int(data.get("priority", 0) or 0) <= 0 and int(data.get("count", 0) or 0) <= 0:
                continue
            item = (activity_name, data)
            if wanted_categories and str(data.get("category", "other") or "other") in wanted_categories:
                matched.append(item)
            else:
                fallback.append(item)

        picked = matched[:limit]
        if len(picked) < limit:
            picked.extend(fallback[: max(0, limit - len(picked))])
        return picked[:limit]

    def _should_offer_shared_activity_invite(self, scene: str, custom_prompt: str = "") -> bool:
        leisure_scenes = {"视频", "阅读", "游戏", "音乐", "社交", "浏览", "浏览-娱乐"}
        if custom_prompt:
            return False
        if scene not in leisure_scenes and not self.long_term_memory.get("shared_activities"):
            return False

        now_ts = time.time()
        if now_ts - float(getattr(self, "last_shared_activity_invite_time", 0.0) or 0.0) < 7200:
            return False

        self.last_shared_activity_invite_time = now_ts
        return True

    def _extract_shared_activity_from_message(self, message_text: str) -> tuple[str, str] | tuple[None, None]:
        import re

        text = str(message_text or "").strip()
        if not text or text.startswith("/"):
            return None, None

        escaped_bot_name = re.escape(str(getattr(self, "bot_name", "") or "").strip())
        together_patterns = [
            r"和你",
            r"跟你",
            r"我们一起",
            r"咱们一起",
            r"你刚刚陪我",
            r"你刚刚帮我",
            r"你陪我",
            r"你帮我",
        ]
        if escaped_bot_name:
            together_patterns.extend(
                [
                    rf"和{escaped_bot_name}",
                    rf"跟{escaped_bot_name}",
                    rf"{escaped_bot_name}陪我",
                    rf"{escaped_bot_name}帮我",
                ]
            )

        if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in together_patterns):
            return None, None

        future_only_markers = (
            "想和你一起",
            "想跟你一起",
            "要不要一起",
            "一起吗",
            "改天一起",
            "下次一起",
            "等会一起",
            "待会一起",
        )
        past_markers = ("刚", "刚刚", "已经", "过", "了", "完", "通关")
        if any(marker in text for marker in future_only_markers) and not any(
            marker in text for marker in past_markers
        ):
            return None, None

        title_match = re.search(r"《[^》]{1,30}》", text)
        title = title_match.group(0) if title_match else ""

        watch_ready = re.search(r"(看|追|补|刷).{0,12}(过|了|完|完了)", text)
        game_ready = re.search(r"(玩|打|开黑|跑团|通关).{0,12}(过|了|完|通关)", text)
        test_ready = re.search(r"(做|测|试).{0,12}(过|了|完)", text)
        screen_ready = re.search(
            r"(看|分析|研究|判断|排查).{0,12}(过|了|完)",
            text,
        )

        watch_keywords = ("电影", "动漫", "番", "动画", "剧", "视频", "纪录片", "直播")
        if watch_ready and (title or any(keyword in text for keyword in watch_keywords)):
            if title:
                return "watch_media", f"一起看{title}"
            media_summary_map = {
                "电影": "一起看电影",
                "动漫": "一起看动漫",
                "番": "一起看动漫",
                "动画": "一起看动漫",
                "剧": "一起追剧",
                "纪录片": "一起看纪录片",
                "直播": "一起看直播",
                "视频": "一起看视频",
            }
            for keyword, summary in media_summary_map.items():
                if keyword in text:
                    return "watch_media", summary

        game_keywords = ("游戏", "开黑", "这局", "这一局")
        if game_ready and (title or any(keyword in text for keyword in game_keywords)):
            if title:
                return "game", f"一起玩{title}"
            if "开黑" in text:
                return "game", "一起开黑"
            if "这局" in text or "这一局" in text:
                return "game", "一起打这局游戏"
            return "game", "一起玩游戏"

        topic_match = re.search(r"([\u4e00-\u9fffA-Za-z0-9]{2,24}测试)", text)
        if test_ready and any(keyword in text for keyword in ("测试", "测评", "题", "问卷", "人格")):
            if topic_match:
                return "test", f"一起做{topic_match.group(1)}"
            if "人格" in text:
                return "test", "一起做人格测试"
            return "test", "一起做测试"

        screen_keywords = {
            "这题": "一起看这道题",
            "这道题": "一起看这道题",
            "这个页面": "一起看这个页面",
            "这个界面": "一起看这个界面",
            "这个截图": "一起看这个截图",
            "这张图": "一起看这张图",
            "这局": "一起看这局",
            "这一局": "一起看这局",
            "这个弹窗": "一起看这个弹窗",
        }
        if screen_ready:
            for keyword, summary in screen_keywords.items():
                if keyword in text:
                    return "screen_interaction", summary

        return None, None

    def _remember_shared_activity(self, category: str, summary: str, source_text: str = "") -> bool:
        import datetime

        normalized_summary = self._normalize_shared_activity_summary(summary)
        if not normalized_summary:
            return False

        self._ensure_long_term_memory_defaults()
        today = datetime.date.today().isoformat()
        activity_memory = self.long_term_memory["shared_activities"].setdefault(
            normalized_summary,
            {
                "category": str(category or "other"),
                "count": 0,
                "last_shared": today,
                "priority": 0,
            },
        )
        activity_memory["category"] = str(category or activity_memory.get("category", "other") or "other")
        activity_memory["count"] = int(activity_memory.get("count", 0) or 0) + 1
        activity_memory["last_shared"] = today
        if source_text:
            activity_memory["example"] = str(source_text).strip()[:120]

        self._update_memory_priorities()
        self._save_long_term_memory()
        logger.info(f"已记录共同经历: {normalized_summary}")
        return True

    def _learn_shared_activity_from_message(self, message_text: str) -> bool:
        category, summary = self._extract_shared_activity_from_message(message_text)
        if not category or not summary:
            return False
        return self._remember_shared_activity(category, summary, source_text=message_text)

    @staticmethod
    def _contains_shared_activity_completion_marker(category: str, message_text: str) -> bool:
        text = str(message_text or "").strip()
        completion_markers_map = {
            "watch_media": (
                "看完了",
                "刚看完",
                "看完",
                "追完了",
                "追完",
                "补完了",
                "补完",
                "刷完了",
                "刷完",
            ),
            "game": (
                "打完了",
                "刚打完",
                "打完",
                "玩完了",
                "玩完",
                "通关了",
                "刚通关",
                "通关",
                "这局打完了",
                "这一局打完了",
            ),
            "test": (
                "做完了",
                "刚做完",
                "做完",
                "测完了",
                "刚测完",
                "测完",
                "答完了",
                "答完",
            ),
        }
        return any(
            marker in text
            for marker in completion_markers_map.get(str(category or "").strip(), ())
        )

    @staticmethod
    def _contains_preference_expression(message_text: str) -> bool:
        text = str(message_text or "").strip()
        markers = (
            "喜欢",
            "最喜欢",
            "不喜欢",
            "印象最深",
            "最戳",
            "最爱",
            "最无聊",
            "最好看",
            "最有感觉",
            "最有意思",
        )
        return any(marker in text for marker in markers)

    def _extract_shared_activity_topic_tokens(
        self,
        summary: str,
        source_text: str = "",
    ) -> list[str]:
        import re

        summary = self._normalize_shared_activity_summary(summary)
        source_text = str(source_text or "").strip()
        tokens: list[str] = []

        title_match = re.search(r"《([^》]{1,30})》", f"{summary} {source_text}")
        if title_match:
            tokens.append(title_match.group(1))

        subject = summary
        if subject.startswith("一起看"):
            subject = subject[3:]
        elif subject.startswith("一起追"):
            subject = subject[3:]
        elif subject.startswith("一起"):
            subject = subject[2:]
        subject = subject.strip("《》 ")
        if subject and subject not in {"电影", "动漫", "纪录片", "直播", "视频", "剧"}:
            tokens.append(subject)

        deduped: list[str] = []
        seen = set()
        for token in tokens:
            normalized = self._normalize_record_text(token)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(token)
        return deduped[:3]

    @staticmethod
    def _looks_like_shared_activity_followup_reply(
        message_text: str,
        *,
        category: str = "",
        topic_tokens: list[str] | None = None,
    ) -> bool:
        text = " ".join(str(message_text or "").split())
        if not text:
            return False

        strong_markers = (
            "我喜欢",
            "我最喜欢",
            "最喜欢",
            "不喜欢",
            "印象最深",
            "最戳",
            "最爱",
            "最好看",
            "最有感觉",
            "最有意思",
        )
        if any(marker in text for marker in strong_markers):
            return True

        content_markers_map = {
            "watch_media": (
                "角色",
                "人物",
                "主角",
                "反派",
                "结尾",
                "结局",
                "反转",
                "配乐",
                "镜头",
                "台词",
                "节奏",
                "氛围",
                "设定",
                "演技",
                "后半段",
                "前半段",
                "中间那段",
                "那一段",
                "这一段",
                "那个角色",
                "这角色",
            ),
            "game": (
                "角色",
                "英雄",
                "阵容",
                "操作",
                "团战",
                "节奏",
                "对线",
                "配合",
                "翻盘",
                "压制",
                "上头",
                "手感",
                "这一局",
                "那波",
            ),
            "test": (
                "结果",
                "题",
                "题目",
                "答案",
                "选项",
                "结论",
                "分析",
                "描述",
                "准",
                "离谱",
                "像我",
                "不像我",
            ),
        }
        content_markers = content_markers_map.get(
            str(category or "").strip(),
            content_markers_map["watch_media"],
        )
        answer_starters = (
            "我觉得",
            "感觉",
            "应该是",
            "大概是",
            "可能是",
            "比较喜欢",
            "更喜欢",
        )
        if any(marker in text for marker in content_markers) and any(
            marker in text for marker in answer_starters
        ):
            return True

        for token in topic_tokens or []:
            token = str(token or "").strip()
            if token and token in text and any(marker in text for marker in content_markers):
                return True
        return False

    def _build_shared_activity_followup_question(self, category: str, summary: str) -> str:
        summary = str(summary or "").strip()
        if not summary:
            return ""
        subject = summary[2:] if summary.startswith("一起") else summary
        if len(subject) > 24:
            subject = subject[:24]
        category = str(category or "").strip()
        if category == "game":
            return f"{subject}之后，你最喜欢刚才哪一波操作、哪个角色，或者哪里最上头？"
        if category == "test":
            return f"{subject}之后，你觉得哪个结果、哪一题，或者哪句描述最戳你？"
        return f"{subject}之后，你最喜欢里面哪一段、哪个角色，或者哪种感觉？"

    def _get_shared_activity_followup_state(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        sent_state = getattr(self, "_shared_activity_followup_sent", None)
        if not isinstance(sent_state, dict):
            sent_state = {}
            self._shared_activity_followup_sent = sent_state

        pending_state = getattr(self, "_shared_activity_followup_pending", None)
        if not isinstance(pending_state, dict):
            pending_state = {}
            self._shared_activity_followup_pending = pending_state

        return sent_state, pending_state

    def _mark_shared_activity_followup_missed(self, target: str) -> None:
        target = str(target or "").strip()
        if not target:
            return

        sent_state, _ = self._get_shared_activity_followup_state()
        state = sent_state.get(target, {}) or {}
        state["miss_count"] = int(state.get("miss_count", 0) or 0) + 1
        state["last_missed_at"] = time.time()
        sent_state[target] = state

    def _mark_shared_activity_followup_answered(self, target: str) -> None:
        target = str(target or "").strip()
        if not target:
            return

        sent_state, _ = self._get_shared_activity_followup_state()
        state = sent_state.get(target, {}) or {}
        state["miss_count"] = 0
        state["last_answered_at"] = time.time()
        sent_state[target] = state

    def _should_send_shared_activity_followup(self, target: str, summary: str) -> bool:
        target = str(target or "").strip()
        summary = self._normalize_shared_activity_summary(summary)
        if not target or not summary:
            return False

        sent_state, _ = self._get_shared_activity_followup_state()
        now_ts = time.time()
        state = sent_state.get(target, {}) or {}
        last_summary = self._normalize_shared_activity_summary(state.get("summary", ""))
        last_sent_at = float(state.get("timestamp", 0.0) or 0.0)
        miss_count = int(state.get("miss_count", 0) or 0)

        if last_summary and last_summary == summary and (now_ts - last_sent_at) < 12 * 3600:
            return False
        min_interval_seconds = 2 * 3600
        if miss_count >= 2:
            min_interval_seconds = 48 * 3600
        elif miss_count == 1:
            min_interval_seconds = 6 * 3600
        if last_sent_at > 0 and (now_ts - last_sent_at) < min_interval_seconds:
            return False
        return True

    @staticmethod
    def _should_probabilistically_follow_up_shared_activity(category: str) -> bool:
        category = str(category or "").strip()
        if category == "watch_media":
            return True

        trigger_probabilities = {
            "game": 0.18,
            "test": 0.12,
        }
        probability = float(trigger_probabilities.get(category, 0.0) or 0.0)
        if probability <= 0:
            return False
        return random.random() < probability

    def _remember_shared_activity_followup_sent(
        self,
        target: str,
        category: str,
        summary: str,
        *,
        source_text: str = "",
    ) -> None:
        target = str(target or "").strip()
        summary = self._normalize_shared_activity_summary(summary)
        if not target or not summary:
            return

        sent_state, pending_state = self._get_shared_activity_followup_state()
        now_ts = time.time()
        topic_tokens = self._extract_shared_activity_topic_tokens(summary, source_text)
        previous_state = sent_state.get(target, {}) or {}
        sent_state[target] = {
            "summary": summary,
            "timestamp": now_ts,
            "miss_count": int(previous_state.get("miss_count", 0) or 0),
            "last_missed_at": float(previous_state.get("last_missed_at", 0.0) or 0.0),
            "last_answered_at": float(previous_state.get("last_answered_at", 0.0) or 0.0),
        }
        pending_state[target] = {
            "category": str(category or "other"),
            "summary": summary,
            "asked_at": now_ts,
            "topic_tokens": topic_tokens,
            "unrelated_count": 0,
        }

        if len(sent_state) > 100:
            sorted_items = sorted(
                sent_state.items(),
                key=lambda item: float((item[1] or {}).get("timestamp", 0.0) or 0.0),
                reverse=True,
            )
            self._shared_activity_followup_sent = dict(sorted_items[:100])
        if len(pending_state) > 100:
            sorted_items = sorted(
                pending_state.items(),
                key=lambda item: float((item[1] or {}).get("asked_at", 0.0) or 0.0),
                reverse=True,
            )
            self._shared_activity_followup_pending = dict(sorted_items[:100])

    def _extract_shared_activity_preference_memory(
        self,
        category: str,
        summary: str,
        message_text: str,
    ) -> str:
        summary = self._normalize_shared_activity_summary(summary)
        text = " ".join(str(message_text or "").split())
        if not summary or not text:
            return ""

        if len(text) > 80:
            text = text[:80].rstrip("，,；;。.!！?？ ") + "..."
        subject = summary[2:] if summary.startswith("一起") else summary
        if not self._contains_preference_expression(text) and len(text) < 6:
            return ""
        category_labels = {
            "watch_media": "一起看内容",
            "game": "一起玩游戏",
            "test": "一起做测试",
        }
        activity_label = category_labels.get(str(category or "").strip(), "这次共同体验")
        return f"{activity_label} {subject}时提到：{text}"

    def _learn_shared_activity_preference_from_reply(
        self,
        category: str,
        summary: str,
        message_text: str,
    ) -> bool:
        preference_text = self._extract_shared_activity_preference_memory(
            category,
            summary,
            message_text,
        )
        if not preference_text:
            return False
        preference_category_map = {
            "watch_media": "movies",
            "game": "hobbies",
            "test": "other",
        }
        self._add_user_preference(
            preference_category_map.get(str(category or "").strip(), "other"),
            preference_text,
        )
        return True

    def _consume_pending_shared_activity_followup(self, event: AstrMessageEvent, message_text: str) -> bool:
        target = str(getattr(event, "unified_msg_origin", "") or "").strip()
        text = str(message_text or "").strip()
        if not target or not text or text.startswith("/"):
            return False

        if not self._get_runtime_flag("enable_learning", True):
            _, pending_state = self._get_shared_activity_followup_state()
            pending_state.pop(target, None)
            self._remember_learning_runtime_event(
                "preference",
                "skipped",
                "总学习开关已关闭",
            )
            return False
        if not self._get_runtime_flag("enable_shared_activity_preference_learning", True):
            _, pending_state = self._get_shared_activity_followup_state()
            pending_state.pop(target, None)
            self._remember_learning_runtime_event(
                "preference",
                "skipped",
                "共同体验偏好学习已关闭",
            )
            return False

        _, pending_state = self._get_shared_activity_followup_state()
        pending = pending_state.get(target, {}) or {}
        if not pending:
            return False

        asked_at = float(pending.get("asked_at", 0.0) or 0.0)
        if asked_at <= 0 or (time.time() - asked_at) > 30 * 60:
            pending_state.pop(target, None)
            self._mark_shared_activity_followup_missed(target)
            self._remember_learning_runtime_event(
                "preference",
                "skipped",
                "共同体验追问已过期，未等到回答",
            )
            return False

        if self._extract_shared_activity_from_message(text)[0]:
            pending_state.pop(target, None)
            self._mark_shared_activity_followup_missed(target)
            self._remember_learning_runtime_event(
                "preference",
                "skipped",
                "用户已经切到新的共同体验话题",
            )
            return False

        category = str(pending.get("category", "") or "").strip()
        topic_tokens = pending.get("topic_tokens", []) or []
        if not self._looks_like_shared_activity_followup_reply(
            text,
            category=category,
            topic_tokens=topic_tokens if isinstance(topic_tokens, list) else [],
        ):
            pending["unrelated_count"] = int(pending.get("unrelated_count", 0) or 0) + 1
            pending_state[target] = pending
            if int(pending["unrelated_count"]) >= 2:
                pending_state.pop(target, None)
                self._mark_shared_activity_followup_missed(target)
                self._remember_learning_runtime_event(
                    "preference",
                    "skipped",
                    "用户连续两次没有接共同体验话题",
                )
            return False

        summary = str(pending.get("summary", "") or "").strip()
        learned = self._learn_shared_activity_preference_from_reply(
            category,
            summary,
            text,
        )
        if learned:
            pending_state.pop(target, None)
            self._mark_shared_activity_followup_answered(target)
            self._remember_learning_runtime_event(
                "preference",
                "learned",
                f"已从共同体验回答中学习：{summary}",
            )
        return learned

    async def _maybe_follow_up_shared_activity(
        self,
        event: AstrMessageEvent,
        message_text: str,
    ) -> bool:
        if not self._get_runtime_flag("enable_learning", True):
            self._remember_learning_runtime_event(
                "followup",
                "skipped",
                "总学习开关已关闭",
            )
            return False

        target = str(getattr(event, "unified_msg_origin", "") or "").strip()
        text = str(message_text or "").strip()
        if not target or not text or text.startswith("/"):
            return False

        category, summary = self._extract_shared_activity_from_message(text)
        if category not in {"watch_media", "game", "test"} or not summary:
            return False
        if not self._contains_shared_activity_completion_marker(category, text):
            return False

        if self._contains_preference_expression(text):
            if not self._get_runtime_flag("enable_shared_activity_preference_learning", True):
                self._remember_learning_runtime_event(
                    "preference",
                    "skipped",
                    "共同体验偏好学习已关闭",
                )
                return False
            learned = self._learn_shared_activity_preference_from_reply(
                category,
                summary,
                text,
            )
            if learned:
                self._mark_shared_activity_followup_answered(target)
                self._remember_learning_runtime_event(
                    "preference",
                    "learned",
                    f"用户已直接表达偏好：{summary}",
                )
            return learned

        if not self._should_send_shared_activity_followup(target, summary):
            self._remember_learning_runtime_event(
                "followup",
                "skipped",
                "共同体验追问仍在冷却中",
            )
            return False
        if not self._get_runtime_flag("enable_shared_activity_followup", True):
            self._remember_learning_runtime_event(
                "followup",
                "skipped",
                "共同体验追问已关闭",
            )
            return False
        if not self._should_probabilistically_follow_up_shared_activity(category):
            self._remember_learning_runtime_event(
                "followup",
                "skipped",
                "这次命中了低打扰概率，不主动追问",
            )
            return False

        question = self._build_shared_activity_followup_question(category, summary)
        if not question:
            return False

        sent = await self._send_plain_message(target, question)
        if sent:
            self._remember_shared_activity_followup_sent(
                target,
                category,
                summary,
                source_text=text,
            )
            self._remember_learning_runtime_event(
                "followup",
                "asked",
                f"已发出共同体验追问：{summary}",
            )
        return sent

    def _update_activity(self, scene, active_window, *, source: str = "screen_analysis"):
        """更新活动状态，记录工作/摸鱼时间。"""
        import time
        current_time = time.time()

        # 定义工作和摸鱼场景
        work_scenes = ["编程", "设计", "办公", "邮件", "浏览-工作"]
        play_scenes = ["游戏", "视频", "音乐", "社交", "浏览-娱乐"]

        # 确定当前活动类型
        activity_type = "其他"
        if scene in work_scenes:
            activity_type = "工作"
        elif scene in play_scenes:
            activity_type = "摸鱼"

        normalized_scene = self._normalize_scene_label(scene or "")
        normalized_window = self._normalize_window_title(active_window or "")
        activity_source = str(source or "screen_analysis").strip() or "screen_analysis"
        activity_meta = self._build_activity_record_meta(
            activity_type=activity_type,
            scene=normalized_scene,
            window=normalized_window,
        )
        activity_meta["capture_source"] = activity_source

        # 创建活动标识
        activity = f"{activity_type}:{normalized_scene}:{normalized_window}"

        # 如果活动发生变化，记录上一个活动的时间
        if self.current_activity != activity:
            if self.current_activity and self.activity_start_time:
                self._append_activity_record(
                    activity=self.current_activity,
                    start_time=self.activity_start_time,
                    end_time=current_time,
                    activity_meta=getattr(self, "current_activity_meta", None),
                )

            # 更新当前活动
            self.current_activity = activity
            self.current_activity_meta = activity_meta
            self.current_activity_source = activity_source
            self.activity_start_time = current_time
        elif (
            isinstance(getattr(self, "current_activity_meta", None), dict)
            and str(getattr(self, "current_activity_source", "") or "").strip()
            != activity_source
        ):
            self.current_activity_meta = activity_meta
            self.current_activity_source = activity_source

        return activity_type

    def _load_activity_history(self) -> None:
        try:
            activity_history_file = getattr(self, "activity_history_file", "")
            if not activity_history_file:
                activity_history_file = os.path.join(self.learning_storage, "activity_history.json")
                self.activity_history_file = activity_history_file
            if not os.path.exists(activity_history_file):
                self.activity_history = []
                return
            with open(activity_history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            normalized_history: list[dict[str, Any]] = []
            for item in data if isinstance(data, list) else []:
                normalized = self._normalize_activity_record(item)
                if normalized is not None:
                    normalized_history.append(normalized)
            self.activity_history = normalized_history
        except Exception as e:
            logger.error(f"加载活动历史失败: {e}")
            self.activity_history = []

    def _save_activity_history(self) -> None:
        try:
            activity_history_file = getattr(self, "activity_history_file", "")
            if not activity_history_file:
                activity_history_file = os.path.join(self.learning_storage, "activity_history.json")
                self.activity_history_file = activity_history_file
            with open(activity_history_file, "w", encoding="utf-8") as f:
                json.dump(self.activity_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存活动历史失败: {e}")

    def _load_rest_reminder_state(self) -> None:
        self.last_rest_reminder_day = ""
        self.last_rest_reminder_time = None
        try:
            state_file = str(getattr(self, "rest_reminder_state_file", "") or "").strip()
            if not state_file or not os.path.exists(state_file):
                return
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            self.last_rest_reminder_day = str(
                data.get("last_rest_reminder_day", "") or ""
            ).strip()
            last_sent_at = str(data.get("last_rest_reminder_at", "") or "").strip()
            if last_sent_at:
                try:
                    self.last_rest_reminder_time = datetime.datetime.fromisoformat(
                        last_sent_at
                    )
                except Exception:
                    self.last_rest_reminder_time = None
        except Exception as e:
            logger.error(f"加载休息提醒状态失败: {e}")
            self.last_rest_reminder_day = ""
            self.last_rest_reminder_time = None

    def _save_rest_reminder_state(self) -> None:
        try:
            state_file = str(getattr(self, "rest_reminder_state_file", "") or "").strip()
            if not state_file:
                state_file = os.path.join(
                    self.learning_storage,
                    "rest_reminder_state.json",
                )
                self.rest_reminder_state_file = state_file
            payload = {
                "last_rest_reminder_day": str(
                    getattr(self, "last_rest_reminder_day", "") or ""
                ).strip(),
                "last_rest_reminder_at": (
                    getattr(self, "last_rest_reminder_time", None).isoformat()
                    if isinstance(
                        getattr(self, "last_rest_reminder_time", None),
                        datetime.datetime,
                    )
                    else ""
                ),
            }
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存休息提醒状态失败: {e}")

    def _get_rest_day_bucket(self, dt: datetime.datetime | None = None) -> datetime.date:
        dt = dt or datetime.datetime.now()
        if dt.hour < self.REST_REMINDER_CUTOFF_HOUR:
            return dt.date() - datetime.timedelta(days=1)
        return dt.date()

    def _to_extended_rest_minutes(self, value: datetime.datetime | datetime.time | str) -> int | None:
        if isinstance(value, datetime.datetime):
            hour = int(value.hour)
            minute = int(value.minute)
        elif isinstance(value, datetime.time):
            hour = int(value.hour)
            minute = int(value.minute)
        else:
            parsed_minutes = self._parse_clock_to_minutes(str(value or "").strip())
            if parsed_minutes is None:
                return None
            hour, minute = divmod(parsed_minutes, 60)
        total = hour * 60 + minute
        if total < self.REST_REMINDER_CUTOFF_HOUR * 60:
            total += 24 * 60
        return total

    def _format_extended_rest_minutes(self, minutes_value: int | float | None) -> str:
        if minutes_value is None:
            return ""
        total = int(round(float(minutes_value or 0)))
        total %= 24 * 60
        hour, minute = divmod(total, 60)
        return f"{hour:02d}:{minute:02d}"

    def _get_configured_rest_range(self) -> tuple[int, int] | None:
        time_range = str(getattr(self, "rest_time_range", "") or "").strip()
        if not time_range or "-" not in time_range:
            return None
        try:
            start_text, end_text = time_range.split("-", 1)
            start_minutes = self._parse_clock_to_minutes(start_text)
            end_minutes = self._parse_clock_to_minutes(end_text)
            if start_minutes is None or end_minutes is None:
                return None
            return start_minutes, end_minutes
        except Exception:
            return None

    def _collect_recent_rest_activity_samples(
        self,
        *,
        lookback_days: int | None = None,
        now: datetime.datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = now or datetime.datetime.now()
        current_bucket = self._get_rest_day_bucket(now)
        lookback = max(1, int(lookback_days or self.REST_INFERENCE_LOOKBACK_DAYS))
        earliest_bucket = current_bucket - datetime.timedelta(days=lookback)
        nightly_start_minutes = self.REST_ACTIVITY_WINDOW_START_HOUR * 60
        nightly_end_minutes = (24 + self.REST_REMINDER_CUTOFF_HOUR) * 60

        daily_samples: dict[str, dict[str, Any]] = {}
        for item in self._get_activity_history_for_stats():
            if not isinstance(item, dict):
                continue
            for field_name in ("start_time", "end_time"):
                ts = float(item.get(field_name, 0) or 0)
                if ts <= 0:
                    continue
                dt = datetime.datetime.fromtimestamp(ts)
                bucket_day = self._get_rest_day_bucket(dt)
                if bucket_day >= current_bucket or bucket_day < earliest_bucket:
                    continue
                extended_minutes = self._to_extended_rest_minutes(dt)
                if extended_minutes is None:
                    continue
                if (
                    extended_minutes < nightly_start_minutes
                    or extended_minutes > nightly_end_minutes
                ):
                    continue
                key = bucket_day.isoformat()
                previous = daily_samples.get(key)
                if previous is None or ts > float(previous.get("timestamp", 0) or 0):
                    daily_samples[key] = {
                        "day": key,
                        "timestamp": ts,
                        "extended_minutes": extended_minutes,
                        "window": self._normalize_window_title(item.get("window", "") or ""),
                        "scene": self._normalize_scene_label(item.get("scene", "") or ""),
                    }

        return [
            daily_samples[key]
            for key in sorted(daily_samples.keys())
        ]

    def _infer_rest_behavior(self, now: datetime.datetime | None = None) -> dict[str, Any]:
        now = now or datetime.datetime.now()
        current_bucket = self._get_rest_day_bucket(now)
        samples = self._collect_recent_rest_activity_samples(now=now)
        info: dict[str, Any] = {
            "available": False,
            "source": "none",
            "rest_extended_minutes": None,
            "rest_clock": "",
            "reminder_extended_minutes": None,
            "reminder_clock": "",
            "sample_count": len(samples),
            "rest_bucket_day": current_bucket.isoformat(),
        }

        if len(samples) >= self.REST_INFERENCE_MIN_SAMPLES:
            import statistics

            recent_samples = samples[-self.REST_INFERENCE_LOOKBACK_DAYS :]
            inferred_rest_minutes = int(
                round(
                    statistics.median(
                        sample.get("extended_minutes", 0) for sample in recent_samples
                    )
                )
            )
            inferred_rest_minutes = max(
                self.REST_ACTIVITY_WINDOW_START_HOUR * 60,
                min(
                    inferred_rest_minutes,
                    (24 + self.REST_REMINDER_CUTOFF_HOUR) * 60,
                ),
            )
            reminder_minutes = max(
                self.REST_ACTIVITY_WINDOW_START_HOUR * 60,
                inferred_rest_minutes - self.REST_REMINDER_ADVANCE_MINUTES,
            )
            info.update(
                {
                    "available": True,
                    "source": "activity_history",
                    "samples": recent_samples,
                    "rest_extended_minutes": inferred_rest_minutes,
                    "rest_clock": self._format_extended_rest_minutes(
                        inferred_rest_minutes
                    ),
                    "reminder_extended_minutes": reminder_minutes,
                    "reminder_clock": self._format_extended_rest_minutes(
                        reminder_minutes
                    ),
                }
            )
            return info

        configured_range = self._get_configured_rest_range()
        if configured_range is None:
            return info

        start_minutes, _ = configured_range
        reminder_minutes = max(
            0,
            start_minutes - self.REST_REMINDER_ADVANCE_MINUTES,
        )
        info.update(
            {
                "available": True,
                "source": "configured_rest_range",
                "rest_extended_minutes": self._to_extended_rest_minutes(
                    datetime.time(start_minutes // 60, start_minutes % 60)
                ),
                "rest_clock": self._format_extended_rest_minutes(start_minutes),
                "reminder_extended_minutes": self._to_extended_rest_minutes(
                    datetime.time(reminder_minutes // 60, reminder_minutes % 60)
                ),
                "reminder_clock": self._format_extended_rest_minutes(reminder_minutes),
            }
        )
        return info

    def _should_send_rest_reminder(self, now: datetime.datetime | None = None) -> tuple[bool, dict[str, Any]]:
        now = now or datetime.datetime.now()
        info = self._infer_rest_behavior(now=now)
        if not info.get("available"):
            return False, info

        current_bucket = self._get_rest_day_bucket(now).isoformat()
        info["rest_bucket_day"] = current_bucket
        if str(getattr(self, "last_rest_reminder_day", "") or "").strip() == current_bucket:
            return False, info

        reminder_minutes = info.get("reminder_extended_minutes")
        rest_minutes = info.get("rest_extended_minutes")
        now_minutes = self._to_extended_rest_minutes(now)
        if reminder_minutes is None or rest_minutes is None or now_minutes is None:
            return False, info
        if now_minutes < reminder_minutes:
            return False, info
        if now_minutes > rest_minutes + self.REST_REMINDER_LATEST_AFTER_MINUTES:
            return False, info
        return True, info

    def _remember_inferred_rest_memory(self, info: dict[str, Any]) -> bool:
        if not isinstance(info, dict) or not info.get("available"):
            return False

        rest_clock = str(info.get("rest_clock", "") or "").strip()
        reminder_clock = str(info.get("reminder_clock", "") or "").strip()
        source = str(info.get("source", "") or "").strip()
        sample_count = int(info.get("sample_count", 0) or 0)
        summary = (
            f"用户最近的休息时间大约在 {rest_clock}，"
            f"提醒休息更适合放在 {reminder_clock} 左右。"
        )
        if source == "activity_history" and sample_count > 0:
            summary += f" 这是根据最近 {sample_count} 天最后一次窗口活动推测出来的。"
            latest_sample = (info.get("samples", []) or [])[-1] if isinstance(info.get("samples", []), list) else {}
            latest_window = self._normalize_window_title(latest_sample.get("window", "") or "")
            if latest_window:
                summary += f" 最近一次夜间收尾窗口是《{latest_window}》。"
        elif source == "configured_rest_range":
            summary += " 当前样本不足，先使用配置的休息时间作为兜底。"

        remembered = self._remember_episodic_memory(
            scene="休息",
            active_window="作息规律",
            summary=summary,
            response_preview=summary,
            kind="rest_pattern",
        )
        if remembered:
            self._save_long_term_memory()
        return remembered

    def _mark_rest_reminder_sent(self, info: dict[str, Any] | None = None) -> None:
        now = datetime.datetime.now()
        self.last_rest_reminder_time = now
        self.last_rest_reminder_day = self._get_rest_day_bucket(now).isoformat()
        self._save_rest_reminder_state()
        if isinstance(info, dict):
            self._remember_inferred_rest_memory(info)

    def _close_current_activity(
        self,
        *,
        end_time: float | None = None,
        min_duration_seconds: int | None = None,
        only_source: str = "",
    ) -> bool:
        current_activity = str(getattr(self, "current_activity", "") or "").strip()
        activity_start_time = float(getattr(self, "activity_start_time", 0) or 0)
        current_source = str(getattr(self, "current_activity_source", "") or "").strip()
        required_source = str(only_source or "").strip()
        if required_source and current_source != required_source:
            return False
        if not current_activity or activity_start_time <= 0:
            return False

        closed = self._append_activity_record(
            activity=current_activity,
            start_time=activity_start_time,
            end_time=float(end_time or time.time()),
            min_duration_seconds=min_duration_seconds,
            activity_meta=getattr(self, "current_activity_meta", None),
        )
        self.current_activity = None
        self.current_activity_meta = None
        self.current_activity_source = ""
        self.activity_start_time = None
        return closed

    def _is_background_activity_tracking_effective(self) -> bool:
        if not bool(getattr(self, "running", False)):
            return False
        if not bool(getattr(self, "enabled", False)):
            return False
        if not bool(getattr(self, "enable_background_activity_tracking", False)):
            return False
        if bool(getattr(self, "is_running", False)):
            return False
        is_window_companion_active = getattr(
            self,
            "_is_window_companion_session_active",
            None,
        )
        if callable(is_window_companion_active) and is_window_companion_active():
            return False
        return True

    def _get_background_activity_tracking_runtime_status(self) -> dict[str, Any]:
        interval = max(
            5,
            int(getattr(self, "background_activity_tracking_interval", 15) or 15),
        )
        return {
            "enabled": bool(getattr(self, "enable_background_activity_tracking", False)),
            "active": self._is_background_activity_tracking_effective(),
            "interval": interval,
        }

    def _infer_background_activity_scene(self, window_title: str) -> str:
        normalized_window = self._normalize_window_title(window_title or "")
        if not normalized_window:
            return ""

        app_name = self._detect_activity_app_name(normalized_window)
        site_info = self._extract_activity_site_info(
            scene="浏览",
            window=normalized_window,
            app_name=app_name,
        )
        site_label = str(site_info.get("site_label", "") or "").strip()
        inferred_scene = self._normalize_scene_label(self._identify_scene(normalized_window))

        if site_label in self.BACKGROUND_ACTIVITY_MAIL_SITES:
            return "邮件"
        if site_label in self.BACKGROUND_ACTIVITY_SOCIAL_SITES:
            return "社交"
        if site_label in self.BACKGROUND_ACTIVITY_WORK_SITES:
            return "浏览-工作"
        if site_label in self.BACKGROUND_ACTIVITY_ENTERTAINMENT_SITES:
            return "浏览-娱乐"

        app_scene = self.BACKGROUND_ACTIVITY_APP_SCENES.get(app_name, "")
        if app_scene:
            return app_scene

        if inferred_scene and inferred_scene != "未知":
            if inferred_scene == "浏览" and site_label:
                return "浏览"
            return inferred_scene

        if site_label or self._is_activity_browser_app(app_name):
            return "浏览"

        return "其他"

    async def _background_activity_tracking_task(self) -> None:
        empty_title_streak = 0
        while self.running and self._is_current_process_instance():
            interval = max(
                5,
                int(getattr(self, "background_activity_tracking_interval", 15) or 15),
            )
            if not self._is_background_activity_tracking_effective():
                empty_title_streak = 0
                self._close_current_activity(
                    min_duration_seconds=self.LIVE_ACTIVITY_MIN_DURATION_SECONDS,
                    only_source="background_tracker",
                )
                await asyncio.sleep(min(interval, 5))
                continue

            try:
                active_window_title, _ = await asyncio.to_thread(
                    self._get_active_window_info
                )
            except Exception as e:
                logger.debug(f"独立活动轨迹采样失败: {e}")
                await asyncio.sleep(interval)
                continue

            normalized_window = self._normalize_window_title(active_window_title or "")
            if not normalized_window:
                empty_title_streak += 1
                if empty_title_streak >= 2:
                    self._close_current_activity(
                        min_duration_seconds=self.LIVE_ACTIVITY_MIN_DURATION_SECONDS,
                        only_source="background_tracker",
                    )
                await asyncio.sleep(interval)
                continue

            empty_title_streak = 0
            scene = self._infer_background_activity_scene(normalized_window) or "其他"
            self._update_activity(
                scene,
                normalized_window,
                source="background_tracker",
            )
            await asyncio.sleep(interval)

    def _parse_activity_marker(self, activity: str) -> tuple[str, str, str]:
        parts = str(activity or "").split(":", 2)
        activity_type = parts[0] if len(parts) > 0 else "其他"
        scene = parts[1] if len(parts) > 1 else ""
        window = parts[2] if len(parts) > 2 else ""
        return activity_type, scene, window

    @staticmethod
    def _split_activity_window_parts(window_title: str) -> list[str]:
        parts = [str(window_title or "").strip()]
        separators = (" - ", " | ", " — ", " – ", " · ", " • ", " :: ")
        for separator in separators:
            next_parts: list[str] = []
            for part in parts:
                next_parts.extend(str(part).split(separator))
            parts = next_parts
        return [str(part).strip() for part in parts if str(part).strip()]

    def _detect_activity_app_name(self, window_title: str) -> str:
        normalized_window = self._normalize_window_title(window_title or "")
        if not normalized_window:
            return ""
        custom_app_name = self._match_custom_activity_app_name(normalized_window)
        if custom_app_name:
            return custom_app_name
        detected_app_name = extract_app_name(normalized_window)
        if detected_app_name:
            return self._normalize_window_title(detected_app_name)[:48]
        lowered = f" {normalized_window.casefold()} "
        for label, aliases in self.ACTIVITY_APP_ALIASES:
            if any(alias.casefold() in lowered for alias in aliases):
                return label
        parts = self._split_activity_window_parts(normalized_window)
        if len(parts) >= 2:
            return self._normalize_window_title(parts[-1])[:48]
        return normalized_window[:48]

    def _is_activity_browser_app(self, app_name: str) -> bool:
        normalized_app = str(app_name or "").strip()
        if not normalized_app:
            return False
        return any(label == normalized_app for label, _ in self.ACTIVITY_BROWSER_APP_ALIASES)

    @staticmethod
    def _extract_activity_domain(text: str) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return ""
        match = re.search(
            r"(?i)\b((?:[a-z0-9-]+\.)+(?:com|cn|org|net|io|ai|dev|app|gg|tv|me|so|co|edu|gov|top|info|fm|cc|xyz|com\.cn|net\.cn))\b",
            normalized,
        )
        if not match:
            return ""
        domain = match.group(1).lower().strip(".")
        return domain[4:] if domain.startswith("www.") else domain

    @staticmethod
    def _clean_activity_site_label(text: str) -> str:
        label = str(text or "").strip()
        if not label:
            return ""
        label = re.sub(r"^\(\d+\)\s*", "", label).strip()
        label = re.sub(r"\s+", " ", label).strip("-|· ")
        return label[:60].strip()

    def _match_known_activity_site(self, text: str) -> dict[str, str]:
        lowered = f" {str(text or '').casefold()} "
        if not lowered.strip():
            return {}
        custom_match = self._match_custom_activity_site(text)
        if custom_match:
            return custom_match
        for domain, label, aliases in self.ACTIVITY_KNOWN_SITES:
            if domain.casefold() in lowered or any(alias.casefold() in lowered for alias in aliases):
                return {
                    "site_label": label,
                    "site_domain": domain,
                }
        return {}

    def _get_activity_recognition_rules(self) -> dict[str, list[dict[str, str]]]:
        raw_rules = str(getattr(self, "activity_recognition_rules", "") or "")
        cached_raw = getattr(self, "_activity_recognition_rules_cache_key", None)
        cached_rules = getattr(self, "_activity_recognition_rules_cache", None)
        if cached_raw == raw_rules and isinstance(cached_rules, dict):
            return cached_rules

        parsed_rules: dict[str, list[dict[str, str]]] = {
            "app": [],
            "site": [],
        }
        invalid_lines: list[int] = []

        for line_number, raw_line in enumerate(raw_rules.splitlines(), start=1):
            line = str(raw_line or "").strip()
            if not line or line.startswith("#"):
                continue

            parts = [str(part or "").strip() for part in raw_line.split("|")]
            if len(parts) < 3:
                invalid_lines.append(line_number)
                continue

            rule_kind = parts[0].casefold()
            pattern = str(parts[1] or "").strip()
            label = str(parts[2] or "").strip()
            if rule_kind not in {"app", "site"} or not pattern or not label:
                invalid_lines.append(line_number)
                continue

            if rule_kind == "app":
                cleaned_label = self._normalize_window_title(label)[:48]
                if not cleaned_label:
                    invalid_lines.append(line_number)
                    continue
                parsed_rules["app"].append(
                    {
                        "pattern": pattern.casefold(),
                        "label": cleaned_label,
                    }
                )
                continue

            cleaned_label = self._clean_activity_site_label(label)
            if not cleaned_label:
                invalid_lines.append(line_number)
                continue
            explicit_domain = self._extract_activity_domain(parts[3]) if len(parts) >= 4 else ""
            parsed_rules["site"].append(
                {
                    "pattern": pattern.casefold(),
                    "label": cleaned_label,
                    "site_domain": explicit_domain or self._extract_activity_domain(pattern),
                }
            )

        if invalid_lines:
            logger.debug(
                f"跳过无效的活动识别规则行: {', '.join(str(number) for number in invalid_lines[:12])}"
            )

        setattr(self, "_activity_recognition_rules_cache_key", raw_rules)
        setattr(self, "_activity_recognition_rules_cache", parsed_rules)
        setattr(self, "_activity_recognition_rules_invalid_lines", invalid_lines)
        return parsed_rules

    def _match_custom_activity_app_name(self, window_title: str) -> str:
        normalized_window = self._normalize_window_title(window_title or "")
        if not normalized_window:
            return ""
        lowered = f" {normalized_window.casefold()} "
        for rule in self._get_activity_recognition_rules().get("app", []):
            pattern = str(rule.get("pattern", "") or "").strip()
            label = str(rule.get("label", "") or "").strip()
            if pattern and label and pattern in lowered:
                return label
        return ""

    def _match_custom_activity_site(self, text: str) -> dict[str, str]:
        lowered = f" {str(text or '').casefold()} "
        if not lowered.strip():
            return {}
        for rule in self._get_activity_recognition_rules().get("site", []):
            pattern = str(rule.get("pattern", "") or "").strip()
            label = str(rule.get("label", "") or "").strip()
            if pattern and label and pattern in lowered:
                return {
                    "site_label": label,
                    "site_domain": str(
                        rule.get("site_domain", "") or self._extract_activity_domain(text)
                    ).strip(),
                }
        return {}

    def _get_activity_recognition_rule_summary(self) -> dict[str, int]:
        parsed_rules = self._get_activity_recognition_rules()
        app_rules = len(parsed_rules.get("app", []))
        site_rules = len(parsed_rules.get("site", []))
        invalid_lines = len(
            getattr(self, "_activity_recognition_rules_invalid_lines", []) or []
        )
        return {
            "app_rules": int(app_rules),
            "site_rules": int(site_rules),
            "total_rules": int(app_rules + site_rules),
            "invalid_lines": int(invalid_lines),
        }

    def _is_generic_browser_segment(self, text: str, *, app_name: str = "") -> bool:
        cleaned = self._clean_activity_site_label(text)
        lowered = cleaned.casefold()
        if not lowered:
            return True
        if lowered in self.ACTIVITY_GENERIC_BROWSER_SEGMENTS:
            return True
        if app_name and lowered == str(app_name).casefold():
            return True
        if re.fullmatch(r"\(\d+\)", lowered):
            return True
        for label, aliases in self.ACTIVITY_BROWSER_APP_ALIASES:
            if lowered == label.casefold():
                return True
            if any(lowered == alias.casefold().strip() for alias in aliases):
                return True
        return False

    def _derive_browser_title_context(
        self,
        *,
        normalized_window: str,
        app_name: str,
    ) -> dict[str, str]:
        raw_parts = self._split_activity_window_parts(normalized_window)
        meaningful_parts = [
            self._clean_activity_site_label(part)
            for part in raw_parts
            if not self._is_generic_browser_segment(part, app_name=app_name)
        ]
        meaningful_parts = [part for part in meaningful_parts if part]
        if not meaningful_parts:
            return {"site_label": "", "site_domain": "", "page_title": ""}

        site_label = ""
        site_domain = ""
        site_index = -1

        for idx in range(len(meaningful_parts) - 1, -1, -1):
            matched = self._match_known_activity_site(meaningful_parts[idx])
            if matched:
                site_label = str(matched.get("site_label", "") or "").strip()
                site_domain = str(matched.get("site_domain", "") or "").strip()
                site_index = idx
                break

        if not site_label:
            for idx in range(len(meaningful_parts) - 1, -1, -1):
                domain = self._extract_activity_domain(meaningful_parts[idx])
                if domain:
                    site_label = domain
                    site_domain = domain
                    site_index = idx
                    break

        if not site_label and len(meaningful_parts) >= 2:
            trailing = self._clean_activity_site_label(meaningful_parts[-1])
            if trailing and trailing.casefold() != str(app_name or "").casefold():
                site_label = trailing
                site_domain = self._extract_activity_domain(trailing)
                site_index = len(meaningful_parts) - 1

        page_parts = list(meaningful_parts)
        if site_index >= 0:
            page_parts = meaningful_parts[:site_index]
        elif len(meaningful_parts) > 1:
            page_parts = meaningful_parts[:-1]

        page_title = " · ".join(page_parts).strip(" ·")
        if page_title and site_label and page_title.casefold() == site_label.casefold():
            page_title = ""
        if page_title and app_name and page_title.casefold() == str(app_name).casefold():
            page_title = ""
        page_title = page_title[:96].strip()

        return {
            "site_label": site_label,
            "site_domain": site_domain,
            "page_title": page_title,
        }

    def _extract_activity_site_info(
        self,
        *,
        scene: str,
        window: str,
        app_name: str,
    ) -> dict[str, str]:
        normalized_scene = self._normalize_scene_label(scene or "")
        normalized_window = self._normalize_window_title(window or "")
        if not normalized_window:
            return {"site_label": "", "site_domain": "", "page_title": ""}

        if not self._is_activity_browser_app(app_name) and not normalized_scene.startswith("浏览"):
            return {"site_label": "", "site_domain": "", "page_title": ""}

        context = self._derive_browser_title_context(
            normalized_window=normalized_window,
            app_name=app_name,
        )
        if any(context.values()):
            return context
        return {"site_label": "", "site_domain": "", "page_title": ""}

    def _build_activity_record_meta(
        self,
        *,
        activity_type: str,
        scene: str,
        window: str,
    ) -> dict[str, Any]:
        normalized_type = str(activity_type or "其他").strip() or "其他"
        normalized_scene = self._normalize_scene_label(scene or "")
        normalized_window = self._normalize_window_title(window or "")
        app_name = self._detect_activity_app_name(normalized_window)
        site_info = self._extract_activity_site_info(
            scene=normalized_scene,
            window=normalized_window,
            app_name=app_name,
        )
        site_label = str(site_info.get("site_label", "") or "").strip()
        site_domain = str(site_info.get("site_domain", "") or "").strip()
        page_title = str(site_info.get("page_title", "") or "").strip()
        return {
            "type": normalized_type,
            "scene": normalized_scene,
            "window": normalized_window,
            "app_name": app_name,
            "site_label": site_label,
            "site_domain": site_domain,
            "page_title": page_title,
            "resource_kind": "page" if page_title else ("site" if site_label else "app"),
            "resource_label": page_title or site_label or app_name or normalized_window or "未命名活动",
        }

    def _normalize_activity_record(self, item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        raw_duration = max(0.0, float(item.get("raw_duration", item.get("duration", 0)) or 0))
        start_time = float(item.get("start_time", 0) or 0)
        end_time = float(item.get("end_time", 0) or 0)
        if raw_duration <= 0 and start_time > 0 and end_time > start_time:
            raw_duration = end_time - start_time

        meta = self._build_activity_record_meta(
            activity_type=str(item.get("type", "其他") or "其他"),
            scene=str(item.get("scene", "") or ""),
            window=str(item.get("window", "") or ""),
        )
        effective_duration = max(
            0.0,
            float(item.get("effective_duration", raw_duration) or raw_duration),
        )
        effective_duration = min(raw_duration, effective_duration) if raw_duration > 0 else 0.0
        idle_trimmed_seconds = max(
            0.0,
            float(item.get("idle_trimmed_seconds", raw_duration - effective_duration) or 0),
        )

        return {
            **meta,
            "start_time": start_time,
            "end_time": end_time,
            "duration": raw_duration,
            "raw_duration": raw_duration,
            "effective_duration": effective_duration if effective_duration > 0 else raw_duration,
            "idle_trimmed_seconds": idle_trimmed_seconds,
            "has_input_estimate": bool(item.get("has_input_estimate", False)),
            "capture_source": str(item.get("capture_source", meta.get("capture_source", "")) or "").strip(),
        }

    def _append_activity_record(
        self,
        *,
        activity: str,
        start_time: float,
        end_time: float,
        min_duration_seconds: int | None = None,
        activity_meta: dict[str, Any] | None = None,
    ) -> bool:
        min_duration = (
            self.ACTIVITY_MIN_DURATION_SECONDS
            if min_duration_seconds is None
            else max(0, int(min_duration_seconds or 0))
        )
        duration = float(end_time or 0) - float(start_time or 0)
        if not activity or duration < min_duration:
            return False

        activity_type, scene, window = self._parse_activity_marker(activity)
        meta = (
            dict(activity_meta)
            if isinstance(activity_meta, dict)
            else self._build_activity_record_meta(
                activity_type=activity_type,
                scene=scene,
                window=window,
            )
        )
        record = self._normalize_activity_record(
            {
                **meta,
                "type": meta.get("type", activity_type),
                "scene": meta.get("scene", scene),
                "window": meta.get("window", window),
                "start_time": float(start_time or 0),
                "end_time": float(end_time or 0),
                "duration": float(duration),
                "raw_duration": float(duration),
                "effective_duration": float(duration),
                "idle_trimmed_seconds": 0.0,
                "has_input_estimate": False,
                "capture_source": str(meta.get("capture_source", "") or "").strip(),
            }
        )
        if record is None:
            return False
        self.activity_history.append(record)
        if len(self.activity_history) > self.ACTIVITY_HISTORY_LIMIT:
            self.activity_history = self.activity_history[-self.ACTIVITY_HISTORY_LIMIT :]
        self._save_activity_history()
        return True

    def _build_current_activity_snapshot(self, now_ts: float | None = None) -> dict[str, Any] | None:
        current_activity = str(getattr(self, "current_activity", "") or "").strip()
        activity_start_time = float(getattr(self, "activity_start_time", 0) or 0)
        current_time = float(now_ts or time.time())
        if not current_activity or activity_start_time <= 0 or current_time <= activity_start_time:
            return None

        duration = current_time - activity_start_time
        if duration < self.LIVE_ACTIVITY_MIN_DURATION_SECONDS:
            return None

        activity_meta = getattr(self, "current_activity_meta", None)
        if isinstance(activity_meta, dict):
            snapshot = dict(activity_meta)
        else:
            activity_type, scene, window = self._parse_activity_marker(current_activity)
            snapshot = self._build_activity_record_meta(
                activity_type=activity_type,
                scene=scene,
                window=window,
            )
        return {
            **snapshot,
            "start_time": activity_start_time,
            "end_time": current_time,
            "duration": float(duration),
            "raw_duration": float(duration),
            "effective_duration": float(duration),
            "idle_trimmed_seconds": 0.0,
            "has_input_estimate": False,
            "capture_source": str(
                snapshot.get(
                    "capture_source",
                    getattr(self, "current_activity_source", "") or "",
                )
                or ""
            ).strip(),
            "is_live": True,
        }

    def _get_activity_history_for_stats(self) -> list[dict[str, Any]]:
        activity_history = list(getattr(self, "activity_history", []) or [])
        current_snapshot = self._build_current_activity_snapshot()
        if current_snapshot:
            activity_history.append(current_snapshot)
        return activity_history

    def _detect_window_changes(self):
        """检测窗口变化，包括新打开的窗口。"""
        import time
        current_time = time.time()
        
        # 检查冷却时间
        if not hasattr(self, 'window_change_cooldown'):
            self.window_change_cooldown = 0
        if current_time < self.window_change_cooldown:
            return False, []
        
        # 检查窗口相关属性
        if not hasattr(self, 'previous_windows'):
            self.previous_windows = set()
        if not hasattr(self, 'window_timestamps'):
            self.window_timestamps = {}
        
        # 获取当前打开的窗口
        current_windows = set(self._list_open_window_titles())
        current_windows = {w for w in current_windows if w and w.strip()}
        
        # 更新窗口时间戳
        valid_new_windows = []
        
        # 处理当前存在的窗口
        for window in current_windows:
            if window not in self.window_timestamps:
                # 记录新窗口的首次出现时间
                self.window_timestamps[window] = current_time
            else:
                # 检查窗口是否持续存在3分钟
                if current_time - self.window_timestamps[window] >= 180:  # 3分钟 = 180秒
                    # 窗口持续存在3分钟，标记为有效新窗口
                    if window not in self.previous_windows:
                        valid_new_windows.append(window)
        
        # 清理已关闭的窗口记录
        closed_windows = list(self.window_timestamps.keys())
        for window in closed_windows:
            if window not in current_windows:
                del self.window_timestamps[window]
        
        # 更新窗口状态
        if current_windows != self.previous_windows:
            self.previous_windows = current_windows
            # 设置冷却时间，避免频繁触发
            self.window_change_cooldown = current_time + 5  # 5秒冷却
            return True, valid_new_windows
        
        return False, []

    def _ensure_auto_screen_runtime_state(self, task_id: str) -> dict[str, Any]:
        self._ensure_runtime_state()
        normalized_task_id = str(task_id or self.AUTO_TASK_ID).strip() or self.AUTO_TASK_ID
        runtime = self.auto_screen_runtime
        state = runtime.get(normalized_task_id)
        if not isinstance(state, dict):
            state = {
                "last_seen_window_title": "",
                "last_scene": "",
                "last_change_at": 0.0,
                "last_change_reason": "",
                "last_new_windows": [],
                "last_trigger_at": 0.0,
                "last_trigger_reason": "",
                "last_effective_probability": 0,
                "last_trigger_roll": None,
                "last_idle_keepalive_due": False,
                "last_sent_at": 0.0,
                "last_reply_signature": "",
                "last_reply_window_title": "",
                "last_reply_scene": "",
                "last_reply_preview": "",
                "last_skip_reason": "",
            }
            runtime[normalized_task_id] = state
        return state

    def _build_auto_screen_change_snapshot(
        self,
        task_id: str,
        *,
        window_changed: bool = False,
        new_windows: list[str] | None = None,
        update_state: bool = True,
    ) -> dict[str, Any]:
        state = self._ensure_auto_screen_runtime_state(task_id)
        active_window_title, _ = self._get_active_window_info()
        active_window_title = self._normalize_window_title(active_window_title)
        scene = ""
        if active_window_title:
            scene = self._normalize_scene_label(self._identify_scene(active_window_title))

        previous_window_title = str(state.get("last_seen_window_title", "") or "").strip()
        previous_scene = str(state.get("last_scene", "") or "").strip()
        normalized_new_windows = [
            title
            for title in (self._normalize_window_title(title) for title in (new_windows or []))
            if title
        ]

        reasons: list[str] = []
        if window_changed and normalized_new_windows:
            reasons.append("新窗口出现")
        elif window_changed:
            reasons.append("窗口列表变化")

        if active_window_title and active_window_title.casefold() != previous_window_title.casefold():
            reasons.append("活动窗口变化")

        if scene and previous_scene and scene != previous_scene:
            reasons.append("场景变化")

        changed = bool(reasons)
        now_ts = time.time()
        if update_state:
            state["last_seen_window_title"] = active_window_title
            state["last_scene"] = scene
            state["last_new_windows"] = normalized_new_windows[:3]
            if changed:
                state["last_change_at"] = now_ts
                state["last_change_reason"] = "、".join(dict.fromkeys(reasons))

        return {
            "task_id": str(task_id or self.AUTO_TASK_ID).strip() or self.AUTO_TASK_ID,
            "active_window_title": active_window_title,
            "scene": scene,
            "changed": changed,
            "reason": "、".join(dict.fromkeys(reasons)),
            "new_windows": normalized_new_windows[:3],
            "timestamp": now_ts,
        }

    def _is_idle_keepalive_due(self, task_id: str, check_interval: int) -> bool:
        state = self._ensure_auto_screen_runtime_state(task_id)
        last_sent_at = float(state.get("last_sent_at", 0.0) or 0.0)
        if last_sent_at <= 0:
            return True

        threshold = max(
            int(check_interval or 0) * 3,
            self.CHANGE_AWARE_IDLE_KEEPALIVE_SECONDS,
        )
        return (time.time() - last_sent_at) >= threshold

    def _decide_auto_screen_trigger(
        self,
        task_id: str,
        *,
        probability: int,
        check_interval: int,
        system_high_load: bool,
        change_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        import random

        state = self._ensure_auto_screen_runtime_state(task_id)
        now_ts = time.time()
        is_window_companion_task = (
            str(task_id or "").strip()
            == str(getattr(self, "WINDOW_COMPANION_TASK_ID", "") or "").strip()
        )
        configured_probability = max(0, min(100, int(probability or 0)))
        if system_high_load:
            if is_window_companion_task:
                random_number = random.randint(1, 100)
                decision = {
                    "trigger": random_number <= configured_probability,
                    "reason": "系统负载较高，但窗口陪伴按设置概率判定",
                    "effective_probability": configured_probability,
                    "random_number": random_number,
                    "idle_keepalive_due": False,
                }
            else:
                decision = {
                    "trigger": True,
                    "reason": "系统负载较高，强制触发识屏",
                    "effective_probability": 100,
                    "random_number": None,
                    "idle_keepalive_due": False,
                }
        else:
            idle_keepalive_due = self._is_idle_keepalive_due(task_id, check_interval)
            if change_snapshot.get("changed"):
                if is_window_companion_task:
                    effective_probability = configured_probability
                    reason = (
                        f"检测到{change_snapshot.get('reason') or '窗口变化'}，"
                        "窗口陪伴按设置概率判定"
                    )
                else:
                    effective_probability = min(100, max(configured_probability, 85))
                    reason = f"检测到{change_snapshot.get('reason') or '窗口变化'}，提升本轮触发概率"
            elif idle_keepalive_due:
                if is_window_companion_task:
                    effective_probability = configured_probability
                    reason = "当前窗口停留较久，窗口陪伴按设置概率判定"
                else:
                    effective_probability = min(100, max(configured_probability, 30))
                    reason = "当前窗口停留较久，保留一次低频跟进机会"
            else:
                effective_probability = min(configured_probability, 15)
                reason = "当前画面变化不大，降低本轮触发概率"

            random_number = random.randint(1, 100)
            decision = {
                "trigger": random_number <= effective_probability,
                "reason": reason,
                "effective_probability": effective_probability,
                "random_number": random_number,
                "idle_keepalive_due": idle_keepalive_due,
            }

            presence_mode = self._build_presence_mode_snapshot(
                task_id,
                scene=str(change_snapshot.get("scene", "") or ""),
                change_snapshot=change_snapshot,
            )
            adjusted_probability = int(
                round(
                    float(decision["effective_probability"] or 0)
                    * float(presence_mode.get("probability_factor", 1.0) or 1.0)
                )
            )
            adjusted_probability = min(100, adjusted_probability)
            if adjusted_probability != decision["effective_probability"]:
                decision["reason"] = (
                    f"{decision['reason']}；当前更像{presence_mode.get('label', '当前节奏')}，本轮进一步收敛主动打扰"
                )
                decision["effective_probability"] = adjusted_probability
                if decision["random_number"] is not None:
                    decision["trigger"] = decision["random_number"] <= adjusted_probability

        state["last_trigger_reason"] = decision["reason"]
        state["last_effective_probability"] = int(decision["effective_probability"] or 0)
        state["last_trigger_roll"] = decision["random_number"]
        state["last_idle_keepalive_due"] = bool(decision["idle_keepalive_due"])
        if decision["trigger"]:
            state["last_trigger_at"] = now_ts
            state["last_skip_reason"] = ""
        return decision

    def _should_skip_similar_auto_reply(
        self,
        task_id: str,
        *,
        active_window_title: str,
        text_content: str,
        check_interval: int,
    ) -> tuple[bool, str]:
        normalized_text = self._normalize_record_text(text_content)[:160]
        if not normalized_text:
            return False, ""

        state = self._ensure_auto_screen_runtime_state(task_id)
        last_signature = str(state.get("last_reply_signature", "") or "").strip()
        last_window_title = self._normalize_window_title(
            state.get("last_reply_window_title", "")
        )
        current_window_title = self._normalize_window_title(active_window_title)
        last_sent_at = float(state.get("last_sent_at", 0.0) or 0.0)
        cooldown_seconds = max(
            int(check_interval or 0) * 3,
            self.CHANGE_AWARE_SIMILAR_REPLY_COOLDOWN_SECONDS,
        )

        if (
            normalized_text
            and last_signature == normalized_text
            and current_window_title
            and current_window_title.casefold() == last_window_title.casefold()
            and last_sent_at > 0
            and (time.time() - last_sent_at) < cooldown_seconds
        ):
            return (
                True,
                f"同一窗口下识别结果相近，仍在 {cooldown_seconds} 秒冷却内",
            )

        return False, ""

    def _remember_auto_reply_state(
        self,
        task_id: str,
        *,
        active_window_title: str,
        text_content: str,
        sent: bool,
        scene: str = "",
        note: str = "",
    ) -> None:
        state = self._ensure_auto_screen_runtime_state(task_id)
        normalized_text = self._normalize_record_text(text_content)[:160]
        state["last_reply_window_title"] = self._normalize_window_title(active_window_title)
        state["last_reply_scene"] = self._normalize_scene_label(scene)
        if normalized_text:
            state["last_reply_signature"] = normalized_text
        state["last_reply_preview"] = self._truncate_preview_text(text_content, limit=120)
        state["last_skip_reason"] = str(note or "").strip()
        if sent:
            state["last_sent_at"] = time.time()

    def _format_reply_interval_text(self, seconds: float) -> str:
        total_seconds = max(0, int(seconds or 0))
        if total_seconds < 60:
            return f"{total_seconds}秒"

        total_minutes = total_seconds // 60
        if total_minutes < 60:
            if total_minutes < 5 and total_seconds % 60:
                return f"{total_minutes}分{total_seconds % 60}秒"
            return f"{total_minutes}分钟"

        total_hours = total_minutes // 60
        remaining_minutes = total_minutes % 60
        if total_hours < 24:
            if total_hours < 3 and remaining_minutes:
                return f"{total_hours}小时{remaining_minutes}分钟"
            return f"{total_hours}小时"

        total_days = total_hours // 24
        remaining_hours = total_hours % 24
        if total_days < 3 and remaining_hours:
            return f"{total_days}天{remaining_hours}小时"
        return f"{total_days}天"

    def _build_reply_interval_guidance(self, task_id: str) -> tuple[str, dict[str, Any]]:
        state = self._ensure_auto_screen_runtime_state(task_id)
        last_sent_at = float(state.get("last_sent_at", 0.0) or 0.0)
        if last_sent_at <= 0:
            return (
                "这是这段时间里较少见的一次主动靠近。可以自然一点，但仍要直接从当前画面切入，"
                "不要假装刚才已经接过话，也不要写得像固定问候或标准开场白。",
                {
                    "bucket": "first_touch",
                    "elapsed_seconds": 0,
                    "elapsed_text": "",
                },
            )

        elapsed_seconds = max(0, int(time.time() - last_sent_at))
        elapsed_text = self._format_reply_interval_text(elapsed_seconds)

        if elapsed_seconds < 3 * 60:
            return (
                f"距离上一次主动回复仅约 {elapsed_text}。这次更像顺着刚才的话补一句，"
                "只点出新的变化、判断或下一步，不要重新开场，不要重复同一句提醒，也不要再来一遍完整播报。",
                {
                    "bucket": "immediate_followup",
                    "elapsed_seconds": elapsed_seconds,
                    "elapsed_text": elapsed_text,
                },
            )

        if elapsed_seconds < 15 * 60:
            return (
                f"距离上一次主动回复约 {elapsed_text}。延续陪伴感即可，可以轻轻承接刚才到现在的新变化，"
                "但不要把语气写得像重新开始一轮对话，也不要重复使用固定句式。",
                {
                    "bucket": "recent_followup",
                    "elapsed_seconds": elapsed_seconds,
                    "elapsed_text": elapsed_text,
                },
            )

        if elapsed_seconds < 90 * 60:
            return (
                f"距离上一次主动回复约 {elapsed_text}。可以有一点重新跟上的感觉，"
                "先简短点出当前变化，再给一句观察、共鸣或建议；仍然不要太正式，也别写成套路化称赞。",
                {
                    "bucket": "soft_reentry",
                    "elapsed_seconds": elapsed_seconds,
                    "elapsed_text": elapsed_text,
                },
            )

        return (
            f"距离上一次主动回复约 {elapsed_text}。可以带一点隔了一阵子后重新靠近的感觉，"
            "但仍要立刻落在当前画面，不要长篇回顾，也不要显得生硬客套或像预制台词。",
            {
                "bucket": "long_gap_reentry",
                "elapsed_seconds": elapsed_seconds,
                "elapsed_text": elapsed_text,
            },
        )

    def _remember_recent_user_activity(self, event: AstrMessageEvent) -> None:
        self._ensure_runtime_state()
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not umo:
            return

        self.recent_user_activity[umo] = time.time()
        if len(self.recent_user_activity) > 100:
            sorted_items = sorted(
                self.recent_user_activity.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            self.recent_user_activity = dict(sorted_items[:100])

    def _get_recent_user_activity_at(self, target_or_event: Any = None) -> float:
        self._ensure_runtime_state()
        umo = ""
        if isinstance(target_or_event, str):
            umo = str(target_or_event or "").strip()
        elif target_or_event is not None:
            umo = str(getattr(target_or_event, "unified_msg_origin", "") or "").strip()

        if not umo:
            return 0.0
        return float(self.recent_user_activity.get(umo, 0.0) or 0.0)

    def _should_defer_for_recent_user_activity(
        self,
        event: AstrMessageEvent,
        *,
        task_id: str,
        change_snapshot: dict[str, Any],
    ) -> tuple[bool, str]:
        last_activity_at = self._get_recent_user_activity_at(event)
        if last_activity_at <= 0:
            return False, ""

        seconds_since = max(0, int(time.time() - last_activity_at))
        grace_seconds = self.USER_ACTIVITY_GRACE_SECONDS
        if change_snapshot.get("changed"):
            grace_seconds = self.USER_ACTIVITY_CHANGE_GRACE_SECONDS

        if seconds_since >= grace_seconds:
            return False, ""

        reason = (
            f"用户刚在 {seconds_since} 秒前发过消息，先暂缓这次主动打断"
        )
        self._ensure_auto_screen_runtime_state(task_id)["last_skip_reason"] = reason
        return True, reason

    def _get_scene_behavior_profile(self, scene: str) -> dict[str, Any]:
        normalized_scene = self._normalize_scene_label(scene)
        entertainment_scenes = {"视频", "游戏", "浏览-娱乐", "音乐", "社交"}
        work_scenes = {"编程", "设计", "办公", "学习", "阅读", "浏览", "浏览-工作"}

        if normalized_scene in entertainment_scenes:
            return {
                "category": "entertainment",
                "same_window_cooldown": self.ENTERTAINMENT_WINDOW_MESSAGE_COOLDOWN_SECONDS,
                "tone_instruction": "语气更像陪伴和轻提醒，不要频繁推进任务，也不要把用户从内容里拽出来。",
                "prefer_sample_only": False,
                "presence_style": "companion",
                "wrap_up_style": "轻轻接住感受，顺一点点往下走，不要像复盘总结。",
            }
        if normalized_scene in work_scenes:
            return {
                "category": "work",
                "same_window_cooldown": self.WORK_WINDOW_MESSAGE_COOLDOWN_SECONDS,
                "tone_instruction": "语气保持克制、直接、任务导向，优先指出卡点、下一步和可立即执行的建议。",
                "prefer_sample_only": True,
                "presence_style": "assistant",
                "wrap_up_style": "如果像刚收住一段任务，可以轻轻确认收尾，再顺一句下一步。",
            }
        return {
            "category": "general",
            "same_window_cooldown": self.GENERAL_WINDOW_MESSAGE_COOLDOWN_SECONDS,
            "tone_instruction": "语气自然、简短，既给出帮助，也尽量避免抢占注意力。",
            "prefer_sample_only": True,
            "presence_style": "balanced",
            "wrap_up_style": "如果像刚完成一小段，可以自然地点一下收住感，但不要抢节奏。",
        }

    def _build_presence_mode_snapshot(
        self,
        task_id: str,
        *,
        scene: str,
        change_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self._get_scene_behavior_profile(scene)
        state = self._ensure_auto_screen_runtime_state(task_id)
        snapshot = dict(change_snapshot or {})
        now_ts = time.time()
        changed = bool(snapshot.get("changed"))
        last_change_at = float(state.get("last_change_at", 0.0) or 0.0)
        seconds_since_change = 0 if changed else max(0, int(now_ts - last_change_at)) if last_change_at > 0 else 0

        mode = "balanced"
        label = "平衡陪伴"
        probability_factor = 1.0
        cooldown_scale = 1.0
        prompt_guidance = "先贴着当前内容说人话，不要太正式，也不要抢用户注意力。"

        if profile["category"] == "work":
            if not changed and seconds_since_change >= 12 * 60:
                mode = "deep_focus"
                label = "深度专注"
                probability_factor = 0.35
                cooldown_scale = 1.8
                prompt_guidance = "用户更像在深度专注，除非真的有价值变化，否则尽量少打断；如果要说，只说最关键的一句。"
            elif not changed and seconds_since_change >= 5 * 60:
                mode = "focused_work"
                label = "专注工作"
                probability_factor = 0.6
                cooldown_scale = 1.35
                prompt_guidance = "用户正持续推进任务，语气更像靠谱助手，优先指出真正能推进的一步。"
            else:
                mode = "assistant"
                label = "任务助手"
                prompt_guidance = "用户当前更需要助手感：直接、具体、少铺垫，帮助把任务继续往前推。"
        elif profile["category"] == "entertainment":
            if changed:
                mode = "companion"
                label = "内容陪伴"
                probability_factor = 0.9
                prompt_guidance = "更像一起在看内容，先顺着情绪和内容轻轻接话，不要把用户拽出体验。"
            else:
                mode = "ambient_companion"
                label = "低打扰陪伴"
                probability_factor = 0.75
                cooldown_scale = 1.2
                prompt_guidance = "当前更适合低打扰陪伴，除非有新变化或真有意思的点，否则别频繁出声。"
        else:
            mode = "balanced"
            label = "平衡陪伴"
            probability_factor = 0.8 if not changed else 1.0
            cooldown_scale = 1.1 if not changed else 1.0
            prompt_guidance = "自然陪着即可，先观察当前内容值不值得说，再决定要不要开口。"

        state["last_presence_mode"] = mode
        return {
            "mode": mode,
            "label": label,
            "probability_factor": probability_factor,
            "cooldown_scale": cooldown_scale,
            "seconds_since_change": seconds_since_change,
            "prompt_guidance": prompt_guidance,
            "wrap_up_style": profile.get("wrap_up_style", ""),
        }

    def _build_social_chat_context(
        self,
        *,
        scene: str,
        contexts: list[str] | None = None,
        request_intent: dict[str, Any] | None = None,
        presence_mode: dict[str, Any] | None = None,
        reply_interval_info: dict[str, Any] | None = None,
        recognition_text: str = "",
        active_window_title: str = "",
    ) -> dict[str, Any]:
        profile = self._get_scene_behavior_profile(scene)
        mode = str((presence_mode or {}).get("mode", "") or "")
        elapsed_seconds = int((reply_interval_info or {}).get("elapsed_seconds", 0) or 0)
        intent_action = str((request_intent or {}).get("action", "") or "")
        intent_type = str((request_intent or {}).get("intent_type", "") or "")

        recent_contexts = [str(item or "").strip() for item in list(contexts or []) if str(item or "").strip()]
        last_assistant = ""
        last_user = ""
        for item in reversed(recent_contexts):
            if not last_assistant and item.startswith("助手:"):
                last_assistant = item.split(":", 1)[-1].strip()
            if not last_user and item.startswith("用户:"):
                last_user = item.split(":", 1)[-1].strip()
            if last_assistant and last_user:
                break

        combined_recent = self._normalize_record_text(
            " ".join(
                part for part in (
                    last_user,
                    last_assistant,
                    recognition_text,
                    active_window_title,
                ) if part
            )
        )

        emotion_markers = (
            "哈哈", "笑死", "绷不住", "离谱", "好烦", "难受", "崩", "绝望",
            "牛", "爽", "稳", "刺激", "紧张", "好耶", "可恶", "无语",
        )
        frustration_markers = (
            "报错", "失败", "卡住", "不行", "没过", "打断", "崩溃", "死了", "寄",
            "难受", "麻烦", "无语", "烦",
        )
        social_scene = profile["category"] == "entertainment" or self._normalize_scene_label(scene) == "社交"

        style = "light_companion"
        label = "轻陪伴接话"
        guidance_lines = [
            "把这次回复当成社交媒体私聊里的连续聊天，不要像重新开一个新话题。",
            "优先像人类顺手接话：短一点、自然一点、留白一点。",
            "观察只是你心里的依据，不是必须先说出口的开场白。",
        ]
        if self._normalize_scene_label(scene) == "游戏":
            guidance_lines.extend(
                [
                    "如果没有特别明确的画面证据，就不要装作已经认出具体角色、模式、强化或阵容。",
                    "这轮更适合像顺手点评一句，而不是切成陪玩教练模式长篇指挥。",
                ]
            )

        if intent_action == "clarify_or_switch":
            style = "quick_clarify"
            label = "简短澄清"
            guidance_lines.extend(
                [
                    "这轮更像先接一句澄清，而不是展开点评。",
                    "先说你现在还没看到用户要找的东西，再请对方切过去或告诉你在哪。"
                ]
            )
        elif intent_type in {"guidance", "verify", "explain"} or profile["category"] == "work":
            style = "practical_reply"
            label = "实用接话"
            guidance_lines.extend(
                [
                    "这轮更像认真回一句有用的话，先给结论或下一步，再补一句轻微陪伴感就够了。",
                    "不要先寒暄半天再进入正题。"
                ]
            )
        elif any(marker in combined_recent for marker in frustration_markers):
            style = "gentle_support"
            label = "轻安慰接话"
            guidance_lines.extend(
                [
                    "最近语境里带一点挫败感，先轻轻接住情绪，再给一句不压人的建议。",
                    "避免高浓度打鸡血，也不要把安慰写成空话。"
                ]
            )
        elif social_scene and any(marker in combined_recent for marker in emotion_markers):
            style = "banter_reply"
            label = "轻松接梗"
            guidance_lines.extend(
                [
                    "这轮可以更像私聊里的轻松接梗或顺势吐槽，但仍然要贴着当前内容。",
                    "别硬抖机灵，别为了活泼而编造细节。"
                ]
            )
        elif mode in {"deep_focus", "focused_work", "ambient_companion"}:
            style = "low_interrupt"
            label = "低打扰接话"
            guidance_lines.extend(
                [
                    "当前更适合低打扰，像在聊天框里留一句短短的话。",
                    "如果没有新的高价值观察，就宁可少说，不要补满。"
                ]
            )

        if elapsed_seconds < 3 * 60:
            guidance_lines.append("延续感要很强，像上一条消息的后半句，不要再做完整开场。")
        elif elapsed_seconds < 15 * 60:
            guidance_lines.append("像隔了几分钟又补一句，承接就好，不需要重新自我介绍式开头。")
        else:
            guidance_lines.append("虽然隔了一阵，但仍然像同一个聊天窗口里的续上，不要切成客服式问候。")

        guidance_lines.extend(
            [
                "尽量使用 1 到 2 句短句；只有用户明确在问问题时才展开到 3 句。",
                "避免反复称呼用户，避免每次都带夸张语气词。",
            ]
        )

        return {
            "style": style,
            "label": label,
            "guidance": "\n".join(guidance_lines),
            "last_user": self._truncate_preview_text(last_user, limit=80),
            "last_assistant": self._truncate_preview_text(last_assistant, limit=80),
        }

    @staticmethod
    def _format_usage_context_duration(seconds: float | int) -> str:
        total_seconds = max(0, int(float(seconds or 0)))
        if total_seconds < 60:
            return f"{total_seconds}秒"
        total_minutes = total_seconds // 60
        if total_minutes < 60:
            return f"{total_minutes}分钟"
        hours, minutes = divmod(total_minutes, 60)
        if minutes == 0:
            return f"{hours}小时"
        return f"{hours}小时{minutes}分钟"

    def _looks_like_usage_context_request(
        self,
        request_text: str,
    ) -> dict[str, bool]:
        normalized = self._normalize_record_text(request_text).casefold()
        if not normalized:
            return {
                "activity": False,
                "browser": False,
                "timeline": False,
            }

        activity_markers = (
            "在干嘛", "干什么", "做什么", "最近在", "最近都在", "一直在",
            "用了多久", "多长时间", "停留了多久", "摸鱼", "工作了多久",
            "切了什么", "用了哪些应用", "打开了什么", "活动轨迹",
        )
        browser_markers = (
            "浏览了什么", "看了什么网页", "哪些网页", "网页", "网站",
            "浏览记录", "浏览历史", "页面", "标签页", "网址",
        )
        timeline_markers = (
            "刚才", "最近", "之前", "这段时间", "今天", "过去", "一会儿前",
            "方才", "一直",
        )
        return {
            "activity": any(marker in normalized for marker in activity_markers),
            "browser": any(marker in normalized for marker in browser_markers),
            "timeline": any(marker in normalized for marker in timeline_markers),
        }

    def _build_usage_context_decision(
        self,
        *,
        scene: str,
        active_window_title: str,
        request_intent: dict[str, Any] | None = None,
        contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        if not bool(getattr(self, "enable_usage_context_autopilot", False)):
            return {
                "enabled": False,
                "used": False,
                "include_activity": False,
                "include_input": False,
                "include_browser_activity": False,
                "include_local_browser_history": False,
                "reason": "使用情况自动参考未开启",
            }

        normalized_scene = self._normalize_scene_label(scene or "")
        current_window = self._normalize_window_title(active_window_title or "")
        request_text = str((request_intent or {}).get("objective", "") or (request_intent or {}).get("request_text", "") or "").strip()
        request_flags = self._looks_like_usage_context_request(request_text)
        browser_scene = normalized_scene.startswith("浏览") or normalized_scene in {"邮件", "社交"}
        if not browser_scene and current_window:
            browser_scene = self._is_activity_browser_app(
                self._detect_activity_app_name(current_window)
            )

        include_activity = bool(
            request_flags["activity"]
            or request_flags["timeline"]
            or getattr(self, "use_companion_mode", False)
            or getattr(self, "stealth_watch_mode", False)
        )
        include_input = bool(
            getattr(self, "enable_input_stats", False)
            and (
                request_flags["activity"]
                or request_flags["timeline"]
                or (
                    getattr(self, "use_companion_mode", False)
                    and normalized_scene in {"编程", "设计", "办公", "浏览-工作", "邮件"}
                )
            )
        )
        include_browser_activity = bool(
            request_flags["browser"]
            or (
                browser_scene
                and (
                    getattr(self, "stealth_watch_mode", False)
                    or request_flags["browser"]
                )
            )
        )
        include_local_browser_history = bool(
            getattr(self, "enable_local_browser_history", False)
            and (
                request_flags["browser"]
                or (browser_scene and getattr(self, "stealth_watch_mode", False))
            )
        )

        used = any(
            (
                include_activity,
                include_input,
                include_browser_activity,
                include_local_browser_history,
            )
        )
        reasons = []
        if request_flags["activity"]:
            reasons.append("用户这轮像是在问最近在做什么/做了多久")
        if request_flags["browser"]:
            reasons.append("用户这轮像是在问浏览过哪些页面")
        if getattr(self, "use_companion_mode", False):
            reasons.append("陪伴模式允许低调参考持续状态，用来理解用户在做什么")
        if getattr(self, "stealth_watch_mode", False):
            reasons.append("偷看模式更适合结合行为变化做反应")
        if browser_scene:
            reasons.append("当前场景本身就是浏览器/页面相关")

        return {
            "enabled": True,
            "used": used,
            "include_activity": include_activity,
            "include_input": include_input,
            "include_browser_activity": include_browser_activity,
            "include_local_browser_history": include_local_browser_history,
            "reason": "；".join(reasons[:4]) or "当前这轮没有命中额外使用情况参考条件",
            "request_flags": request_flags,
            "browser_scene": browser_scene,
        }

    def _build_recent_activity_summary_lines(
        self,
        *,
        lookback_hours: int | None = None,
        limit: int | None = None,
    ) -> list[str]:
        lookback_seconds = max(
            1,
            int(lookback_hours or getattr(self, "usage_context_lookback_hours", 6) or 6),
        ) * 3600
        item_limit = max(
            1,
            int(limit or getattr(self, "usage_context_item_limit", 6) or 6),
        )
        cutoff_ts = time.time() - lookback_seconds
        aggregates: dict[tuple[str, str], dict[str, Any]] = {}

        for item in self._get_activity_history_for_stats():
            if not isinstance(item, dict):
                continue
            end_time = float(item.get("end_time", 0) or 0)
            if end_time and end_time < cutoff_ts:
                continue
            duration = max(
                0.0,
                float(
                    item.get(
                        "effective_duration",
                        item.get("raw_duration", item.get("duration", 0)),
                    )
                    or 0
                ),
            )
            if duration < 90:
                continue
            scene = self._normalize_scene_label(item.get("scene") or "")
            label = str(
                item.get("page_title")
                or item.get("site_label")
                or item.get("app_name")
                or item.get("resource_label")
                or item.get("window")
                or ""
            ).strip()
            if not label:
                continue
            key = (scene, label)
            aggregate = aggregates.setdefault(
                key,
                {
                    "scene": scene,
                    "label": label,
                    "duration": 0.0,
                    "latest_end_time": 0.0,
                },
            )
            aggregate["duration"] += duration
            aggregate["latest_end_time"] = max(aggregate["latest_end_time"], end_time)

        ranked = sorted(
            aggregates.values(),
            key=lambda item: (float(item.get("duration", 0) or 0), float(item.get("latest_end_time", 0) or 0)),
            reverse=True,
        )[:item_limit]
        lines = []
        for item in ranked:
            scene = str(item.get("scene", "") or "").strip()
            label = str(item.get("label", "") or "").strip()
            duration_label = self._format_usage_context_duration(item.get("duration", 0))
            if scene:
                lines.append(f"{label} 约 {duration_label}（{scene}）")
            else:
                lines.append(f"{label} 约 {duration_label}")
        return lines

    def _build_recent_scene_summary_lines(
        self,
        *,
        lookback_hours: int | None = None,
        limit: int | None = None,
    ) -> list[str]:
        lookback_seconds = max(
            1,
            int(lookback_hours or getattr(self, "usage_context_lookback_hours", 6) or 6),
        ) * 3600
        item_limit = max(
            1,
            int(limit or getattr(self, "usage_context_item_limit", 6) or 6),
        )
        cutoff_ts = time.time() - lookback_seconds
        aggregates: dict[str, float] = {}

        for item in self._get_activity_history_for_stats():
            if not isinstance(item, dict):
                continue
            end_time = float(item.get("end_time", 0) or 0)
            if end_time and end_time < cutoff_ts:
                continue
            duration = max(
                0.0,
                float(
                    item.get(
                        "effective_duration",
                        item.get("raw_duration", item.get("duration", 0)),
                    )
                    or 0
                ),
            )
            if duration < 90:
                continue
            scene = self._normalize_scene_label(item.get("scene") or "") or "未识别场景"
            aggregates[scene] = aggregates.get(scene, 0.0) + duration

        ranked = sorted(
            aggregates.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:item_limit]
        return [
            f"{scene} 约 {self._format_usage_context_duration(duration)}"
            for scene, duration in ranked
        ]

    def _build_recent_app_summary_lines(
        self,
        *,
        lookback_hours: int | None = None,
        limit: int | None = None,
    ) -> list[str]:
        lookback_seconds = max(
            1,
            int(lookback_hours or getattr(self, "usage_context_lookback_hours", 6) or 6),
        ) * 3600
        item_limit = max(
            1,
            int(limit or getattr(self, "usage_context_item_limit", 6) or 6),
        )
        cutoff_ts = time.time() - lookback_seconds
        aggregates: dict[str, float] = {}

        for item in self._get_activity_history_for_stats():
            if not isinstance(item, dict):
                continue
            end_time = float(item.get("end_time", 0) or 0)
            if end_time and end_time < cutoff_ts:
                continue
            duration = max(
                0.0,
                float(
                    item.get(
                        "effective_duration",
                        item.get("raw_duration", item.get("duration", 0)),
                    )
                    or 0
                ),
            )
            if duration < 90:
                continue
            app_name = str(
                item.get("app_name")
                or self._detect_activity_app_name(item.get("window", "") or "")
                or ""
            ).strip()
            if not app_name:
                continue
            aggregates[app_name] = aggregates.get(app_name, 0.0) + duration

        ranked = sorted(
            aggregates.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:item_limit]
        return [
            f"{app_name} 约 {self._format_usage_context_duration(duration)}"
            for app_name, duration in ranked
        ]

    def _build_recent_browsing_activity_lines(
        self,
        *,
        lookback_hours: int | None = None,
        limit: int | None = None,
    ) -> list[str]:
        lookback_seconds = max(
            1,
            int(lookback_hours or getattr(self, "usage_context_lookback_hours", 6) or 6),
        ) * 3600
        item_limit = max(
            1,
            int(limit or getattr(self, "usage_context_item_limit", 6) or 6),
        )
        cutoff_ts = time.time() - lookback_seconds
        seen: set[str] = set()
        lines: list[str] = []

        items = sorted(
            self._get_activity_history_for_stats(),
            key=lambda item: float((item or {}).get("end_time", 0) or 0),
            reverse=True,
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            end_time = float(item.get("end_time", 0) or 0)
            if end_time and end_time < cutoff_ts:
                continue
            site_label = str(item.get("site_label", "") or "").strip()
            page_title = str(item.get("page_title", "") or "").strip()
            if not site_label and not page_title:
                continue
            if page_title and site_label:
                label = f"{site_label} 的《{page_title}》"
            else:
                label = page_title or site_label
            key = label.casefold()
            if key in seen:
                continue
            seen.add(key)
            lines.append(label)
            if len(lines) >= item_limit:
                break
        return lines

    def _get_local_browser_history_candidates(self) -> list[tuple[str, str]]:
        import glob

        local_appdata = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
        if not local_appdata:
            return []

        roots = [
            ("Chrome", os.path.join(local_appdata, "Google", "Chrome", "User Data")),
            ("Edge", os.path.join(local_appdata, "Microsoft", "Edge", "User Data")),
            ("Brave", os.path.join(local_appdata, "BraveSoftware", "Brave-Browser", "User Data")),
        ]
        candidates: list[tuple[str, str]] = []
        for browser_name, root in roots:
            if not os.path.isdir(root):
                continue
            profile_paths = [os.path.join(root, "Default", "History")]
            profile_paths.extend(glob.glob(os.path.join(root, "Profile *", "History")))
            for path in profile_paths:
                if os.path.isfile(path):
                    candidates.append((browser_name, path))
        return candidates

    def _read_local_browser_history_entries(
        self,
        *,
        lookback_minutes: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, str]]:
        import shutil
        import sqlite3
        import tempfile
        from urllib.parse import urlparse

        lookback_seconds = max(
            10,
            int(
                lookback_minutes
                or getattr(self, "browser_history_lookback_minutes", 180)
                or 180
            ),
        ) * 60
        item_limit = max(
            1,
            int(limit or getattr(self, "usage_context_item_limit", 6) or 6),
        )
        cutoff_unix = time.time() - lookback_seconds
        chrome_epoch_offset = 11644473600
        cutoff_chrome_microseconds = int((cutoff_unix + chrome_epoch_offset) * 1_000_000)

        entries: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for browser_name, db_path in self._get_local_browser_history_candidates():
            temp_path = ""
            try:
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
                    temp_path = temp_file.name
                shutil.copy2(db_path, temp_path)
                connection = sqlite3.connect(temp_path)
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        """
                        SELECT url, title, last_visit_time
                        FROM urls
                        WHERE last_visit_time >= ?
                        ORDER BY last_visit_time DESC
                        LIMIT 80
                        """,
                        (cutoff_chrome_microseconds,),
                    )
                    for url, title, last_visit_time in cursor.fetchall():
                        normalized_url = str(url or "").strip()
                        if (
                            not normalized_url
                            or normalized_url in seen_urls
                            or not normalized_url.startswith(("http://", "https://"))
                        ):
                            continue
                        seen_urls.add(normalized_url)
                        parsed = urlparse(normalized_url)
                        domain = str(parsed.netloc or "").strip().lower()
                        if domain.startswith("www."):
                            domain = domain[4:]
                        title_text = self._clean_activity_site_label(title or "")
                        matched = self._match_known_activity_site(f"{title_text} {normalized_url}")
                        site_label = str(matched.get("site_label", "") or domain or browser_name).strip()
                        entries.append(
                            {
                                "browser": browser_name,
                                "site_label": site_label,
                                "page_title": title_text[:96].strip(),
                                "url": normalized_url[:240],
                                "domain": domain[:80],
                                "last_visit_time": str(last_visit_time or ""),
                            }
                        )
                        if len(entries) >= item_limit * 3:
                            break
                finally:
                    connection.close()
            except Exception as e:
                logger.debug(f"读取本地浏览器历史失败 {browser_name}: {e}")
            finally:
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
            if len(entries) >= item_limit * 3:
                break

        return entries[:item_limit]

    def _build_local_browser_history_lines(
        self,
        *,
        lookback_minutes: int | None = None,
        limit: int | None = None,
    ) -> list[str]:
        lines: list[str] = []
        for item in self._read_local_browser_history_entries(
            lookback_minutes=lookback_minutes,
            limit=limit,
        ):
            page_title = str(item.get("page_title", "") or "").strip()
            site_label = str(item.get("site_label", "") or "").strip()
            if page_title and site_label:
                lines.append(f"{site_label} 的《{page_title}》")
            elif page_title:
                lines.append(f"《{page_title}》")
            elif site_label:
                lines.append(site_label)
        return lines

    def _build_usage_context_prompt_bundle(
        self,
        *,
        scene: str,
        active_window_title: str,
        request_intent: dict[str, Any] | None = None,
        contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        decision = self._build_usage_context_decision(
            scene=scene,
            active_window_title=active_window_title,
            request_intent=request_intent,
            contexts=contexts,
        )
        if not decision.get("enabled"):
            return decision
        if not decision.get("used"):
            return {
                **decision,
                "prompt_block": "",
                "sections": {},
            }

        item_limit = max(
            1,
            int(getattr(self, "usage_context_item_limit", 6) or 6),
        )
        lookback_hours = max(
            1,
            int(getattr(self, "usage_context_lookback_hours", 6) or 6),
        )
        browser_lookback_minutes = max(
            10,
            int(getattr(self, "browser_history_lookback_minutes", 180) or 180),
        )
        sections: dict[str, list[str]] = {}

        if decision.get("include_activity"):
            live_snapshot = self._build_current_activity_snapshot()
            activity_lines = self._build_recent_activity_summary_lines(
                lookback_hours=lookback_hours,
                limit=item_limit,
            )
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
                    live_line = (
                        f"当前持续活动：{live_label}，已约 "
                        f"{self._format_usage_context_duration(live_snapshot.get('duration', 0))}"
                    )
                    activity_lines = [live_line] + [
                        line for line in activity_lines if live_label not in line
                    ]
            if activity_lines:
                sections["activity"] = activity_lines[:item_limit]
            scene_lines = self._build_recent_scene_summary_lines(
                lookback_hours=lookback_hours,
                limit=max(3, min(item_limit, 5)),
            )
            if scene_lines:
                sections["scene_summary"] = scene_lines
            app_lines = self._build_recent_app_summary_lines(
                lookback_hours=lookback_hours,
                limit=max(3, min(item_limit, 5)),
            )
            if app_lines:
                sections["app_summary"] = app_lines

        if decision.get("include_input") and bool(getattr(self, "enable_input_stats", False)):
            payload = self._build_input_stats_payload(
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
                sections["input"] = input_lines[:2]

        if decision.get("include_browser_activity"):
            browser_lines = self._build_recent_browsing_activity_lines(
                lookback_hours=lookback_hours,
                limit=item_limit,
            )
            if browser_lines:
                sections["browser_activity"] = browser_lines[:item_limit]

        if decision.get("include_local_browser_history"):
            browser_history_lines = self._build_local_browser_history_lines(
                lookback_minutes=browser_lookback_minutes,
                limit=item_limit,
            )
            if browser_history_lines:
                sections["browser_history"] = browser_history_lines[:item_limit]

        prompt_lines = [
            "可选旁证：下面这些是电脑使用情况的辅助线索，只在真的能帮助判断时再用。",
            "优先级始终是当前屏幕 > 最近对话 > 使用轨迹旁证。",
            "不要每次都逐条复述这些旁证，更不要让回复变成监控报告。",
        ]
        if sections.get("activity"):
            prompt_lines.append("最近活动轨迹：")
            prompt_lines.extend(f"- {line}" for line in sections["activity"])
        if sections.get("scene_summary"):
            prompt_lines.append("最近时间主要花在哪些场景：")
            prompt_lines.extend(f"- {line}" for line in sections["scene_summary"])
        if sections.get("app_summary"):
            prompt_lines.append("最近常用应用：")
            prompt_lines.extend(f"- {line}" for line in sections["app_summary"])
        if sections.get("input"):
            prompt_lines.append("本地输入活跃度：")
            prompt_lines.extend(f"- {line}" for line in sections["input"])
        if sections.get("browser_activity"):
            prompt_lines.append("从窗口轨迹推断的最近浏览内容：")
            prompt_lines.extend(f"- {line}" for line in sections["browser_activity"])
        if sections.get("browser_history"):
            prompt_lines.append("本地浏览器历史旁证：")
            prompt_lines.extend(f"- {line}" for line in sections["browser_history"])

        return {
            **decision,
            "sections": sections,
            "prompt_block": "\n".join(prompt_lines) if sections else "",
        }

    def _detect_task_wrap_up_signal(
        self,
        *,
        scene: str,
        recognition_text: str = "",
        contexts: list[str] | None = None,
        active_window_title: str = "",
    ) -> dict[str, Any]:
        profile = self._get_scene_behavior_profile(scene)
        if profile["category"] != "work":
            return {"detected": False}

        user_contexts = [
            str(item or "").strip()
            for item in (contexts or [])
            if str(item or "").strip().startswith("用户:")
        ]
        combined_text = " ".join(
            part
            for part in (
                " ".join(user_contexts[-2:]),
                str(recognition_text or "").strip(),
                str(active_window_title or "").strip(),
            )
            if part
        )
        normalized = self._normalize_record_text(combined_text)
        if not normalized:
            return {"detected": False}

        completion_keywords = (
            "完成",
            "搞定",
            "解决了",
            "成功",
            "通过",
            "已提交",
            "合并",
            "提交了",
            "发布成功",
            "导出完成",
            "done",
            "completed",
            "resolved",
            "merged",
            "passed",
            "success",
        )
        checkpoint_keywords = (
            "差不多",
            "先这样",
            "先收住",
            "告一段落",
            "到这里",
            "先放一下",
            "回头再",
            "先停这",
        )
        if any(keyword in normalized for keyword in completion_keywords):
            return {
                "detected": True,
                "kind": "completion",
                "guidance": "用户像是刚收住一段任务。如果真的像阶段性完成，可以轻轻确认这块算收好了，再顺一句下一步；不要写成长总结。",
            }
        if any(keyword in normalized for keyword in checkpoint_keywords):
            return {
                "detected": True,
                "kind": "checkpoint",
                "guidance": "用户像是在这里先收一下节奏。可以轻轻接住收尾感，但别立刻塞太多新的要求。",
            }
        return {"detected": False}

    def _should_skip_same_window_followup(
        self,
        task_id: str,
        *,
        active_window_title: str,
        scene: str,
    ) -> tuple[bool, str]:
        state = self._ensure_auto_screen_runtime_state(task_id)
        current_window_title = self._normalize_window_title(active_window_title)
        last_window_title = self._normalize_window_title(
            state.get("last_reply_window_title", "")
        )
        if not current_window_title or current_window_title.casefold() != last_window_title.casefold():
            return False, ""

        last_sent_at = float(state.get("last_sent_at", 0.0) or 0.0)
        if last_sent_at <= 0:
            return False, ""

        profile = self._get_scene_behavior_profile(scene)
        presence_mode = self._build_presence_mode_snapshot(
            task_id,
            scene=scene,
            change_snapshot={"changed": False, "scene": scene},
        )
        cooldown_seconds = int(
            (profile.get("same_window_cooldown", 0) or 0)
            * float(presence_mode.get("cooldown_scale", 1.0) or 1.0)
        )
        elapsed = time.time() - last_sent_at
        if elapsed >= cooldown_seconds:
            return False, ""

        reason = (
            f"同一窗口《{current_window_title}》仍在冷却中，距离上次主动消息仅 {int(max(0, elapsed))} 秒；"
            f"当前更像{presence_mode.get('label', '当前节奏')}"
        )
        state["last_skip_reason"] = reason
        return True, reason

    def _truncate_preview_text(self, text: str, limit: int = 120) -> str:
        preview = str(text or "").strip().replace("\r", " ").replace("\n", " ")
        if len(preview) <= limit:
            return preview
        return preview[: max(0, limit - 1)] + "…"

    def _contains_rest_cue(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        keywords = (
            "休息",
            "睡觉",
            "去睡",
            "早点睡",
            "快去睡",
            "先睡",
            "熬夜",
            "别熬夜",
            "关机睡",
            "关机吧",
            "凌晨",
            "太晚了",
        )
        return any(keyword in normalized for keyword in keywords)

    def _strip_repeated_companion_opening(self, text: str, *, has_recent_context: bool) -> str:
        import re

        cleaned = str(text or "").strip()
        cleaned = re.sub(r"^(笨蛋|傻瓜|喂|欸|哎呀|哼)[，,、\s]+", "", cleaned, count=1)
        cleaned = re.sub(
            r"^(原来(?:你)?在)(?=\S)",
            "",
            cleaned,
            count=1,
        )
        cleaned = re.sub(
            r"^(原来(?:你)?刚刚在)(?=\S)",
            "",
            cleaned,
            count=1,
        )
        cleaned = re.sub(
            r"^(原来是你在)(?=\S)",
            "",
            cleaned,
            count=1,
        )
        cleaned = re.sub(r"^(又在|还在|现在在)看", "在看", cleaned, count=1)
        if not has_recent_context:
            return cleaned.strip()
        return cleaned.strip()

    def _strip_rest_cue_sentences(self, text: str) -> str:
        import re

        original = str(text or "").strip()
        if not original:
            return ""

        parts = re.split(r"(?<=[。！？!?])\s*|\n+", original)
        kept_parts = [
            part.strip()
            for part in parts
            if part.strip() and not self._contains_rest_cue(part)
        ]
        if not kept_parts:
            return original
        cleaned = " ".join(kept_parts).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned or original

    def _has_recent_rest_cue(
        self,
        contexts: list[str],
        *,
        task_id: str,
    ) -> bool:
        assistant_contexts = [
            str(item or "").strip()
            for item in (contexts or [])
            if str(item or "").strip().startswith("助手:")
        ]
        recent_assistant_mentions = sum(
            1 for item in assistant_contexts[-3:] if self._contains_rest_cue(item)
        )
        if recent_assistant_mentions > 0:
            return True

        state = self._ensure_auto_screen_runtime_state(task_id)
        last_preview = str(state.get("last_reply_preview", "") or "").strip()
        last_sent_at = float(state.get("last_sent_at", 0.0) or 0.0)
        if (
            last_preview
            and self._contains_rest_cue(last_preview)
            and last_sent_at > 0
            and (time.time() - last_sent_at) < self.REST_CUE_REPLY_COOLDOWN_SECONDS
        ):
            return True
        return False

    def _remember_screen_analysis_trace(self, trace: dict[str, Any] | None) -> None:
        if not isinstance(trace, dict):
            return

        cleaned = dict(trace)
        cleaned.setdefault("timestamp", datetime.datetime.now().isoformat())
        for key in (
            "task_id",
            "trigger_reason",
            "media_kind",
            "analysis_material_kind",
            "sampling_strategy",
            "recognition_summary",
            "reply_preview",
            "active_window_title",
            "scene",
            "status",
        ):
            cleaned[key] = str(cleaned.get(key, "") or "").strip()

        cleaned["stored_as_observation"] = bool(cleaned.get("stored_as_observation", False))
        cleaned["stored_in_diary"] = bool(cleaned.get("stored_in_diary", False))
        cleaned["memory_hints"] = list(cleaned.get("memory_hints", []) or [])[:4]
        cleaned["frame_labels"] = list(cleaned.get("frame_labels", []) or [])[:4]
        cleaned["frame_count"] = int(cleaned.get("frame_count", 0) or 0)
        cleaned["used_full_video"] = bool(cleaned.get("used_full_video", False))

        self.screen_analysis_traces.append(cleaned)
        if len(self.screen_analysis_traces) > self.SCREEN_TRACE_LIMIT:
            self.screen_analysis_traces = self.screen_analysis_traces[-self.SCREEN_TRACE_LIMIT :]

    def _get_recent_screen_analysis_traces(self, limit: int = 8) -> list[dict[str, Any]]:
        traces = list(getattr(self, "screen_analysis_traces", []) or [])
        if limit > 0:
            traces = traces[-limit:]
        return list(reversed(traces))

    @staticmethod
    def _format_runtime_timestamp(timestamp: float | int | None) -> str:
        try:
            value = float(timestamp or 0)
        except Exception:
            value = 0.0
        if value <= 0:
            return "未记录"
        return datetime.datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    def _resolve_webui_access_url(self) -> str:
        if not self.webui_enabled:
            return "未启用"
        if not self.web_server or not getattr(self.web_server, "_started", False):
            return "已启用但未运行"

        port = getattr(self.web_server, "port", self.webui_port)
        host = self.webui_host
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return f"http://{host}:{port}"

    async def _build_kpi_doctor_report(self, event: AstrMessageEvent) -> str:
        self._ensure_runtime_state()

        current_check_interval, current_probability = self._get_current_preset_params()
        active_task_ids = list(self.auto_tasks.keys())
        focus_task_id = (
            self.AUTO_TASK_ID
            if self.AUTO_TASK_ID in self.auto_tasks
            else (active_task_ids[0] if active_task_ids else self.AUTO_TASK_ID)
        )
        auto_state = self._ensure_auto_screen_runtime_state(focus_task_id)
        current_change_snapshot = self._build_auto_screen_change_snapshot(
            focus_task_id,
            update_state=False,
        )
        active_window_title = (
            current_change_snapshot.get("active_window_title")
            or auto_state.get("last_seen_window_title")
            or "未知"
        )
        if auto_state.get("last_change_at"):
            latest_change_reason = auto_state.get("last_change_reason") or "最近有变化"
        elif self.is_running:
            latest_change_reason = (
                "当前窗口有变化"
                if current_change_snapshot.get("changed")
                else "最近未检测到明显变化"
            )
        else:
            latest_change_reason = "自动观察未运行，当前仅展示前台窗口"

        provider = self.context.get_using_provider()
        umo = str(getattr(event, "unified_msg_origin", "") or "").strip()
        provider_id = await self._get_current_chat_provider_id(umo=umo)
        provider_info = self._resolve_provider_runtime_info(provider_id=provider_id, provider=provider)
        model_label = provider_info.get("model") or getattr(provider, "model_name", "") or getattr(provider, "model", "") or "未知"
        provider_label = provider_info.get("provider_id") or getattr(provider, "id", "") or "未识别"

        env_ok, env_msg = self._check_env(check_mic=False)
        mode = "录屏" if self._use_screen_recording_mode() else "截图"
        ffmpeg_label = "未使用"
        encoder_label = "未使用"
        if self._use_screen_recording_mode():
            ffmpeg_path = self._get_ffmpeg_path()
            ffmpeg_label = ffmpeg_path if ffmpeg_path else "未检测到 ffmpeg"
            encoder_label = self._get_recording_video_encoder()

        diary_status = "开启" if self.enable_diary else "关闭"
        last_diary_label = (
            self.last_diary_date.strftime("%Y-%m-%d")
            if isinstance(self.last_diary_date, datetime.date)
            else "未生成"
        )
        target = self._resolve_proactive_target(event) or "未配置"
        webui_url = self._resolve_webui_access_url()
        custom_task_count = max(0, len(active_task_ids) - (1 if self.AUTO_TASK_ID in active_task_ids else 0))
        recent_user_activity_at = self._get_recent_user_activity_at(event)

        lines = [
            "屏幕伙伴自检",
            f"运行状态：{'已启用' if self.enabled else '未启用'} / 当前状态 {self.state} / 自动观察 {'运行中' if self.is_running else '未运行'}",
            f"任务概览：主任务 {focus_task_id} / 运行中 {len(active_task_ids)} 个 / 自定义任务 {custom_task_count} 个",
            f"识屏模式：{mode} / 间隔 {current_check_interval} 秒 / 基础概率 {current_probability}%",
            f"变化感知：当前窗口《{active_window_title}》 / 最近变化 {latest_change_reason} / 最近变化时间 {self._format_runtime_timestamp(auto_state.get('last_change_at'))}",
            f"最近判定：{auto_state.get('last_trigger_reason') or '暂未判定'} / 生效概率 {auto_state.get('last_effective_probability', 0)}% / 随机数 {auto_state.get('last_trigger_roll') if auto_state.get('last_trigger_roll') is not None else '未记录'}",
            f"最近手动消息：{self._format_runtime_timestamp(recent_user_activity_at)}",
            f"最近主动消息：{self._format_runtime_timestamp(auto_state.get('last_sent_at'))} / 预览 {auto_state.get('last_reply_preview') or '暂无'}",
            f"相似去重：{auto_state.get('last_skip_reason') or '最近没有命中去重'}",
            f"主动目标：{target}",
            f"模型提供方：{provider_label} / 模型 {model_label}",
            f"视觉链路：外部视觉 {'开启' if self._get_runtime_flag('use_external_vision') else '关闭'} / 视频直连兜底 {'开启' if self._get_runtime_flag('allow_unsafe_video_direct_fallback') else '关闭'}",
            f"录屏参数：{self._get_recording_duration_seconds()} 秒 @ {self._get_recording_fps():.2f} fps / 编码器 {encoder_label} / ffmpeg {ffmpeg_label}",
            f"观察与日记：观察 {len(self.observations)} 条 / 待写日记 {len(self.diary_entries)} 条 / 日记 {diary_status} / 计划时间 {self.diary_time} / 最近日记 {last_diary_label}",
            f"WebUI：{webui_url}",
            "学习开关："
            + " / ".join(
                f"{label}{'开' if enabled else '关'}"
                for _, label, enabled in self._get_learning_switches()
            ),
            "最近学习："
            + " / ".join(
                f"{label}{str((self._get_learning_runtime_events().get(key, {}) or {}).get('status', '暂无') or '暂无')}"
                for key, label, _ in self._get_learning_switches()
                if key != "all"
            ),
            f"环境检查：{'正常' if env_ok else env_msg}",
        ]
        suggestions = self._build_status_suggestions(
            env_ok=env_ok,
            active_task_ids=active_task_ids,
        )
        if suggestions:
            lines.append("建议下一步：")
            lines.extend(f"- {item}" for item in suggestions[:2])
        return "\n".join(lines)

    def _adjust_interaction_frequency(self, user_response):
        """根据用户回应调整互动频率。"""
        # 简单估算参与度：结合回复长度与内容变化
        response_length = len(user_response)
        
        if response_length > 50:
            engagement = min(10, self.user_engagement + 1)
        elif response_length < 10:
            engagement = max(1, self.user_engagement - 1)
        else:
            engagement = self.user_engagement
        
        self.engagement_history.append(engagement)
        if len(self.engagement_history) > 10:
            self.engagement_history.pop(0)
        
        # 计算平均参与度
        avg_engagement = sum(self.engagement_history) / len(self.engagement_history)
        self.user_engagement = int(avg_engagement)
        
        # 根据参与度调整互动频率，参与度越高频率越高
        self.interaction_frequency = max(1, min(10, 5 + (self.user_engagement - 5) * 0.5))
        logger.info(f"用户参与度: {self.user_engagement}, 互动频率: {self.interaction_frequency}")
