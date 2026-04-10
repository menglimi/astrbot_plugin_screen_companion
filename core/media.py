# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import base64
import datetime
import io
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from types import SimpleNamespace
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import BaseMessageComponent, Image, Plain

from ..web_server import WebServer
from .app_descriptions import describe_window_activity, infer_scene_from_window_title

class ScreenCompanionMediaMixin:
    def _parse_user_preferences(self):
        """解析用户偏好设置。"""
        self.parsed_preferences = {}
        if not self.user_preferences:
            return

        lines = self.user_preferences.strip().split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue

            scene, preference = parts
            self.parsed_preferences[scene] = preference

        logger.info("用户偏好设置解析完成")

    def _load_learning_data(self):
        """加载学习数据。"""
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
        self._ensure_runtime_state()
        webui_lock = getattr(self, "_webui_lock", None)
        if webui_lock is None:
            self._webui_lock = asyncio.Lock()
            webui_lock = self._webui_lock

        async with webui_lock:
            try:
                if self.web_server:
                    logger.info("检测到 Web UI 服务器已存在，正在停止旧实例...")
                    await self.web_server.stop()
                    self.web_server = None
                    # 增加延迟时间，确保端口完全释放
                    await asyncio.sleep(1.0)

                self.web_server = WebServer(self, host=self.webui_host, port=self.webui_port)
                success = await self.web_server.start()
                if not success:
                    self.web_server = None
                    logger.error(
                        f"WebUI 启动失败，原因: 无法绑定 {self.webui_host}:{self.webui_port}"
                    )
            except Exception as e:
                self.web_server = None
                logger.error(f"启动 Web UI 时出错: {e}")

    async def _stop_webui(self):
        """停止 Web UI 服务器"""
        self._ensure_runtime_state()
        webui_lock = getattr(self, "_webui_lock", None)
        if webui_lock is None:
            self._webui_lock = asyncio.Lock()
            webui_lock = self._webui_lock

        async with webui_lock:
            if self.web_server:
                try:
                    await self.web_server.stop()
                except Exception as e:
                    logger.error(f"停止 Web UI 时出错: {e}")
                finally:
                    self.web_server = None

    def _save_learning_data(self):
        """保存学习数据。"""
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
        """加载用户纠正数据。"""
        try:
            import json
            import os
            corrections_file = getattr(self, "corrections_file", "")
            if not corrections_file:
                corrections_file = os.path.join(self.learning_storage, "corrections.json")
                self.corrections_file = corrections_file
            if os.path.exists(corrections_file):
                with open(corrections_file, "r", encoding="utf-8") as f:
                    self.corrections = json.load(f)
                logger.info("纠正数据加载成功")
        except Exception as e:
            logger.error(f"加载纠正数据失败: {e}")
            self.corrections = {}

    def _save_corrections(self):
        """保存用户纠正数据。"""
        try:
            import json
            import os
            corrections_file = getattr(self, "corrections_file", "")
            if not corrections_file:
                corrections_file = os.path.join(self.learning_storage, "corrections.json")
                self.corrections_file = corrections_file
            with open(corrections_file, "w", encoding="utf-8") as f:
                json.dump(self.corrections, f, ensure_ascii=False, indent=2)
            logger.info("纠正数据保存成功")
        except Exception as e:
            logger.error(f"保存纠正数据失败: {e}")

    def _polish_response_text(
        self,
        response_text,
        scene,
        *,
        contexts: list[str] | None = None,
        allow_rest_hint: bool = False,
        task_id: str = "",
    ):
        """只做轻量清理，不主动塑造固定回复风格。"""
        response_text = str(response_text or "").strip()
        response_text = self._strip_response_markdown_artifacts(response_text)
        recent_contexts = list(contexts or [])
        has_recent_context = bool(recent_contexts)

        response_text = self._strip_repeated_companion_opening(
            response_text,
            has_recent_context=has_recent_context,
        )

        if (
            not allow_rest_hint
            and self._contains_rest_cue(response_text)
            and self._has_recent_rest_cue(recent_contexts, task_id=task_id)
        ):
            response_text = self._strip_rest_cue_sentences(response_text)

        return response_text.strip()

    def _strip_response_markdown_artifacts(self, text: str) -> str:
        import re

        cleaned = str(text or "").strip()
        if not cleaned:
            return ""

        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned, flags=re.S)
        cleaned = re.sub(r"__(.*?)__", r"\1", cleaned, flags=re.S)
        cleaned = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", cleaned, flags=re.M)
        cleaned = re.sub(r"^[ \t]*[-*][ \t]+", "", cleaned, flags=re.M)
        cleaned = re.sub(r"^[ \t]*>[ \t]*", "", cleaned, flags=re.M)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    @staticmethod
    def _normalize_screen_fact_text(text: str, limit: int = 72) -> str:
        import re

        normalized = str(text or "").strip()
        if not normalized:
            return ""

        normalized = normalized.replace("\r", "\n")
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.strip(" -:：;；,.，。")
        if len(normalized) > limit:
            normalized = normalized[: limit - 3].rstrip("，。；;,. ") + "..."
        return normalized

    def _extract_screen_fact_lines(
        self,
        recognition_text: str,
        *,
        limit: int = 4,
    ) -> list[str]:
        import re

        text = str(recognition_text or "").strip()
        if not text:
            return []

        raw_segments: list[str] = []
        for line in text.replace("\r", "\n").split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            raw_segments.extend(re.split(r"[；;]", stripped))

        filtered: list[str] = []
        seen: set[str] = set()
        skip_markers = (
            "建议",
            "可以先",
            "可先",
            "下一步",
            "提醒",
            "注意",
            "优先",
            "最好",
            "不妨",
            "也许",
            "可能",
        )
        prefix_pattern = re.compile(r"^[\-\*\d\.\)\(（）：:、\s]+")

        for segment in raw_segments:
            candidate = prefix_pattern.sub("", str(segment or "").strip())
            candidate = self._normalize_screen_fact_text(candidate)
            if not candidate:
                continue
            if any(marker in candidate for marker in skip_markers):
                continue
            signature = candidate.casefold()
            if signature in seen:
                continue
            seen.add(signature)
            filtered.append(candidate)
            if len(filtered) >= max(1, int(limit or 1)):
                break

        return filtered

    def _build_screen_fact_digest(
        self,
        *,
        scene: str,
        active_window_title: str,
        recognition_text: str,
        media_kind: str,
        latest_window_title: str = "",
        clip_active_window_title: str = "",
    ) -> dict[str, Any]:
        normalized_scene = str(scene or "").strip()
        normalized_window = self._normalize_window_title(active_window_title)
        normalized_latest_window = self._normalize_window_title(latest_window_title)
        normalized_clip_window = self._normalize_window_title(clip_active_window_title)
        fact_lines = self._extract_screen_fact_lines(recognition_text)
        activity_hint = describe_window_activity(normalized_window, normalized_scene)
        activity_scene = str(activity_hint.get("scene", "") or "").strip()
        app_name = str(activity_hint.get("app_name", "") or "").strip()
        display_title = str(activity_hint.get("display_title", "") or "").strip()
        activity_description = str(activity_hint.get("description", "") or "").strip()

        summary_lines: list[str] = []
        effective_scene = normalized_scene or activity_scene
        if effective_scene and effective_scene != "未知":
            summary_lines.append(f"场景：{effective_scene}")
        if app_name:
            summary_lines.append(f"应用：{app_name}")
        if normalized_window:
            summary_lines.append(f"当前窗口：{normalized_window}")
        if display_title:
            summary_lines.append(f"标题：{display_title}")
        if activity_description:
            summary_lines.append(f"活动：{activity_description}")
        if (
            str(media_kind or "").strip().lower() == "video"
            and normalized_latest_window
            and normalized_latest_window.casefold() != normalized_window.casefold()
        ):
            summary_lines.append(f"最新窗口：{normalized_latest_window}")
        elif (
            str(media_kind or "").strip().lower() == "video"
            and normalized_clip_window
            and normalized_clip_window.casefold() != normalized_window.casefold()
        ):
            summary_lines.append(f"录屏起点窗口：{normalized_clip_window}")

        for fact in fact_lines:
            summary_lines.append(f"观察：{fact}")

        summary_lines = summary_lines[:6]
        summary = "；".join(summary_lines)
        prompt_block = ""
        if summary_lines:
            prompt_block = "可直接依赖的状态摘要：\n" + "\n".join(
                f"- {line}" for line in summary_lines
            )

        return {
            "summary": summary,
            "summary_lines": summary_lines,
            "fact_lines": fact_lines,
            "prompt_block": prompt_block,
            "app_name": app_name,
            "display_title": display_title,
            "activity_description": activity_description,
            "scene": effective_scene,
        }

    def _build_grounded_screen_reply_guide(
        self,
        *,
        fact_digest: dict[str, Any] | None,
        custom_prompt: str,
        context_count: int,
    ) -> str:
        fact_lines = list((fact_digest or {}).get("summary_lines", []) or [])
        guide_lines = [
            "只根据当前画面与上文里能确认的事实回答。",
            "如果看不清或证据不够，直接承认不确定，不要硬猜。",
            "不要编造未看到的具体结果、文档内容、按钮状态、聊天对象或任务结论。",
        ]
        if fact_lines:
            guide_lines.append("回答时可以引用当前画面里的事实，但不要为了像在识屏而机械复述。")
        else:
            guide_lines.append("当前事实不足时，优先澄清或请用户切到相关页面。")
        if custom_prompt:
            guide_lines.append("用户有明确问题时，先贴着问题回答。")
        if context_count > 0:
            guide_lines.append("参考最近对话保持连贯，不要把上一条换个说法重讲。")
        return "\n".join(guide_lines)

    def _normalize_user_request_objective(self, user_request_text: str) -> str:
        import re

        text = self._truncate_preview_text(user_request_text, limit=160)
        if not text:
            return ""

        normalized = str(text or "").strip()
        normalized = re.sub(
            r"^(?:请|麻烦|拜托|劳驾|帮忙|能不能|可以|可不可以|能否|想请你)?\s*",
            "",
            normalized,
        )
        normalized = re.sub(
            (
                r"^(?:你|你帮我|帮我|麻烦你|麻烦帮我|帮忙|帮忙给我|你帮忙)?\s*"
                r"(?:看看|看下|看一下|瞅瞅|分析一下|分析下|分析|确认一下|确认下|确认|"
                r"判断一下|判断下|判断|查一下|查下|查查看|找一下|找找|定位一下|定位下|"
                r"说一下|说说|讲一下|讲讲|告诉我|帮我看看)?\s*"
            ),
            "",
            normalized,
        )
        normalized = re.sub(
            r"^(?:我想知道|我想确认|我想看|我想问|我在问|我想让你看|你觉得)\s*",
            "",
            normalized,
        )
        normalized = normalized.strip("，。！？!?、:：;； ")
        return normalized

    def _extract_request_focus_clauses(
        self,
        user_request_text: str,
        *,
        limit: int = 4,
    ) -> list[str]:
        import re

        objective = self._normalize_user_request_objective(user_request_text)
        if not objective:
            return []

        candidates: list[str] = []
        quote_patterns = (
            r"「([^」]{2,40})」",
            r"“([^”]{2,40})”",
            r"\"([^\"]{2,40})\"",
            r"'([^']{2,40})'",
        )
        for pattern in quote_patterns:
            for match in re.findall(pattern, objective):
                value = self._normalize_screen_fact_text(match)
                if value:
                    candidates.append(value)

        segments = re.split(r"[，。！？!?；;\n]", objective)
        clause_cleanup_pattern = re.compile(
            (
                r"^(?:这个|那个|这|那|目前|现在|刚刚|刚才|电脑上|屏幕上|当前|这里|那里)?\s*"
                r"(?:的)?\s*"
            )
        )
        suffix_cleanup_pattern = re.compile(
            r"(?:在哪|在哪里|在哪儿|是啥|是什么|什么意思|怎么回事|怎么样|如何|怎么办|怎么做|有没有|是否|是不是|出来没|看到了吗|能看到吗)$"
        )
        for segment in segments:
            cleaned = self._normalize_screen_fact_text(segment)
            if not cleaned:
                continue
            cleaned = clause_cleanup_pattern.sub("", cleaned).strip()
            cleaned = suffix_cleanup_pattern.sub("", cleaned).strip("，。！？!?、:：;； ")
            if cleaned and len(cleaned) >= 2:
                candidates.append(cleaned)

        fallback = self._normalize_screen_fact_text(objective)
        if fallback:
            candidates.append(fallback)

        normalized_candidates: list[str] = []
        seen: set[str] = set()
        stop_values = {
            "看看",
            "看下",
            "看一下",
            "分析",
            "确认",
            "判断",
            "查一下",
            "查下",
            "找一下",
            "找找",
            "说一下",
            "说说",
            "讲一下",
            "讲讲",
        }
        for candidate in candidates:
            cleaned = self._normalize_screen_fact_text(candidate)
            if not cleaned or cleaned in stop_values:
                continue
            key = cleaned.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized_candidates.append(cleaned)

        normalized_candidates.sort(key=len, reverse=True)
        return normalized_candidates[: max(1, int(limit or 1))]

    def _classify_user_request_intent(self, user_request_text: str) -> str:
        text = self._normalize_user_request_objective(user_request_text).casefold()
        if not text:
            return "observe"

        if any(marker in text for marker in ("在哪", "在哪里", "在哪儿", "哪个", "哪一个", "位置", "地方")):
            return "locate"
        if any(marker in text for marker in ("怎么做", "怎么办", "下一步", "咋弄", "卡在哪", "卡住了")):
            return "guidance"
        if any(marker in text for marker in ("什么意思", "怎么回事", "为什么", "为啥", "是啥", "是什么")):
            return "explain"
        if any(marker in text for marker in ("有没有", "是否", "是不是", "出来没", "看到没", "看到了吗", "能看到吗", "确认")):
            return "verify"
        return "observe"

    def _evaluate_user_request_intent(
        self,
        *,
        user_request_text: str,
        fact_digest: dict[str, Any] | None,
        recognition_text: str,
        contexts: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_request = self._truncate_preview_text(user_request_text, limit=160)
        objective = self._normalize_user_request_objective(normalized_request)
        intent_type = self._classify_user_request_intent(normalized_request)
        focus_clauses = self._extract_request_focus_clauses(normalized_request)

        visible_parts: list[str] = []
        for item in list((fact_digest or {}).get("summary_lines", []) or []):
            text = str(item or "").strip()
            if text:
                visible_parts.append(text)
        recognition_preview = self._truncate_preview_text(recognition_text, limit=240)
        if recognition_preview:
            visible_parts.append(recognition_preview)
        visible_text = "\n".join(visible_parts).casefold()

        matched_clauses = [
            clause
            for clause in focus_clauses
            if len(str(clause or "").strip()) >= 2
            and str(clause or "").casefold() in visible_text
        ]

        objective_lower = objective.casefold()
        has_reference_pronoun = any(
            marker in objective_lower
            for marker in ("这个", "那个", "这", "那", "这里", "那里", "它", "其")
        )
        screen_looks_transitional = any(
            marker in visible_text
            for marker in (
                "启动",
                "连接",
                "加载",
                "登陆",
                "登录",
                "欢迎",
                "主页",
                "首页",
                "请稍候",
                "等待",
                "loading",
                "launch",
                "connect",
                "starting",
            )
        )

        action = "answer"
        reason = "当前画面大概率足以支撑直接回答。"
        if not normalized_request:
            action = "answer"
            reason = "没有额外用户目标，按常规识屏回答。"
        elif focus_clauses and not matched_clauses:
            if intent_type in {"locate", "verify"} or has_reference_pronoun:
                action = "clarify_or_switch"
                reason = "用户要确认的目标没有出现在当前画面里。"
            elif screen_looks_transitional:
                action = "clarify_or_switch"
                reason = "当前画面更像过渡状态，和用户要找的目标可能不是同一页。"
            else:
                action = "answer_with_uncertainty"
                reason = "目标没有明显出现在屏幕里，回答时需要先承认不确定。"
        elif not focus_clauses and intent_type in {"locate", "verify"} and screen_looks_transitional:
            action = "clarify_or_switch"
            reason = "用户在找具体位置/结果，但当前画面仍是过渡状态。"

        recent_user_reference = ""
        for item in reversed(list(contexts or [])):
            text = str(item or "").strip()
            if not text.startswith("用户:"):
                continue
            content = text.split(":", 1)[-1].strip()
            if not content or content == normalized_request:
                continue
            recent_user_reference = self._truncate_preview_text(content, limit=100)
            break

        return {
            "request_text": normalized_request,
            "objective": objective or normalized_request,
            "intent_type": intent_type,
            "focus_clauses": focus_clauses,
            "matched_clauses": matched_clauses,
            "action": action,
            "reason": reason,
            "recent_user_reference": recent_user_reference,
        }

    def _build_intent_first_screen_reply_guide(
        self,
        *,
        request_intent: dict[str, Any] | None,
        context_count: int,
    ) -> str:
        intent = dict(request_intent or {})
        request_text = str(intent.get("request_text", "") or "").strip()
        if not request_text:
            return ""

        objective = str(intent.get("objective", "") or request_text).strip()
        action = str(intent.get("action", "answer") or "answer").strip()
        reason = str(intent.get("reason", "") or "").strip()
        focus_clauses = [
            str(item or "").strip()
            for item in list(intent.get("focus_clauses", []) or [])
            if str(item or "").strip()
        ]
        matched_clauses = [
            str(item or "").strip()
            for item in list(intent.get("matched_clauses", []) or [])
            if str(item or "").strip()
        ]
        recent_user_reference = str(intent.get("recent_user_reference", "") or "").strip()

        guide_lines = [
            f"当前这条用户消息：{request_text}",
            f"提炼出的用户目标：{objective}",
            "决策顺序：先判断用户现在想确认什么，再判断当前画面能不能直接回答。",
        ]
        if focus_clauses:
            guide_lines.append("目标线索：" + "、".join(focus_clauses[:3]))
        if matched_clauses:
            guide_lines.append("当前画面已覆盖的线索：" + "、".join(matched_clauses[:3]))
        if reason:
            guide_lines.append(f"覆盖判断：{reason}")
        if recent_user_reference:
            guide_lines.append(f"最近用户上文：{recent_user_reference}")
        if action == "clarify_or_switch":
            guide_lines.append(
                "回复动作：这次先不要抢着解读当前界面，更不要把启动页、连接页、首页或过渡画面当成最终答案。"
            )
            guide_lines.append(
                "优先直接说明你还没在当前屏幕里看到用户要找的目标，然后追问它在哪个窗口/页面，或请用户切到那里。"
            )
        elif action == "answer_with_uncertainty":
            guide_lines.append(
                "回复动作：可以结合当前画面回答，但必须先交代你还不能完全确认，不要把猜测说成已经看到。"
            )
        else:
            guide_lines.append(
                "回复动作：当前画面足以支撑回答时，再根据屏幕给结论，不要多做无关播报。"
            )
        if context_count > 0:
            guide_lines.append("结合最近对话处理“这个”“那个”“刚刚那个”之类的省略指代。")
        return "\n".join(guide_lines)

    def _soften_screen_reply_phrasing(self, text: str) -> str:
        softened = str(text or "").strip()
        if not softened:
            return ""

        replacements = (
            ("根据当前屏幕内容，", ""),
            ("根据当前画面，", ""),
            ("从当前屏幕来看，", ""),
            ("从当前画面来看，", ""),
            ("从画面看，", ""),
            ("结合当前画面，", ""),
            ("建议你可以", "你可以"),
            ("建议你先", "你可以先"),
            ("建议你", "你可以"),
            ("建议最后", "最后"),
            ("建议先", "可以先"),
            ("建议待会儿", "待会儿可以"),
            ("建议还是", "还是"),
        )
        for source, target in replacements:
            softened = softened.replace(source, target)
        return softened.strip()

    def _trim_overstyled_screen_sentences(self, text: str) -> str:
        import re

        original = str(text or "").strip()
        if not original:
            return ""

        cliche_markers = (
            "手感依旧在线",
            "简直是大优局",
            "稳稳拿下了",
            "节奏完全在你手里",
            "妥妥的第一梯队",
            "手感应该热得发烫",
            "背景里这音乐",
            "继续保持这种压制力就行",
            "我也正好陪你看看这把的评分战绩",
        )
        pieces = re.split(r"(?<=[。！？!?])\s*|\n+", original)
        kept_pieces = []
        for piece in pieces:
            sentence = piece.strip()
            if not sentence:
                continue
            if any(marker in sentence for marker in cliche_markers):
                continue
            kept_pieces.append(sentence)

        if not kept_pieces:
            return original

        cleaned = " ".join(kept_pieces).strip()
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned or original

    def _learn_from_correction(self, original_response, corrected_response):
        """从用户纠正中学习。"""
        if not self._get_runtime_flag("enable_learning", True):
            self._remember_learning_runtime_event(
                "correction",
                "skipped",
                "总学习开关已关闭",
            )
            return False
        if not self._get_runtime_flag("enable_manual_correction_learning", True):
            self._remember_learning_runtime_event(
                "correction",
                "skipped",
                "手动纠正学习已关闭",
            )
            return False

        # 记录纠正信息
        import uuid
        import datetime
        scene = self._infer_correction_scene(original_response, corrected_response)
        preference_hint = self._extract_correction_preference_hint(
            original_response,
            corrected_response,
        )
        correction_id = str(uuid.uuid4())
        self.corrections[correction_id] = {
            "original": original_response,
            "corrected": corrected_response,
            "timestamp": datetime.datetime.now().isoformat(),
            "scene": scene,
            "preference_hint": preference_hint,
        }
        
        # 分析纠正内容，提取关键信息
        self._analyze_correction_content(original_response, corrected_response)

        if preference_hint:
            self._update_learning_data(
                scene or "通用",
                preference_hint,
                feedback_id=correction_id,
                source="manual_correction",
                original_text=corrected_response,
            )
        
        # 保存纠正数据
        self._save_corrections()
        logger.info("已记录一条用户纠正数据")
        self._remember_learning_runtime_event(
            "correction",
            "learned",
            preference_hint or "已记录一条手动纠正",
        )
        return True

    @staticmethod
    def _normalize_learning_feedback(text: str, limit: int = 80) -> str:
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return ""
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip("，,；;。.!！?？ ") + "..."

    def _infer_correction_scene(self, original_response, corrected_response) -> str:
        combined = f"{original_response or ''} {corrected_response or ''}"
        scene_keywords = [
            "编程",
            "设计",
            "办公",
            "游戏",
            "视频",
            "阅读",
            "音乐",
            "社交",
            "浏览",
            "学习",
        ]
        for scene in scene_keywords:
            if scene in combined:
                return scene
        return "通用"

    def _extract_correction_preference_hint(self, original_response, corrected_response) -> str:
        corrected_text = self._normalize_learning_feedback(corrected_response, limit=72)
        original_text = self._normalize_learning_feedback(original_response, limit=48)
        if not corrected_text:
            return ""

        hints = []
        keyword_groups = [
            (
                ("具体", "下一步", "步骤", "操作", "可执行", "先"),
                "更偏好具体、可执行、能直接落地的建议。",
            ),
            (
                ("自然", "口语", "像朋友", "别太官方", "不要机械", "少播报", "少说教"),
                "更偏好自然、低播报感、少模板味的表达。",
            ),
            (
                ("简短", "简洁", "短一点", "别太长", "少一点"),
                "更偏好简短克制的回复。",
            ),
            (
                ("温柔", "陪伴", "别打断", "不打断", "轻一点"),
                "希望语气更轻、更有陪伴感。",
            ),
        ]
        for keywords, hint in keyword_groups:
            if any(keyword in corrected_text for keyword in keywords):
                hints.append(hint)

        deduped_hints = []
        seen = set()
        for hint in hints:
            if hint in seen:
                continue
            seen.add(hint)
            deduped_hints.append(hint)

        if deduped_hints:
            return " ".join(deduped_hints)

        if corrected_text != original_text:
            return f"用户更认可类似“{corrected_text}”这样的表达。"
        return ""

    def _get_recent_correction_guidance(self, scene: str = "", limit: int = 2) -> list[str]:
        corrections = getattr(self, "corrections", {}) or {}
        if not isinstance(corrections, dict) or not corrections:
            return []

        normalized_scene = self._normalize_scene_label(scene) if scene else ""
        guidance = []
        seen = set()
        ranked_items = sorted(
            corrections.values(),
            key=lambda item: str((item or {}).get("timestamp", "") or ""),
            reverse=True,
        )
        for item in ranked_items:
            if not isinstance(item, dict):
                continue
            item_scene = self._normalize_scene_label(str(item.get("scene", "") or ""))
            if normalized_scene and item_scene and item_scene not in {normalized_scene, "通用"}:
                continue

            hint = self._normalize_learning_feedback(item.get("preference_hint", ""), limit=90)
            if not hint:
                corrected_text = self._normalize_learning_feedback(item.get("corrected", ""), limit=60)
                if corrected_text:
                    hint = f"用户最近更认可类似“{corrected_text}”这样的表达。"
            if not hint:
                continue

            key = self._normalize_record_text(hint)
            if not key or key in seen:
                continue
            seen.add(key)
            guidance.append(hint)
            if len(guidance) >= limit:
                break
        return guidance

    @staticmethod
    def _score_user_feedback_message(message_text: str) -> int:
        text = str(message_text or "").strip()
        if not text:
            return 0

        score = 0
        assistant_markers = (
            "你",
            "你这",
            "你刚才",
            "你刚刚",
            "回复",
            "语气",
            "说话",
            "称呼",
            "开场",
        )
        style_markers = (
            "别这么",
            "不要这么",
            "别再",
            "不要再",
            "别老",
            "不要老",
            "太啰嗦",
            "太官方",
            "太机械",
            "太长了",
            "简短点",
            "短一点",
            "自然一点",
            "温柔一点",
            "具体一点",
            "直接一点",
            "少说教",
            "少播报",
            "别打断",
            "不要打断",
            "你可以",
            "你应该",
            "你就说",
            "你直接说",
            "别叫我",
            "不要叫我",
        )
        if any(marker in text for marker in assistant_markers):
            score += 2
        if any(marker in text for marker in style_markers):
            score += 2
        if text.startswith(("别", "不要", "你别", "你不要")):
            score += 1
        if any(marker in text for marker in ("希望", "最好", "建议", "有点", "感觉")):
            score += 1

        third_party_markers = ("他", "她", "他们", "她们", "你们", "我们", "同事", "老板", "朋友", "对象", "客服")
        if any(marker in text for marker in third_party_markers) and not any(
            marker in text for marker in ("你刚才", "你刚刚", "你的回复", "你这回复")
        ):
            score -= 2

        if len(text) > 120:
            score -= 1
        return score

    def _looks_like_user_feedback_message(self, message_text: str, *, has_recent_assistant_reply: bool) -> bool:
        text = str(message_text or "").strip()
        if not text:
            return False
        score = self._score_user_feedback_message(text)
        if has_recent_assistant_reply:
            return score >= 3
        return score >= 5

    def _extract_feedback_preference_hint_from_message(self, message_text: str) -> str:
        text = self._normalize_learning_feedback(message_text, limit=90)
        if not text:
            return ""

        keyword_groups = [
            (
                ("简短", "短一点", "别太长", "太长", "啰嗦", "废话"),
                "用户更偏好简短克制的回复，避免啰嗦展开。",
            ),
            (
                ("自然一点", "自然", "别太官方", "太官方", "机械", "模板", "像朋友"),
                "用户更偏好自然、少模板味、少官方腔的表达。",
            ),
            (
                ("具体一点", "具体", "下一步", "步骤", "直接说", "可执行"),
                "用户更偏好具体、可执行、能直接落地的建议。",
            ),
            (
                ("温柔一点", "轻一点", "别打断", "不要打断", "少说教", "少播报"),
                "用户希望语气更轻、更低打扰，减少播报和说教感。",
            ),
        ]
        hints = []
        for keywords, hint in keyword_groups:
            if any(keyword in text for keyword in keywords):
                hints.append(hint)

        if hints:
            deduped = []
            seen = set()
            for hint in hints:
                if hint in seen:
                    continue
                seen.add(hint)
                deduped.append(hint)
            return " ".join(deduped)

        return f"用户刚刚在调整回复风格，倾向于类似“{text}”这样的表达要求。"

    async def _get_recent_assistant_reply_text(self, event: AstrMessageEvent) -> str:
        try:
            if not hasattr(self.context, "conversation_manager"):
                return ""

            uid = str(getattr(event, "unified_msg_origin", "") or "").strip()
            if not uid:
                return ""

            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(uid)
            if not curr_cid:
                return ""

            conversation = await conv_mgr.get_conversation(uid, curr_cid)
            if not conversation or not getattr(conversation, "history", None):
                return ""

            for msg in reversed(conversation.history[-8:]):
                if str(msg.get("role", "") or "") != "assistant":
                    continue
                content = str(msg.get("content", "") or "").strip()
                if content:
                    return content
        except Exception as e:
            logger.debug(f"读取最近助手回复失败: {e}")
        return ""

    def _remember_recent_assistant_reply(self, target: str, reply_text: str) -> None:
        target = str(target or "").strip()
        reply_text = str(reply_text or "").strip()
        if not target or not reply_text:
            return

        state = getattr(self, "_recent_assistant_replies", None)
        if not isinstance(state, dict):
            state = {}
            self._recent_assistant_replies = state
        state[target] = {
            "text": reply_text[:500],
            "timestamp": time.time(),
        }
        if len(state) > 100:
            sorted_items = sorted(
                state.items(),
                key=lambda item: float((item[1] or {}).get("timestamp", 0.0) or 0.0),
                reverse=True,
            )
            self._recent_assistant_replies = dict(sorted_items[:100])

    def _get_recent_assistant_reply_snapshot(
        self,
        event: AstrMessageEvent,
        *,
        max_age_seconds: int = 180,
    ) -> tuple[str, float]:
        target = str(getattr(event, "unified_msg_origin", "") or "").strip()
        if not target:
            return "", 0.0

        state = getattr(self, "_recent_assistant_replies", None)
        if not isinstance(state, dict):
            return "", 0.0

        snapshot = state.get(target, {}) or {}
        text = str(snapshot.get("text", "") or "").strip()
        timestamp = float(snapshot.get("timestamp", 0.0) or 0.0)
        if not text or not timestamp:
            return "", 0.0
        if time.time() - timestamp > max_age_seconds:
            return "", 0.0
        return text, timestamp

    async def _learn_from_user_feedback_message(
        self,
        event: AstrMessageEvent,
        message_text: str,
    ) -> bool:
        if not self._get_runtime_flag("enable_learning", True):
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "总学习开关已关闭",
            )
            return False
        if not self._get_runtime_flag("enable_natural_feedback_learning", True):
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "自然反馈学习已关闭",
            )
            return False

        text = str(message_text or "").strip()
        recent_assistant_reply, recent_reply_at = self._get_recent_assistant_reply_snapshot(event)
        if not self._looks_like_user_feedback_message(
            text,
            has_recent_assistant_reply=bool(recent_assistant_reply),
        ):
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "最近这条消息不像是在纠正回复风格",
            )
            return False

        target = str(getattr(event, "unified_msg_origin", "") or "").strip()
        cooldowns = getattr(self, "_natural_feedback_learning_cooldowns", None)
        if not isinstance(cooldowns, dict):
            cooldowns = {}
            self._natural_feedback_learning_cooldowns = cooldowns
        now_ts = time.time()
        if target and (now_ts - float(cooldowns.get(target, 0.0) or 0.0)) < 90:
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "自然反馈学习仍在冷却中",
            )
            return False

        assistant_reply = recent_assistant_reply or await self._get_recent_assistant_reply_text(event)
        if not assistant_reply:
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "最近没有可关联的助手回复",
            )
            return False

        preference_hint = self._extract_feedback_preference_hint_from_message(text)
        if not preference_hint:
            self._remember_learning_runtime_event(
                "feedback",
                "skipped",
                "没有提炼出明确的偏好提示",
            )
            return False

        scene = self._infer_correction_scene(assistant_reply, text)
        correction_id = str(uuid.uuid4())
        self.corrections[correction_id] = {
            "original": assistant_reply,
            "corrected": text,
            "timestamp": datetime.datetime.now().isoformat(),
            "scene": scene,
            "preference_hint": preference_hint,
            "source": "natural_feedback",
            "reply_age_seconds": int(max(0.0, now_ts - float(recent_reply_at or now_ts))),
        }
        self._update_learning_data(
            scene or "通用",
            preference_hint,
            feedback_id=correction_id,
            source="natural_feedback",
            original_text=text,
        )
        self._save_corrections()
        if target:
            cooldowns[target] = now_ts
        logger.info(f"已从自然反馈中学习一条偏好: {preference_hint}")
        self._remember_learning_runtime_event(
            "feedback",
            "learned",
            preference_hint,
        )
        return True

    def _analyze_correction_content(self, original, corrected):
        """分析纠正内容，提取关键信息并更新长期记忆。"""
        # 转换为小写进行分析
        corrected_lower = corrected.lower()
        
        # 提取关于自身形象的纠正
        if "形象" in corrected_lower or "logo" in corrected_lower or "输入法" in corrected_lower:
            self._update_self_image_memory(corrected)
        
        # 提取关于场景的纠正
        scene_patterns = ["场景", "是在", "正在", "在做"]
        if any(pattern in corrected_lower for pattern in scene_patterns):
            self._update_scene_memory(corrected)
        
        # 提取关于应用的纠正
        app_patterns = ["应用", "程序", "软件", "工具"]
        if any(pattern in corrected_lower for pattern in app_patterns):
            self._update_application_memory(corrected)

    def _update_self_image_memory(self, correction):
        """更新关于自身形象的记忆。"""
        if "self_image" not in self.long_term_memory:
            self.long_term_memory["self_image"] = []
        
        # 检查是否已经存在类似的记忆
        correction_lower = correction.lower()
        for existing in self.long_term_memory["self_image"]:
            if correction_lower in existing["content"].lower() or existing["content"].lower() in correction_lower:
                # 更新现有记忆
                existing["timestamp"] = datetime.datetime.now().isoformat()
                existing["count"] = existing.get("count", 0) + 1
                break
        else:
            # 添加新记忆
            self.long_term_memory["self_image"].append({
                "content": correction,
                "timestamp": datetime.datetime.now().isoformat(),
                "count": 1
            })
        
        # 保存长期记忆
        self._save_long_term_memory()
        logger.info("已更新自身形象记忆")

    def _update_scene_memory(self, correction):
        """更新关于场景的记忆。"""
        # 简单实现，后续可以扩展更复杂的场景提取逻辑
        if "scenes" not in self.long_term_memory:
            self.long_term_memory["scenes"] = {}
        
        # 提取可能的场景名称
        scene_keywords = ["编程", "设计", "办公", "游戏", "视频", "阅读", "音乐", "社交", "浏览"]
        for keyword in scene_keywords:
            if keyword in correction:
                if keyword not in self.long_term_memory["scenes"]:
                    self.long_term_memory["scenes"][keyword] = {
                        "count": 0,
                        "last_used": datetime.datetime.now().isoformat()
                    }
                self.long_term_memory["scenes"][keyword]["count"] += 1
                self.long_term_memory["scenes"][keyword]["last_used"] = datetime.datetime.now().isoformat()
                break
        
        # 保存长期记忆
        self._save_long_term_memory()

    def _update_application_memory(self, correction):
        """更新关于应用的记忆。"""
        if "applications" not in self.long_term_memory:
            self.long_term_memory["applications"] = {}
        
        # 简单实现，后续可以扩展更复杂的应用提取逻辑
        # 这里只是一个示例，实际应用需要更复杂的解析
        app_name = correction.split(" ")[0]
        if app_name:
            if app_name not in self.long_term_memory["applications"]:
                self.long_term_memory["applications"][app_name] = {
                    "usage_count": 0,
                    "last_used": datetime.datetime.now().isoformat(),
                    "scenes": {}
                }
            self.long_term_memory["applications"][app_name]["usage_count"] += 1
            self.long_term_memory["applications"][app_name]["last_used"] = datetime.datetime.now().isoformat()
        
        # 保存长期记忆
        self._save_long_term_memory()

    def _update_learning_data(
        self,
        scene,
        feedback,
        *,
        feedback_id: str = "",
        source: str = "",
        original_text: str = "",
    ):
        """更新学习数据。"""
        if not self.enable_learning:
            return

        scene = self._normalize_scene_label(scene or "通用")
        feedback = self._normalize_learning_feedback(feedback, limit=120)
        if not feedback:
            return

        if scene not in self.learning_data:
            self.learning_data[scene] = {"feedback": []}

        feedback_record = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "feedback": feedback,
        }
        if feedback_id:
            feedback_record["id"] = str(feedback_id)
        if source:
            feedback_record["source"] = str(source)
        if original_text:
            feedback_record["original_text"] = self._normalize_learning_feedback(
                original_text,
                limit=120,
            )

        self.learning_data[scene]["feedback"].append(feedback_record)
        self.learning_data[scene]["feedback"] = self.learning_data[scene]["feedback"][-20:]

        # 保存学习数据
        self._save_learning_data()

    def _get_recent_learned_feedback_records(
        self,
        *,
        limit: int = 5,
        source: str = "natural_feedback",
    ) -> list[dict[str, str]]:
        corrections = getattr(self, "corrections", {}) or {}
        if not isinstance(corrections, dict):
            return []

        items: list[tuple[str, dict[str, Any]]] = []
        for correction_id, item in corrections.items():
            if not isinstance(item, dict):
                continue
            if source and str(item.get("source", "") or "") != source:
                continue
            items.append((str(correction_id), item))

        ranked_items = sorted(
            items,
            key=lambda pair: str((pair[1] or {}).get("timestamp", "") or ""),
            reverse=True,
        )

        records: list[dict[str, str]] = []
        for correction_id, item in ranked_items[: max(1, int(limit or 1))]:
            records.append(
                {
                    "id": correction_id,
                    "scene": str(item.get("scene", "") or "通用"),
                    "timestamp": str(item.get("timestamp", "") or ""),
                    "preference_hint": self._normalize_learning_feedback(
                        item.get("preference_hint", ""),
                        limit=90,
                    ),
                    "corrected": self._normalize_learning_feedback(
                        item.get("corrected", ""),
                        limit=90,
                    ),
                }
            )
        return records

    def _delete_correction_learning_record(self, correction_id: str) -> bool:
        correction_id = str(correction_id or "").strip()
        if not correction_id:
            return False

        corrections = getattr(self, "corrections", {}) or {}
        if not isinstance(corrections, dict) or correction_id not in corrections:
            return False

        del corrections[correction_id]
        self.corrections = corrections
        self._save_corrections()

        learning_data = getattr(self, "learning_data", {}) or {}
        if isinstance(learning_data, dict):
            changed = False
            empty_scenes = []
            for scene_name, scene_data in learning_data.items():
                if not isinstance(scene_data, dict):
                    continue
                feedbacks = scene_data.get("feedback", [])
                if not isinstance(feedbacks, list):
                    continue
                filtered_feedbacks = [
                    item
                    for item in feedbacks
                    if str((item or {}).get("id", "") or "").strip() != correction_id
                ]
                if len(filtered_feedbacks) != len(feedbacks):
                    scene_data["feedback"] = filtered_feedbacks
                    changed = True
                if not filtered_feedbacks:
                    empty_scenes.append(scene_name)
            for scene_name in empty_scenes:
                scene_data = learning_data.get(scene_name, {})
                if isinstance(scene_data, dict) and not scene_data.get("feedback"):
                    learning_data.pop(scene_name, None)
                    changed = True
            if changed:
                self.learning_data = learning_data
                self._save_learning_data()

        return True

    def _get_default_scene_preference(self, scene: str) -> str:
        default_preferences = {
            "编程": "更喜欢收到和实现思路、排查方向、结构优化相关的建议。",
            "设计": "更喜欢收到和布局、视觉层次、信息表达相关的建议。",
            "浏览": "更喜欢收到提炼重点和判断信息价值的建议。",
            "办公": "更喜欢收到和下一步动作、沟通表达、任务推进相关的建议。",
            "游戏": "更喜欢收到和局势判断、资源分配、装备路线相关的建议。",
            "视频": "更喜欢收到贴合内容的轻量回应，而不是打断式播报。",
            "阅读": "更喜欢收到理解思路、要点提炼和解题方向上的帮助。",
            "音乐": "更喜欢收到围绕氛围、感受和联想的轻量回应。",
            "社交": "更喜欢收到对聊天语气、表达方式和分寸感的建议。",
            "学习": "更喜欢收到能立刻执行的学习方法和拆解思路。",
            "通用": "更喜欢收到具体、自然、低打扰、真正有用的回应。",
        }
        normalized_scene = self._normalize_scene_label(scene) or "通用"
        return default_preferences.get(normalized_scene, default_preferences["通用"])

    def _get_learning_preference_hints(self, scene: str, limit: int = 2) -> list[str]:
        if not self.enable_learning:
            return []

        normalized_scene = self._normalize_scene_label(scene) or "通用"
        guidance: list[str] = []
        seen = set()
        candidate_scenes = [normalized_scene]
        if normalized_scene != "通用":
            candidate_scenes.append("通用")

        for candidate_scene in candidate_scenes:
            feedbacks = ((self.learning_data or {}).get(candidate_scene, {}) or {}).get("feedback", [])
            for item in reversed(feedbacks[-limit:]):
                if not isinstance(item, dict):
                    continue
                feedback = self._normalize_learning_feedback(item.get("feedback", ""), limit=90)
                if not feedback:
                    continue
                key = self._normalize_record_text(feedback)
                if not key or key in seen:
                    continue
                seen.add(key)
                guidance.append(feedback)
                if len(guidance) >= limit:
                    return guidance
        return guidance

    def _collect_scene_preference_guidance(
        self,
        scene: str,
        *,
        active_window_title: str = "",
        limit: int = 4,
    ) -> list[str]:
        normalized_scene = self._normalize_scene_label(scene) or "通用"
        guidance: list[str] = []
        seen = set()

        def append_hint(text: str) -> None:
            hint = str(text or "").strip()
            if not hint:
                return
            key = self._normalize_record_text(hint)
            if not key or key in seen:
                return
            seen.add(key)
            guidance.append(hint)

        for candidate_scene in (normalized_scene, "通用"):
            if candidate_scene in getattr(self, "parsed_preferences", {}):
                append_hint(self.parsed_preferences[candidate_scene])
                if len(guidance) >= limit:
                    return guidance

        for hint in self._get_learning_preference_hints(normalized_scene, limit=2):
            append_hint(hint)
            if len(guidance) >= limit:
                return guidance

        get_long_term_hints = getattr(self, "_get_user_preference_memory_hints", None)
        if callable(get_long_term_hints):
            for hint in get_long_term_hints(
                normalized_scene,
                active_window_title,
                limit=2,
            ):
                append_hint(hint)
                if len(guidance) >= limit:
                    return guidance

        for hint in self._get_recent_correction_guidance(normalized_scene, limit=2):
            append_hint(hint)
            if len(guidance) >= limit:
                return guidance

        if not guidance:
            append_hint(self._get_default_scene_preference(normalized_scene))

        return guidance[:limit]

    def _get_scene_preference(self, scene, active_window_title: str = ""):
        """获取某个场景对应的互动偏好摘要。"""
        guidance = self._collect_scene_preference_guidance(
            scene,
            active_window_title=active_window_title,
            limit=3,
        )
        return " ".join(guidance)

    async def _task_scheduler(self):
        """后台任务调度器。"""
        self._ensure_runtime_state()
        while self.running and self._is_current_process_instance():
            try:
                    # 从队列中获取任务
                try:
                    task_func, task_args = await asyncio.wait_for(
                        self.task_queue.get(), timeout=1.0
                    )

                    # Run queued work under the task semaphore
                    async with self.task_semaphore:
                        try:
                            await task_func(*task_args)
                        except Exception as e:
                            logger.error(f"执行任务时出错: {e}")

                    # 标记任务完成
                    self.task_queue.task_done()
                except asyncio.TimeoutError:
                    # 超时，跳过检查running状态
                    pass
            except Exception as e:
                logger.error(f"任务调度器异常: {e}")
                await asyncio.sleep(1)

    def _parse_custom_tasks(self):
        """解析自定义定时监控任务。"""
        self.parsed_custom_tasks = []
        if not self.custom_tasks:
            return

        lines = self.custom_tasks.strip().split("\n")
        seen_tasks = set()  # 用于去重
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
                    task_key = f"{hour}:{minute}:{prompt}"
                    # 去重：如果任务已存在，则跳过
                    if task_key in seen_tasks:
                        logger.warning(f"发现重复的自定义任务: {time_str} {prompt}，已跳过")
                        continue
                    seen_tasks.add(task_key)
                    self.parsed_custom_tasks.append(
                        {"hour": hour, "minute": minute, "prompt": prompt}
                    )
            except ValueError:
                pass

        logger.info(f"解析到 {len(self.parsed_custom_tasks)} 个自定义监控任务")

    def _resolve_microphone_input_device(self, pyaudio_instance):
        cached_index = getattr(self, "_mic_input_device_index", None)
        if cached_index is not None:
            try:
                cached_info = pyaudio_instance.get_device_info_by_index(int(cached_index))
                if int(cached_info.get("maxInputChannels", 0) or 0) > 0:
                    return int(cached_info["index"]), cached_info
            except Exception:
                self._mic_input_device_index = None
                self._mic_input_device_name = ""

        candidates = []
        try:
            default_info = pyaudio_instance.get_default_input_device_info()
            if int(default_info.get("maxInputChannels", 0) or 0) > 0:
                candidates.append(default_info)
        except Exception:
            default_info = None

        try:
            device_count = int(pyaudio_instance.get_device_count() or 0)
        except Exception:
            device_count = 0

        for index in range(device_count):
            try:
                info = pyaudio_instance.get_device_info_by_index(index)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0) or 0) <= 0:
                continue
            if any(int(existing.get("index", -1)) == int(info.get("index", -2)) for existing in candidates):
                continue
            candidates.append(info)

        if not candidates:
            return None, None

        info = candidates[0]
        try:
            device_index = int(info.get("index"))
        except Exception:
            return None, None

        self._mic_input_device_index = device_index
        self._mic_input_device_name = str(info.get("name", "") or "")
        return device_index, info

    def _get_microphone_volume(self):
        """读取当前麦克风音量。"""
        self._ensure_runtime_state()
        p = None
        stream = None
        try:
            import numpy as np
            import pyaudio

            p = pyaudio.PyAudio()
            device_index, device_info = self._resolve_microphone_input_device(p)
            if device_info is None:
                logger.warning("未找到可用的麦克风输入设备，已跳过本轮音量检测")
                return 0

            sample_rate = int(float(device_info.get("defaultSampleRate", 44100) or 44100))
            frames_per_buffer = 2048
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=max(8000, sample_rate),
                input=True,
                input_device_index=device_index,
                frames_per_buffer=frames_per_buffer,
                start=False,
            )
            stream.start_stream()

            chunks = []
            for chunk_index in range(4):
                raw = stream.read(frames_per_buffer, exception_on_overflow=False)
                if not raw:
                    continue
                if chunk_index == 0:
                    continue
                chunk = np.frombuffer(raw, dtype=np.int16)
                if chunk.size:
                    chunks.append(chunk.astype(np.float32))

            if not chunks:
                return 0

            audio_data = np.concatenate(chunks)
            if audio_data.size == 0:
                return 0

            mean_square = float(np.mean(np.square(audio_data, dtype=np.float32), dtype=np.float64))
            if not np.isfinite(mean_square) or mean_square <= 0:
                return 0

            rms = float(np.sqrt(mean_square))
            if not np.isfinite(rms) or rms <= 0:
                return 0

            volume = min(100, max(0, int(rms / 32768.0 * 100 * 5)))
            return volume
        except ImportError:
            logger.debug("麦克风监听依赖未安装，无法读取音量")
            return 0
        except Exception as e:
            logger.error(f"获取麦克风音量失败: {e}")
            return 0
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            if p is not None:
                try:
                    p.terminate()
                except Exception:
                    pass

    def _ensure_mic_monitor_background_task(self) -> None:
        self._ensure_runtime_state()
        task = getattr(self, "_mic_monitor_background_task", None)
        if task and not task.done():
            return
        if not self.enable_mic_monitor or not self.running:
            return
        task = self._safe_create_task(self._mic_monitor_task(), name="mic_monitor")
        self._mic_monitor_background_task = task
        if task not in self.background_tasks:
            self.background_tasks.append(task)

    def _stop_mic_monitor_background_task(self) -> None:
        task = getattr(self, "_mic_monitor_background_task", None)
        if task and not task.done():
            task.cancel()
        self._mic_monitor_background_task = None

    def _get_missing_mic_dependencies(self) -> list[str]:
        """返回当前缺失或不可用的麦克风监听依赖。"""
        missing_libs = []
        for module_name in ("pyaudio", "numpy"):
            try:
                __import__(module_name)
            except Exception:
                missing_libs.append(module_name)
        return missing_libs

    def _format_missing_dependency_message(self, missing_libs: list[str]) -> str:
        """生成缺失依赖提示文案。"""
        unique_missing_libs = list(dict.fromkeys(missing_libs))
        if not unique_missing_libs:
            return ""

        install_cmd = f"pip install {' '.join(unique_missing_libs)}"
        message = f"缺少依赖：{', '.join(unique_missing_libs)}。请执行：{install_cmd}"

        mic_missing = [lib for lib in unique_missing_libs if lib in {"pyaudio", "numpy"}]
        if mic_missing:
            message += "。如果只是想启用麦克风监听，也可以执行：pip install -r requirements-optional-mic.txt"
            if "pyaudio" in mic_missing:
                if sys.platform.startswith("linux"):
                    message += "。Linux 还需要先安装 PortAudio 开发包，例如：sudo apt install portaudio19-dev"
                elif sys.platform == "darwin":
                    message += "。macOS 如安装失败，请先安装 PortAudio，例如：brew install portaudio"
        return message

    async def _mic_monitor_task(self):
        """后台麦克风监听任务。"""
        self._ensure_runtime_state()
        # 检查麦克风依赖
        mic_deps_ok = False
        try:
            import sys

            logger.info(f"[麦克风依赖检查] Python 路径: {sys.path}")
            logger.info(f"[麦克风依赖检查] Python 可执行文件: {sys.executable}")

            import pyaudio

            logger.info(f"[麦克风依赖检查] PyAudio 已加载: {pyaudio.__version__}")

            import numpy

            logger.info(f"[麦克风依赖检查] NumPy 已加载: {numpy.__version__}")

            mic_deps_ok = True
        except Exception as e:
            missing_mic_libs = self._get_missing_mic_dependencies()
            logger.warning(f"[麦克风依赖检查] 麦克风监听依赖不可用: {e}")
            if missing_mic_libs:
                logger.warning(self._format_missing_dependency_message(missing_mic_libs))
            elif sys.platform.startswith("linux"):
                logger.warning(
                    "[麦克风依赖检查] PyAudio 初始化失败，请确认已安装 PortAudio 相关系统库，并授予麦克风权限。"
                )
            import traceback

            logger.warning(f"[麦克风依赖检查] 详细错误: {traceback.format_exc()}")

        while self.enable_mic_monitor and self._is_current_process_instance():
            try:
                if not mic_deps_ok:
                    await asyncio.sleep(60)
                    continue

                # 获取当前时间
                current_time = time.time()

                if current_time - self.last_mic_trigger < self.mic_debounce_time:
                    await asyncio.sleep(self.mic_check_interval)
                    continue

                # 获取麦克风音量
                volume = self._get_microphone_volume()
                logger.debug(f"麦克风音量: {volume}")

                if volume > self.mic_threshold:
                    logger.info(f"麦克风音量超过阈值: {volume} > {self.mic_threshold}")
                    # 在进入异步识屏任务前就启动冷却，避免高音量持续时重复创建任务。
                    self.last_mic_trigger = current_time

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
                        if current_state == "inactive":
                            self.state = "temporary"
                        
                        # 创建临时任务 ID
                        temp_task_id = f"temp_mic_{int(time.time())}"
                        
                        # 定义临时任务函数
                        async def temp_mic_task():
                            background_job_started = False
                            try:
                                background_job_started, skip_reason = self._try_begin_background_screen_job()
                                if not background_job_started:
                                    logger.info(f"[{temp_task_id}] 跳过麦克风触发识屏: {skip_reason}")
                                    return
                                target = self._resolve_proactive_target()
                                event = self._create_virtual_event(target)

                                capture_timeout = self._get_capture_context_timeout(
                                    "video" if self._use_screen_recording_mode() else "image"
                                )
                                capture_context = await asyncio.wait_for(
                                    self._capture_proactive_recognition_context(),
                                    timeout=capture_timeout,
                                )
                                active_window_title = capture_context.get("active_window_title", "")
                                components = await asyncio.wait_for(
                                    self._analyze_screen(
                                        capture_context,
                                        session=event,
                                        active_window_title=active_window_title,
                                        custom_prompt="刚才那边好像有点动静？让我看看你现在在做什么呢。",
                                        task_id=temp_task_id,
                                    ),
                                    timeout=self._get_screen_analysis_timeout(
                                        capture_context.get("media_kind", "image")
                                    ),
                                )

                                # 确定消息发送目标
                                target = self._resolve_proactive_target()

                                if target and await self._send_component_text(
                                    target,
                                    components,
                                ):
                                        logger.info("麦克风提醒消息发送成功")
                                        if capture_context.get("_rest_reminder_planned"):
                                            self._mark_rest_reminder_sent(
                                                capture_context.get("_rest_reminder_info", {}) or {}
                                            )

                            finally:
                                # 任务完成后清理临时任务
                                if temp_task_id in self.temporary_tasks:
                                    del self.temporary_tasks[temp_task_id]
                                if background_job_started:
                                    self._finish_background_screen_job()
                                if not self.auto_tasks and not self.temporary_tasks:
                                    self.state = current_state

                        self.temporary_tasks[temp_task_id] = asyncio.create_task(temp_mic_task())
                        logger.info(f"已创建麦克风临时任务: {temp_task_id}")
                    except Exception as e:
                        logger.error(f"创建麦克风临时任务时出错: {e}")
                        if not self.auto_tasks and not self.temporary_tasks:
                            self.state = current_state

                await asyncio.sleep(self.mic_check_interval)
            except Exception as e:
                logger.error(f"麦克风监听任务异常: {e}")
                await asyncio.sleep(self.mic_check_interval)

    async def _custom_tasks_task(self):
        """后台自定义任务调度循环。"""
        self._ensure_runtime_state()
        while self.running and self._is_current_process_instance():
            try:
                now = datetime.datetime.now()
                current_date = now.date()
                current_hour = now.hour
                current_minute = now.minute

                for task in self.parsed_custom_tasks:
                    # 生成任务唯一标识
                    task_key = f"{task['hour']}:{task['minute']}:{task['prompt']}"
                    # 检查今天是否已经执行过
                    if self.last_task_execution.get(task_key) == current_date:
                        continue
                    if task["hour"] != current_hour or task["minute"] != current_minute:
                        continue
                    if not self._try_mark_custom_task_dispatch(task_key):
                        logger.info(f"跳过重复的自定义监控任务派发: {task['prompt']}")
                        self.last_task_execution[task_key] = current_date
                        continue
                    
                    if (
                        task["hour"] == current_hour
                        and task["minute"] == current_minute
                    ):
                        logger.info(f"执行自定义监控任务: {task['prompt']}")
                        self.last_task_execution[task_key] = current_date
                        # 检查环境
                        ok, err_msg = self._check_env()
                        if not ok:
                            logger.error(f"自定义任务执行失败: {err_msg}")
                            continue

                        # 创建临时任务
                        try:
                            # 保存当前状态
                            current_state = self.state
                            if current_state == "inactive":
                                self.state = "temporary"
                            
                            # 创建临时任务 ID
                            temp_task_id = f"temp_custom_{int(time.time())}"
                            
                            # 定义临时任务函数
                            async def temp_custom_task():
                                background_job_started = False
                                try:
                                    background_job_started, skip_reason = self._try_begin_background_screen_job()
                                    if not background_job_started:
                                        logger.info(f"[{temp_task_id}] 跳过自定义监控识屏: {skip_reason}")
                                        return
                                    capture_timeout = self._get_capture_context_timeout(
                                        "video" if self._use_screen_recording_mode() else "image"
                                    )
                                    capture_context = await asyncio.wait_for(
                                        self._capture_proactive_recognition_context(),
                                        timeout=capture_timeout,
                                    )
                                    capture_context["trigger_reason"] = f"定时提醒：{task['prompt']}"
                                    active_window_title = capture_context.get("active_window_title", "")
                                    components = await asyncio.wait_for(
                                        self._analyze_screen(
                                            capture_context,
                                            active_window_title=active_window_title,
                                            custom_prompt=task["prompt"],
                                            task_id=temp_task_id,
                                        ),
                                        timeout=self._get_screen_analysis_timeout(
                                            capture_context.get("media_kind", "image")
                                        ),
                                    )

                                    # 确定消息发送目标
                                    target = self._resolve_proactive_target()
                                    analysis_trace = capture_context.get("_analysis_trace", {}) or {}

                                    if target and await self._send_component_text(
                                        target,
                                        components,
                                        prefix="【定时提醒】",
                                    ):
                                            analysis_trace["status"] = "sent"
                                            analysis_trace["reply_preview"] = self._truncate_preview_text(
                                                self._extract_plain_text(components),
                                                limit=140,
                                            )
                                            self._remember_screen_analysis_trace(analysis_trace)
                                            logger.info("自定义任务提醒消息发送成功")
                                            if capture_context.get("_rest_reminder_planned"):
                                                self._mark_rest_reminder_sent(
                                                    capture_context.get("_rest_reminder_info", {}) or {}
                                                )
                                finally:
                                    # 任务完成后清理临时任务
                                    if temp_task_id in self.temporary_tasks:
                                        del self.temporary_tasks[temp_task_id]
                                    if background_job_started:
                                        self._finish_background_screen_job()
                                    if not self.auto_tasks and not self.temporary_tasks:
                                        self.state = current_state

                            self.temporary_tasks[temp_task_id] = asyncio.create_task(temp_custom_task())
                            logger.info(f"已创建自定义临时任务: {temp_task_id}")
                        except Exception as e:
                            logger.error(f"创建自定义临时任务时出错: {e}")
                            if not self.auto_tasks and not self.temporary_tasks:
                                self.state = current_state

                # 等待 1 分钟，期间持续检查 running 标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"自定义任务异常: {e}")
                # 等待 1 分钟，期间持续检查 running 标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)

    async def _diary_task(self):
        """日记定时任务。"""
        while self.running and self._is_current_process_instance():
            try:
                now = datetime.datetime.now()
                if self.enable_diary:
                    current_target_date = self._resolve_diary_target_date(now)
                    for target_date in self._get_due_diary_dates(now):
                        await self._generate_diary(
                            target_date=target_date,
                            allow_empty=(target_date == current_target_date),
                        )

                # 等待 1 分钟，期间持续检查 running 标志
                for _ in range(60):
                    if not self.running:
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"日记任务异常: {e}")
                # 等待 1 分钟，期间持续检查 running 标志
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
        """后台自动截图分析任务。

        参数:
        task_id: 任务 ID
        custom_prompt: 自定义提示词
        interval: 自定义检查间隔（秒）
        """
        self._ensure_runtime_state()
        logger.info(f"[任务 {task_id}] 启动自动识屏任务")
        
        try:
            while self.is_running and self.state == "active" and self._is_current_process_instance():
                if not self._is_in_active_time_range():
                    logger.info(f"[任务 {task_id}] 当前不在活跃时间段，准备停止任务")
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
                if task_id == getattr(self, "WINDOW_COMPANION_TASK_ID", ""):
                    self._sync_window_companion_effective_params(
                        check_interval,
                        probability,
                    )

                # 优先使用任务级别的自定义间隔
                if interval is not None:
                    check_interval = interval
                    logger.info(f"[任务 {task_id}] 使用自定义检查间隔: {check_interval} 秒")
                else:
                    logger.info(f"[任务 {task_id}] 使用当前预设间隔: {check_interval} 秒")

                while self.is_running and self.state == "active":
                    if not await self._handle_away_auto_pause(event, task_id=task_id):
                        break
                    await asyncio.sleep(1)

                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务状态已变化，结束本轮")
                    break

                logger.info(f"[任务 {task_id}] 等待 {check_interval} 秒后进入触发判定")
                elapsed = 0
                window_changed = False
                latest_new_windows: list[str] = []
                while elapsed < check_interval:
                    if not self.is_running or self.state != "active":
                        logger.info(f"[任务 {task_id}] 任务状态已变化，停止等待")
                        break
                    try:
                        if await self._handle_away_auto_pause(event, task_id=task_id):
                            await asyncio.sleep(1)
                            continue

                        # 检测窗口变化
                        if elapsed % 3 == 0:  # 每3秒检测一次窗口变化
                            latest_window_changed, new_windows = self._detect_window_changes()
                            if latest_window_changed:
                                window_changed = True
                                latest_new_windows = list(new_windows or [])
                            if latest_window_changed and new_windows:
                                logger.info(f"[任务 {task_id}] 检测到新打开的窗口: {new_windows}")
                                # 可以在这里添加对新窗口的处理逻辑
                                # 例如：发送通知、自动开始陪伴等
                        
                        if elapsed > 0 and elapsed % 10 == 0 and interval is None:
                            new_check_interval, new_probability = self._get_current_preset_params()
                            if new_check_interval != check_interval:
                                check_interval = new_check_interval
                                logger.info(
                                    f"[Task {task_id}] preset interval updated to {check_interval} seconds"
                                )
                                if elapsed >= check_interval:
                                    logger.info(
                                        f"[Task {task_id}] new interval is now active; triggering early"
                                    )
                                    break
                            if new_probability != probability:
                                probability = new_probability
                                logger.info(
                                    f"[任务 {task_id}] 预设参数已更新，触发概率变为 {probability}%"
                                )
                            if task_id == getattr(self, "WINDOW_COMPANION_TASK_ID", ""):
                                self._sync_window_companion_effective_params(
                                    check_interval,
                                    probability,
                                )
                        await asyncio.sleep(1)
                        elapsed += 1
                    except asyncio.CancelledError:
                        logger.info(f"[任务 {task_id}] 等待期间收到取消信号")
                        raise

                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务状态已变化，结束本轮")
                    break

                if await self._handle_away_auto_pause(event, task_id=task_id):
                    await asyncio.sleep(1)
                    continue

                # 再次确认是否仍处于活跃时间段
                if not self._is_in_active_time_range():
                    logger.info(f"[任务 {task_id}] 已离开活跃时间段，停止任务")
                    # 清理任务
                    if task_id in self.auto_tasks:
                        del self.auto_tasks[task_id]
                    # 检查是否还有其他任务在运行
                    if not self.auto_tasks:
                        self.is_running = False
                        self.state = "inactive"
                    break

                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务状态已变化，结束本轮")
                    break

                # 检测系统负载
                system_high_load = False
                try:
                    import psutil

                    cpu_percent = psutil.cpu_percent(interval=1)
                    memory = psutil.virtual_memory()
                    memory_percent = memory.percent

                    if cpu_percent > 80 or memory_percent > 80:
                        system_high_load = True
                        logger.info(
                            f"[任务 {task_id}] 系统资源占用较高: CPU={cpu_percent}%, 内存={memory_percent}%"
                        )
                except ImportError:
                    logger.debug(f"[任务 {task_id}] 未安装 psutil，跳过系统负载检测")
                except Exception as e:
                    logger.debug(f"[任务 {task_id}] 系统状态检测失败: {e}")

                # 高负载时强制触发一次识屏
                change_snapshot = self._build_auto_screen_change_snapshot(
                    task_id,
                    window_changed=window_changed,
                    new_windows=latest_new_windows,
                )
                logger.info(
                    f"[任务 {task_id}] 变化感知: changed={change_snapshot['changed']}, "
                    f"window={change_snapshot['active_window_title'] or '未知'}, "
                    f"reason={change_snapshot['reason'] or '无明显变化'}"
                )
                decision = self._decide_auto_screen_trigger(
                    task_id,
                    probability=probability,
                    check_interval=check_interval,
                    system_high_load=system_high_load,
                    change_snapshot=change_snapshot,
                )
                trigger = bool(decision["trigger"])
                if decision["random_number"] is None:
                    logger.info(f"[任务 {task_id}] {decision['reason']}")
                else:
                    logger.info(
                        f"[任务 {task_id}] {decision['reason']}，随机数={decision['random_number']}，"
                        f"生效概率={decision['effective_probability']}%"
                    )

                # 检查是否已经停止
                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务状态已变化，结束本轮")
                    break

                if not self.is_running or self.state != "active":
                    logger.info(f"[任务 {task_id}] 任务状态已变化，结束本轮")
                    break

                if trigger:
                    logger.info(f"[任务 {task_id}] 满足触发条件，准备执行识屏分析")
                    try:
                        should_defer, defer_reason = self._should_defer_for_recent_user_activity(
                            event,
                            task_id=task_id,
                            change_snapshot=change_snapshot,
                        )
                        if should_defer:
                            logger.info(f"[任务 {task_id}] 主动识屏暂缓: {defer_reason}")
                            continue

                        if await self._handle_away_auto_pause(event, task_id=task_id):
                            await asyncio.sleep(1)
                            continue

                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务停止标志已设置，取消本次屏幕分析"
                            )
                            break

                        if not self._is_in_active_time_range():
                            logger.info(
                                f"[Task {task_id}] outside active time range, stopping task"
                            )
                            # 清理任务
                            if task_id in self.auto_tasks:
                                del self.auto_tasks[task_id]
                            # 检查是否还有其他任务在运行
                            if not self.auto_tasks:
                                self.is_running = False
                            break

                        # 妫鏌ユ槸鍚﹁鍋滄
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[Task {task_id}] stop flag detected, cancelling screen analysis"
                            )
                            break

                        capture_timeout = self._get_capture_context_timeout(
                            "video" if self._use_screen_recording_mode() else "image"
                        )
                        capture_context = await asyncio.wait_for(
                            self._capture_proactive_recognition_context(),
                            timeout=capture_timeout,
                        )
                        capture_context["trigger_reason"] = decision["reason"]
                        active_window_title = capture_context.get("active_window_title", "")

                        # 检查是否运行中
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[任务 {task_id}] 任务运行状态被取消，取消屏幕分析"
                            )
                            break

                        components = await asyncio.wait_for(
                            self._analyze_screen(
                                capture_context,
                                session=event,
                                active_window_title=active_window_title,
                                custom_prompt=custom_prompt,
                                task_id=task_id,
                            ),
                            timeout=self._get_screen_analysis_timeout(
                                capture_context.get("media_kind", "image")
                            ),
                        )

                        # 检查任务是否已停止
                        if not self.is_running or self.state != "active":
                            logger.info(
                                f"[Task {task_id}] stop flag detected, canceling proactive send"
                            )
                            break

                        chain = self._build_message_chain(components)
                        target = self._resolve_proactive_target(event)
                        text_content = self._extract_plain_text(components)
                        analysis_trace = capture_context.get("_analysis_trace", {}) or {}
                        current_scene = str(
                            analysis_trace.get("scene")
                            or change_snapshot.get("scene")
                            or ""
                        ).strip()
                        skip_similar, skip_reason = self._should_skip_similar_auto_reply(
                            task_id,
                            active_window_title=active_window_title,
                            text_content=text_content,
                            check_interval=check_interval,
                        )

                        if skip_similar:
                            logger.info(f"[任务 {task_id}] 主动回复已跳过: {skip_reason}")
                            self._remember_auto_reply_state(
                                task_id,
                                active_window_title=active_window_title,
                                text_content=text_content,
                                sent=False,
                                scene=current_scene,
                                note=skip_reason,
                            )
                            analysis_trace["status"] = "skipped_similar"
                            analysis_trace["reply_preview"] = self._truncate_preview_text(
                                text_content,
                                limit=140,
                            )
                            self._remember_screen_analysis_trace(analysis_trace)
                            continue

                        skip_window_limit, window_limit_reason = self._should_skip_same_window_followup(
                            task_id,
                            active_window_title=active_window_title,
                            scene=current_scene,
                        )
                        if skip_window_limit:
                            logger.info(f"[任务 {task_id}] 主动回复已降频: {window_limit_reason}")
                            self._remember_auto_reply_state(
                                task_id,
                                active_window_title=active_window_title,
                                text_content=text_content,
                                sent=False,
                                scene=current_scene,
                                note=window_limit_reason,
                            )
                            analysis_trace["status"] = "skipped_window_cooldown"
                            analysis_trace["reply_preview"] = self._truncate_preview_text(
                                text_content,
                                limit=140,
                            )
                            self._remember_screen_analysis_trace(analysis_trace)
                            continue

                        # 添加日记条目
                        diary_stored = self._add_diary_entry(text_content, active_window_title)
                        analysis_trace["stored_in_diary"] = bool(diary_stored)

                        # 自动分段发送，参考 splitter 插件的思路
                        if text_content:
                            logger.info(
                                f"准备发送主动消息，目标: {target}, 文本内容: {text_content}"
                            )
                            sent = await self._send_segmented_text(
                                target,
                                text_content,
                                should_continue=lambda: self.is_running,
                            )
                            self._remember_auto_reply_state(
                                task_id,
                                active_window_title=active_window_title,
                                text_content=text_content,
                                sent=sent,
                                scene=current_scene,
                            )
                            if sent and capture_context.get("_rest_reminder_planned"):
                                self._mark_rest_reminder_sent(
                                    capture_context.get("_rest_reminder_info", {}) or {}
                                )
                        else:
                            sent = False
                            if self.is_running:
                                sent = await self._send_proactive_message(
                                    target, chain
                                )
                            self._remember_auto_reply_state(
                                task_id,
                                active_window_title=active_window_title,
                                text_content="[非纯文本回复]",
                                sent=sent,
                                scene=current_scene,
                            )
                            if sent and capture_context.get("_rest_reminder_planned"):
                                self._mark_rest_reminder_sent(
                                    capture_context.get("_rest_reminder_info", {}) or {}
                                )
                        analysis_trace["reply_preview"] = self._truncate_preview_text(
                            text_content or "[非纯文本回复]",
                            limit=140,
                        )
                        analysis_trace["status"] = "sent" if sent else "not_sent"
                        self._remember_screen_analysis_trace(analysis_trace)

                        # 尝试将消息加入到对话历史
                        try:
                            from astrbot.core.agent.message import (
                                AssistantMessageSegment,
                                TextPart,
                                UserMessageSegment,
                            )

                            if hasattr(self.context, "conversation_manager"):
                                conv_mgr = self.context.conversation_manager
                                uid = event.unified_msg_origin
                                curr_cid = await conv_mgr.get_curr_conversation_id(uid)

                                if curr_cid:
                                    # Create user and assistant message segments
                                    user_msg = UserMessageSegment(
                                        content=[TextPart(text="[主动识屏触发]")]
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
                                    logger.info("已写入一条主动消息到会话历史")
                        except Exception as e:
                            logger.debug(f"添加对话历史失败: {e}")
                    except asyncio.TimeoutError:
                        logger.error("自动识屏任务超时，请检查系统资源和网络连接")
                    except Exception as e:
                        logger.error(f"自动观察任务执行失败: {e}")
                        import traceback

                        logger.error(traceback.format_exc())
        except asyncio.CancelledError:
            logger.info(f"任务 {task_id} 已被取消")
        except Exception as e:
            logger.error(f"任务 {task_id} 异常: {e}")
        finally:
            if task_id in self.auto_tasks:
                del self.auto_tasks[task_id]
                logger.info(f"[任务 {task_id}] 已从自动任务列表移除")
            # 检查是否还有其他任务在运行
            if not self.auto_tasks:
                reset_away_pause = getattr(self, "_reset_away_pause_runtime_state", None)
                if callable(reset_away_pause):
                    reset_away_pause()
                self.is_running = False
                logger.info("所有自动观察任务已结束")
            logger.info(f"任务 {task_id} 已结束")

    def _split_message(self, text: str, max_length: int = 1000) -> list[str]:
        """将较长文本拆分为适合发送的多段消息。"""
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
                    # 单行长度超过上限时，强制拆分
                    while len(line) > max_length:
                        segments.append(line[:max_length])
                        line = line[max_length:]
                    current_segment = line

        if current_segment:
            segments.append(current_segment)

        return segments

    async def stop(self):
        """Stop the plugin and cancel active tasks."""
        shutdown_lock = getattr(self, "_shutdown_lock", None)
        if shutdown_lock is None:
            self._shutdown_lock = asyncio.Lock()
            shutdown_lock = self._shutdown_lock

        async with shutdown_lock:
            if getattr(self, "_is_stopping", False):
                logger.info("插件关闭过程正在进行，跳过重复关闭请求")
                return

            self._is_stopping = True
            logger.info("开始停止插件并清理运行中的任务")

            try:
                self.running = False
                self.is_running = False
                self.state = "inactive"
                self.enable_mic_monitor = False
                self.enable_input_stats = False
                self.window_companion_active_title = ""
                self._close_current_activity(
                    min_duration_seconds=self.LIVE_ACTIVITY_MIN_DURATION_SECONDS
                )
                
                # 停止 Web 服务器
                if self.web_server:
                    logger.info("正在停止 Web UI 服务器...")
                    await self.web_server.stop()
                    self.web_server = None
                    # 增加延迟时间，确保端口完全释放
                    await asyncio.sleep(1.0)
                await self._stop_recording_if_running()
                self._stop_input_stats_listener(reason="shutdown")
                self.window_companion_active_target = ""
                self.window_companion_active_rule = {}

                await self._cancel_tasks(list(self.auto_tasks.values()), "自动任务")
                self.auto_tasks.clear()

                await self._cancel_tasks(list(self.temporary_tasks.values()), "临时任务")
                self.temporary_tasks.clear()

                await self._cancel_tasks(list(self.background_tasks), "后台任务")
                self.background_tasks.clear()

                await self._stop_webui()
                logger.info("插件停止完成，后台任务与 WebUI 已清理")
            finally:
                self._is_stopping = False

    def _check_dependencies(self, check_mic=False):
        """Check optional runtime dependencies.

        Args:
            check_mic: Whether microphone-related dependencies are required.
        """
        self._ensure_runtime_state()
        missing_libs = []
        if self._use_screen_recording_mode():
            if not self._get_ffmpeg_path():
                missing_libs.append("ffmpeg")
        else:
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
            and self.capture_active_window
            and not self._use_screen_recording_mode()
        ):
            try:
                import pygetwindow
            except ImportError:
                missing_libs.append("pygetwindow")

        # 检查麦克风监控依赖
        if check_mic and self.enable_mic_monitor:
            missing_libs.extend(self._get_missing_mic_dependencies())

        if missing_libs:
            if missing_libs == ["ffmpeg"]:
                return (
                    False,
                    "缺少 ffmpeg。你可以将 ffmpeg.exe 放到插件数据目录下的 bin 文件夹，"
                    "或在配置中填写 ffmpeg_path，或加入系统 PATH。"
                )
            return (
                False,
                self._format_missing_dependency_message(missing_libs),
            )
        return True, ""

    def _check_env(self, check_mic=False):
        """Check whether the desktop environment is available.

        Args:
            check_mic: Whether microphone-related dependencies are required.
        """
        dep_ok, dep_msg = self._check_dependencies(check_mic=check_mic)
        if not dep_ok:
            return False, dep_msg

        if self._use_screen_recording_mode():
            if sys.platform != "win32":
                return False, "录屏视频识别目前仅支持 Windows 桌面环境。"
            ffmpeg_path = self._get_ffmpeg_path()
            if not ffmpeg_path:
                return (
                    False,
                    "未检测到 ffmpeg。请将 ffmpeg.exe 放到插件数据目录下的 bin 文件夹，"
                    "或在配置中填写 ffmpeg_path，或加入系统 PATH。"
                )
            return True, ""

        try:
            import pyautogui

            # 检查 Linux 下的 Display 环境变量
            if sys.platform.startswith("linux"):
                import os

                if not os.environ.get("DISPLAY") and not os.environ.get(
                    "WAYLAND_DISPLAY"
                ):
                    return (
                        False,
                        "Detected Linux without an available graphical display. Please run it in a desktop session or with X11 forwarding.",
                    )

            size = pyautogui.size()
            if size[0] <= 0 or size[1] <= 0:
                return False, "Unable to capture the screen properly."

            return True, ""
        except Exception as e:
            return False, f"自我检查失败: {str(e)}"

    async def _get_persona_prompt(self, umo: str = None) -> str:
        """获取屏幕伴侣的系统提示词"""
        def _normalize_prompt_override(value: Any) -> str:
            text = str(value or "").strip()
            if not text:
                return ""

            placeholder_markers = (
                "把你正在使用的人格复制到这里",
                "角色设定：窥屏助手",
            )
            normalized_text = text.replace("\r\n", "\n").strip()
            if any(marker in normalized_text for marker in placeholder_markers):
                return ""
            return normalized_text

        base_prompt = ""
        try:
            if hasattr(self.context, "persona_manager"):
                persona = await self.context.persona_manager.get_default_persona_v3(
                    umo=umo
                )
                if persona and "prompt" in persona:
                    base_prompt = persona["prompt"]
        except Exception as e:
            logger.debug(f"获取屏幕尺寸失败: {e}")

        base_prompt = _normalize_prompt_override(base_prompt)
        config_prompt = _normalize_prompt_override(getattr(self, "system_prompt", ""))
        companion_prompt = _normalize_prompt_override(
            getattr(self, "companion_prompt", "")
        )

        # 检查是否为陪伴模式
        if self.use_companion_mode:
            companion_supplemental_guide = (
                "\n\n额外要求：保持对话的连续性，关注用户的任务进展，提供具体、实用的建议。"
                "你可以偶尔轻轻表达自己也想和用户一起看点内容、玩一局游戏或做个小测试，"
                "但必须低频、自然，不要打断正事，更不能凭空捏造共同经历。"
            )
            effective_prompt = (
                companion_prompt or base_prompt or config_prompt or DEFAULT_SYSTEM_PROMPT
            )
            return f"{effective_prompt.rstrip()}{companion_supplemental_guide}"

        if not base_prompt and config_prompt:
            base_prompt = config_prompt

        if not base_prompt:
            base_prompt = DEFAULT_SYSTEM_PROMPT

        supplemental_guide = (
            "\n\n额外要求：少用旁白式开场，不要总是先叫用户名字。"
            "如果能提出建议，优先给和当前任务直接相关、能立刻用上的建议。"
            "可以偶尔表达自己也想和用户一起做点什么，但只限轻松自然的一句，"
            "并且任何共同经历都只能基于当前对话或已记录内容，不能虚构。"
        )

        return f"{base_prompt.rstrip()}{supplemental_guide}"

    def _build_start_end_prompt(self, raw_prompt: str, action: str) -> str:
        """为开始/结束消息补充更明确的人格化约束。"""
        base_prompt = str(raw_prompt or "").strip()
        if not base_prompt:
            if action == "start":
                base_prompt = "以你的性格向用户表达你会开始偶尔地陪着用户看屏幕了。"
            else:
                base_prompt = "以你的性格向用户表达你会先暂停看屏幕、退到旁边等用户再叫你。"

        supplemental = (
            "\n额外要求："
            "回复必须明显带有人格，不要像系统提示、状态播报或功能开关通知。"
            "语气要自然、亲近、有人味，像这个角色本人在开口。"
            "避免使用“已开始”“已停止”“任务已启动”“任务已结束”这种机械措辞。"
            "尽量简短，控制在 1 到 2 句话内。"
            "允许有一点角色感、小情绪或亲昵感，但不要夸张，也不要说得像说明书。"
        )
        return f"{base_prompt.rstrip()}{supplemental}"

    def _collect_start_end_reference_lines(self, limit: int | None = None) -> list[str]:
        """收集最近几条可供开始/结束文案参考的识屏结果与回复。"""
        self._ensure_runtime_state()
        try:
            max_items = int(
                limit
                if limit is not None
                else getattr(self, "START_END_CONTEXT_LOOKBACK", 2)
            )
        except Exception:
            max_items = 2

        if max_items <= 0:
            return []

        context_lines: list[str] = []
        seen_signatures: set[str] = set()

        recent_traces: list[dict[str, Any]] = []
        if hasattr(self, "_get_recent_screen_analysis_traces"):
            recent_traces = self._get_recent_screen_analysis_traces(
                limit=max(max_items * 3, max_items)
            ) or []

        for trace in recent_traces:
            if not isinstance(trace, dict):
                continue
            status = str(trace.get("status", "") or "").strip().lower()
            if status.startswith("error"):
                continue

            scene = self._normalize_scene_label(trace.get("scene", ""))
            if scene == "未知":
                scene = ""
            window_title = self._normalize_window_title(
                trace.get("active_window_title", "")
                or trace.get("latest_window_title", "")
                or ""
            )
            recognition_summary = self._truncate_preview_text(
                trace.get("recognition_summary", ""),
                limit=80,
            )
            reply_preview = self._truncate_preview_text(
                trace.get("reply_preview", ""),
                limit=80,
            )
            if not any((scene, window_title, recognition_summary, reply_preview)):
                continue

            signature = "|".join(
                (scene, window_title, recognition_summary, reply_preview)
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            parts: list[str] = []
            if scene:
                parts.append(f"场景：{scene}")
            if window_title:
                parts.append(f"窗口：{window_title}")
            if recognition_summary:
                parts.append(f"识屏：{recognition_summary}")
            if reply_preview:
                parts.append(f"回复：{reply_preview}")

            if parts:
                context_lines.append("- " + "；".join(parts))
            if len(context_lines) >= max_items:
                return context_lines

        recent_observations = list(getattr(self, "observations", []) or [])
        for obs in reversed(recent_observations):
            if not isinstance(obs, dict):
                continue
            scene = self._normalize_scene_label(obs.get("scene", ""))
            if scene == "未知":
                scene = ""
            window_title = self._normalize_window_title(
                obs.get("active_window") or obs.get("window_title") or ""
            )
            description = self._truncate_preview_text(
                obs.get("description", "") or obs.get("recognition_summary", ""),
                limit=80,
            )
            if not any((scene, window_title, description)):
                continue

            signature = "|".join((scene, window_title, description))
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)

            parts = []
            if scene:
                parts.append(f"场景：{scene}")
            if window_title:
                parts.append(f"窗口：{window_title}")
            if description:
                parts.append(f"识屏：{description}")

            if parts:
                context_lines.append("- " + "；".join(parts))
            if len(context_lines) >= max_items:
                break

        return context_lines

    def _build_end_response_prompt(self) -> str:
        """为结束陪伴回复补充最近识屏上下文。"""
        prompt = self._build_start_end_prompt(
            self.end_llm_prompt,
            action="end",
        )
        reference_lines = self._collect_start_end_reference_lines()
        if not reference_lines:
            return prompt

        contextual_guidance = (
            "\n补充要求：如果最近几轮明显围绕某个具体场景，"
            "结束时可以顺着刚刚那段陪伴自然收尾，"
            "比如轻轻提一下下次继续看、继续玩、继续写，"
            "或者说有需要再叫你。"
            "但必须严格基于下面这些最近记录，不要凭空编造共同经历。"
            "\n最近几轮识屏与回复：\n"
            + "\n".join(reference_lines)
        )
        return f"{prompt}{contextual_guidance}"

    async def _get_start_response(self, umo: str = None) -> str:
        """Build the startup reply text."""
        mode = "llm" if self.use_llm_for_start_end else "preset"
        if mode == "preset" or (hasattr(mode, 'value') and mode.value == "preset"):
            return self.start_preset
        else:
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt(umo)
                    prompt = self._build_start_end_prompt(
                        self.start_llm_prompt,
                        action="start",
                    )
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=prompt, system_prompt=system_prompt),
                        timeout=60.0
                    )
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        return response.completion_text
                except asyncio.TimeoutError:
                    logger.warning("LLM 生成结束回复超时，将使用默认文案")
                except Exception as e:
                    logger.warning(f"Operation warning: {e}")
            return "我先退到旁边了，有需要再叫我。"

    async def _get_end_response(self, umo: str = None) -> str:
        """生成结束陪伴时的回复。"""
        mode = "llm" if self.use_llm_for_start_end else "preset"
        if mode == "preset" or (hasattr(mode, 'value') and mode.value == "preset"):
            return self.end_preset
        else:
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt(umo)
                    prompt = self._build_end_response_prompt()
                    response = await asyncio.wait_for(
                        provider.text_chat(prompt=prompt, system_prompt=system_prompt),
                        timeout=60.0
                    )
                    if response and hasattr(response, "completion_text") and response.completion_text:
                        return response.completion_text
                except asyncio.TimeoutError:
                    logger.warning("LLM 生成结束回复超时")
                except Exception as e:
                    logger.warning(f"Operation warning: {e}")
            return "我先不打扰你了，等你需要时我再过来。"

    def _generate_diary_image(self, diary_message: str) -> str:
        """将日记文本渲染为图片文件。"""
        from PIL import Image, ImageDraw, ImageFont
        import tempfile

        # 优化字体大小和行高
        font_size = 18
        line_height = int(font_size * 1.8)
        title_font_size = 24
        padding = 60
        max_width = 850

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

        # 加载正文字体
        font = None
        for font_path in chinese_fonts:
            try:
                font = ImageFont.truetype(font_path, font_size)
                test_draw = ImageDraw.Draw(Image.new('RGB', (100, 100)))
                test_draw.text((0, 0), "娴嬭瘯涓枃", font=font)
                break
            except Exception:
                continue

        # 加载标题字体
        title_font = None
        for font_path in chinese_fonts:
            try:
                title_font = ImageFont.truetype(font_path, title_font_size)
                break
            except Exception:
                continue

        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        if title_font is None:
            title_font = font

        def get_text_width(text, use_title_font=False):
            if use_title_font and title_font:
                return title_font.getlength(text)
            elif font:
                return font.getlength(text)
            return len(text) * font_size

        lines = []
        max_text_width = max_width - padding * 2
        title_count = 0  # 统计标题行数量
        
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
                if current_line.startswith("#") and "日记" in current_line:
                    title_count += 1

        # 计算总高度，并为标题额外留白
        title_extra_height = title_count * 10  # 每个标题增加 10 像素
        total_height = padding * 2 + len(lines) * line_height + title_extra_height + 30
        total_height = max(400, total_height)  # 增加最小高度
        # 优化背景色和边框
        image = Image.new('RGB', (max_width, total_height), color=(255, 254, 250))
        draw = ImageDraw.Draw(image)

        # 绘制更柔和的边框
        border_color = (180, 160, 140)
        border_width = 3
        border_padding = 15
        draw.rectangle(
            [(padding - border_padding, padding - border_padding), (max_width - padding + border_padding, total_height - padding + border_padding)],
            outline=border_color,
            width=border_width
        )

        # Draw a simple divider line under the title area
        draw.line(
            [(padding, padding + 40), (max_width - padding, padding + 40)],
            fill=border_color,
            width=1
        )

        y = padding
        for line in lines:
            if line.startswith("#") and "日记" in line:
                # 标题居中显示
                title_width = get_text_width(line, use_title_font=True)
                title_x = (max_width - title_width) // 2
                draw.text((title_x, y), line, fill=(139, 69, 19), font=title_font)
                y += line_height + 10  # 标题行使用更大的行高
            elif line and line[0].isdigit() and "年" in line:
                # 日期居中显示
                date_width = get_text_width(line)
                date_x = (max_width - date_width) // 2
                draw.text((date_x, y), line, fill=(100, 100, 100), font=font)
                y += line_height + 5
            else:
                # 正文左对齐，首段额外缩进
                if line.strip():
                    if len(lines) > 0 and lines.index(line) > 0 and lines[lines.index(line) - 1].strip() == '':
                        # 首行缩进
                        draw.text((padding + 20, y), line, fill=(60, 60, 60), font=font)
                    else:
                        draw.text((padding, y), line, fill=(60, 60, 60), font=font)
                y += line_height

        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        image.save(temp_file, format="PNG", quality=95)
        temp_file.close()

        return temp_file.name

    async def _capture_screen_bytes(self, *, force_fresh_capture: bool = False):
        """返回截图字节流与来源标签。"""

        def _core_task():
            import os
            from PIL import Image

            shared_dir_enabled = self._get_runtime_flag("use_shared_screenshot_dir")
            configured_shared_dir = str(getattr(self, "shared_screenshot_dir", "") or "").strip()
            force_live_capture = bool(force_fresh_capture)

            def resolve_shared_screenshot_dir() -> str:
                if configured_shared_dir:
                    return os.path.normpath(configured_shared_dir)

                env_dir = str(os.environ.get("SCREENSHOT_DIR") or "").strip()
                if env_dir:
                    return os.path.normpath(env_dir)

                current_dir = os.path.dirname(os.path.abspath(__file__))
                return os.path.normpath(os.path.join(current_dir, "..", "..", "screenshots"))

            def persist_shared_screenshot(image_bytes: bytes) -> None:
                if not shared_dir_enabled:
                    return

                screenshots_dir = resolve_shared_screenshot_dir()
                try:
                    os.makedirs(screenshots_dir, exist_ok=True)
                    timestamp = int(time.time())
                    target_path = os.path.join(screenshots_dir, f"screenshot_{timestamp}.jpg")
                    latest_path = os.path.join(screenshots_dir, "screenshot_latest.jpg")
                    with open(target_path, "wb") as f:
                        f.write(image_bytes)
                    with open(latest_path, "wb") as f:
                        f.write(image_bytes)
                except Exception as e:
                    logger.warning(f"写入共享截图目录失败: {e}")

            def get_active_window_info():
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

            def encode_image_to_jpeg_bytes(image):
                if image.mode != "RGB":
                    image = image.convert("RGB")
                img_byte_arr = io.BytesIO()
                quality_val = self.image_quality
                try:
                    quality = max(10, min(100, int(quality_val)))
                except (ValueError, TypeError):
                    quality = 70
                image.save(img_byte_arr, format="JPEG", quality=quality)
                return img_byte_arr.getvalue()

            def capture_live_screenshot():
                import pyautogui

                active_title, active_region = self._get_active_window_info()
                screenshot = None

                if self.capture_active_window and active_region:
                    try:
                        screenshot = pyautogui.screenshot(region=active_region)
                    except Exception as e:
                        logger.warning(f"活动窗口截图失败，将回退为全屏截图: {e}")

                if screenshot is None:
                    screenshot = pyautogui.screenshot()

                source_label = active_title or ("活动窗口截图" if self.capture_active_window else "实时截图")
                image_bytes = encode_image_to_jpeg_bytes(screenshot)
                persist_shared_screenshot(image_bytes)
                return image_bytes, source_label

            if not shared_dir_enabled:
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.error(f"实时截图失败: {e}")
                    raise

            if force_live_capture:
                try:
                    logger.info("当前识屏请求要求优先抓取最新截图，开始立即实时截图")
                    return capture_live_screenshot()
                except Exception as e:
                    logger.warning(f"立即实时截图失败，将回退到共享截图目录: {e}")

            screenshots_dir = resolve_shared_screenshot_dir()

            if not os.path.exists(screenshots_dir):
                logger.warning(f"共享截图目录不存在，将回退为实时截图: {screenshots_dir}")
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.error(f"实时截图失败: {e}")
                    raise
            
            # 获取所有截图文件
            screenshot_files = [f for f in os.listdir(screenshots_dir) if f.startswith("screenshot_") and f.endswith(".jpg")]
            
            if not screenshot_files:
                logger.warning("共享截图目录中没有可用截图，将回退为实时截图")
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.error(f"实时截图失败: {e}")
                    raise

            screenshot_candidates = []
            for filename in screenshot_files:
                screenshot_path = os.path.join(screenshots_dir, filename)
                try:
                    stat = os.stat(screenshot_path)
                    screenshot_candidates.append((stat.st_mtime, filename, screenshot_path))
                except OSError as e:
                    logger.debug(f"读取截图文件信息失败 {screenshot_path}: {e}")

            if not screenshot_candidates:
                logger.warning("没有找到可读取的共享截图，将回退为实时截图")
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.error(f"实时截图失败: {e}")
                    raise

            screenshot_candidates.sort(key=lambda item: item[0], reverse=True)
            latest_mtime, latest_screenshot, screenshot_path = screenshot_candidates[0]
            screenshot_age = max(0.0, time.time() - float(latest_mtime))

            if screenshot_age > 20:
                logger.warning(
                    f"最新共享截图已过期 {screenshot_age:.1f} 秒: {screenshot_path}，将优先尝试实时截图"
                )
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.warning(f"实时截图失败，将回退到共享截图: {e}")

            logger.info(
                f"使用最新截图: {screenshot_path} (mtime={datetime.datetime.fromtimestamp(latest_mtime).isoformat(timespec='seconds')})"
            )

            # 读取截图文件
            try:
                with Image.open(screenshot_path) as screenshot:
                    screenshot.load()
                    return encode_image_to_jpeg_bytes(screenshot), f"共享截图:{latest_screenshot}"
            except Exception as e:
                logger.error(f"读取截图文件失败: {e}")
                try:
                    return capture_live_screenshot()
                except Exception as e:
                    logger.error(f"实时截图失败: {e}")
                    raise

        result = await asyncio.to_thread(_core_task)
        return result

    async def _capture_recording_context(self) -> dict[str, Any]:
        self._ensure_recording_runtime_state()
        clip_active_window_title, _ = await asyncio.to_thread(self._get_active_window_info)

        async with self._screen_recording_lock:
            current_path = str(getattr(self, "_screen_recording_path", "") or "")
            current_process = getattr(self, "_screen_recording_process", None)
            if not current_path:
                await asyncio.to_thread(self._start_screen_recording_sync)
                await asyncio.sleep(1.5)
                current_path = str(getattr(self, "_screen_recording_path", "") or "")
                current_process = getattr(self, "_screen_recording_process", None)

            if current_process and current_process.poll() is None:
                video_path = await asyncio.to_thread(self._stop_screen_recording_sync)
            else:
                video_path = current_path

            if not video_path or not os.path.exists(video_path):
                await asyncio.to_thread(self._start_screen_recording_sync)
                raise RuntimeError("录屏文件尚未准备好，请稍后再试一次。")

            def _read_video_bytes() -> bytes:
                with open(video_path, "rb") as f:
                    return f.read()

            video_bytes = await asyncio.to_thread(_read_video_bytes)
            if not video_bytes:
                await asyncio.to_thread(self._start_screen_recording_sync)
                raise RuntimeError("录屏文件为空，请稍后再试一次。")

            if self.save_local:
                try:
                    data_dir = self.plugin_config.data_dir
                    data_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(video_path, str(data_dir / "screen_record_latest.mp4"))
                except Exception as e:
                    logger.error(f"保存录屏文件失败: {e}")

            await asyncio.to_thread(self._start_screen_recording_sync)
            await asyncio.to_thread(self._cleanup_recording_cache)

        latest_image_bytes, latest_window_title, active_window_title = (
            await self._capture_latest_screen_anchor(
                fallback_window_title=clip_active_window_title
            )
        )
        return {
            "media_kind": "video",
            "mime_type": "video/mp4",
            "media_bytes": video_bytes,
            "active_window_title": active_window_title,
            "clip_active_window_title": clip_active_window_title,
            "latest_window_title": latest_window_title,
            "latest_image_bytes": latest_image_bytes,
            "duration_seconds": self._get_recording_duration_seconds(),
            "source_label": active_window_title or "最近一段桌面录屏",
        }

    async def _capture_screenshot_context(
        self,
        *,
        force_fresh_capture: bool = False,
    ) -> dict[str, Any]:
        image_bytes, active_window_title = await self._capture_screen_bytes(
            force_fresh_capture=force_fresh_capture
        )
        return {
            "media_kind": "image",
            "mime_type": "image/jpeg",
            "media_bytes": image_bytes,
            "active_window_title": active_window_title,
            "source_label": active_window_title,
        }

    async def _capture_latest_screen_anchor(
        self,
        *,
        fallback_window_title: str = "",
        force_fresh_capture: bool = False,
    ) -> tuple[bytes, str, str]:
        latest_image_bytes = b""
        latest_window_title = ""
        active_window_title = self._normalize_window_title(fallback_window_title)
        try:
            latest_image_bytes, latest_window_title = await self._capture_screen_bytes(
                force_fresh_capture=force_fresh_capture
            )
            active_window_title = (
                self._normalize_window_title(latest_window_title)
                or active_window_title
            )
        except Exception as e:
            logger.debug(f"录屏后补抓当前截图失败: {e}")
        return latest_image_bytes, latest_window_title, active_window_title

    async def _capture_one_shot_recording_context(
        self, duration_seconds: int | None = None
    ) -> dict[str, Any]:
        self._ensure_recording_runtime_state()
        clip_active_window_title, _ = await asyncio.to_thread(self._get_active_window_info)
        duration = max(1, int(duration_seconds or self._get_recording_duration_seconds()))

        async with self._screen_recording_lock:
            await asyncio.to_thread(self._stop_screen_recording_sync)
            video_path = await asyncio.to_thread(self._record_screen_clip_sync, duration)

        try:
            def _read_video_bytes() -> bytes:
                with open(video_path, "rb") as f:
                    return f.read()

            video_bytes = await asyncio.to_thread(_read_video_bytes)
            if not video_bytes:
                raise RuntimeError("\u5355\u6b21\u5f55\u5c4f\u6587\u4ef6\u4e3a\u7a7a\uff0c\u8bf7\u7a0d\u540e\u518d\u8bd5\u4e00\u6b21\u3002")

            if self.save_local:
                try:
                    data_dir = self.plugin_config.data_dir
                    data_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(video_path, str(data_dir / "screen_record_latest.mp4"))
                except Exception as e:
                    logger.error(f"\u4fdd\u5b58\u5355\u6b21\u5f55\u5c4f\u6587\u4ef6\u5931\u8d25: {e}")

            latest_image_bytes, latest_window_title, active_window_title = (
                await self._capture_latest_screen_anchor(
                    fallback_window_title=clip_active_window_title,
                    force_fresh_capture=True,
                )
            )

            return {
                "media_kind": "video",
                "mime_type": "video/mp4",
                "media_bytes": video_bytes,
                "active_window_title": active_window_title,
                "clip_active_window_title": clip_active_window_title,
                "latest_window_title": latest_window_title,
                "latest_image_bytes": latest_image_bytes,
                "duration_seconds": duration,
                "source_label": active_window_title
                or "\u624b\u52a8\u5f55\u5236\u7684\u6700\u8fd1 10 \u79d2\u684c\u9762\u5f55\u5c4f",
            }
        finally:
            try:
                if os.path.exists(video_path):
                    os.remove(video_path)
            except OSError:
                pass

    async def _capture_recognition_context(
        self,
        *,
        force_fresh_capture: bool = False,
        force_fresh_recording: bool = False,
    ) -> dict[str, Any]:
        if self._use_screen_recording_mode():
            if force_fresh_recording:
                return await self._capture_one_shot_recording_context(
                    self._get_recording_duration_seconds()
                )
            return await self._capture_recording_context()

        return await self._capture_screenshot_context(
            force_fresh_capture=force_fresh_capture
        )

    async def _capture_proactive_recognition_context(self) -> dict[str, Any]:
        if self._use_screen_recording_mode():
            return await self._capture_one_shot_recording_context(
                self._get_recording_duration_seconds()
            )

        return await self._capture_screenshot_context()

    async def _call_external_vision_api(
        self,
        media_bytes: bytes,
        media_kind: str = "image",
        mime_type: str = "image/jpeg",
        scene: str = "",
        active_window_title: str = "",
    ) -> str:
        """调用外部视觉 API 进行图像分析。"""
        import aiohttp

        # 构建请求数据
        base64_data = base64.b64encode(media_bytes).decode("utf-8")
        image_prompt = self._build_vision_prompt(scene, active_window_title)
        if media_kind == "video":
            image_prompt = (
                "以下为用户当前桌面录屏视频（最近约10秒），你可以参考此内容判断用户正在做什么、进行到哪一步、画面里的关键线索或异常，并给出最值得的一条建议。\n"
                f"{image_prompt}"
            )

        # 定义API调用函数
        async def call_api(api_url, api_key, api_model):
            if not api_url:
                return None, "未配置视觉 API 地址"

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
                                    "url": f"data:{mime_type};base64,{base64_data}"
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
            max_retries = 2  # 减少重试次数，避免总超时时间过长
            retry_delay = 1  # 秒，减少重试间隔
            for attempt in range(max_retries):
                try:
                    # 发送请求，并设置合理的超时
                    timeout = aiohttp.ClientTimeout(total=60.0)  # 增加超时时间，给视觉API更多响应时间
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(
                            api_url, json=payload, headers=headers
                        ) as response:
                            if response.status == 200:
                                result = await response.json()
                                if "choices" in result and len(result["choices"]) > 0:
                                    choice = result["choices"][0]
                                    if "message" in choice and "content" in choice["message"]:
                                        return choice["message"]["content"], None
                                    elif "text" in choice:
                                        return choice["text"], None
                                elif "response" in result:
                                    return result["response"], None
                                else:
                                    return None, "我刚才没能顺利读出画面内容。"
                            else:
                                error_text = await response.text()
                                logger.error(
                                    f"视觉 API 调用失败 (尝试 {attempt+1}/{max_retries}): {response.status} - {error_text}"
                                )
                                if attempt < max_retries - 1:
                                    logger.info(f"等待 {retry_delay} 秒后重试...")
                                    await asyncio.sleep(retry_delay)
                                    retry_delay *= 2
                                else:
                                    return None, "刚才没看清，我们再试一次？"
                except asyncio.TimeoutError:
                    logger.error(f"Vision API timeout (attempt {attempt+1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        return None, "网络刚才有点卡，我们再试一次？"
                except Exception as e:
                    logger.error(f"调用视觉 API 异常 (尝试 {attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        return None, "这次视觉分析没有成功，再给我一次机会。"

        # 获取主API配置
        main_api_url = self.vision_api_url
        main_api_key = self.vision_api_key
        main_api_model = self.vision_api_model

        # 首先尝试主API
        logger.info("尝试使用主视觉API")
        result, error = await call_api(main_api_url, main_api_key, main_api_model)
        if result:
            return result

        # 主API失败，尝试备用API
        backup_api_url = getattr(self, 'vision_api_url_backup', None)
        backup_api_key = getattr(self, 'vision_api_key_backup', None)
        backup_api_model = getattr(self, 'vision_api_model_backup', None)

        if backup_api_url:
            logger.info("主视觉API失败，尝试使用备用视觉API")
            result, error = await call_api(backup_api_url, backup_api_key, backup_api_model)
            if result:
                return result

        # 所有API都失败
        logger.error("所有视觉API调用都失败了")
        return error if error else "视觉分析服务暂时不可用，请稍后再试。"

    @staticmethod
    def _build_data_url(media_bytes: bytes, mime_type: str) -> str:
        base64_data = base64.b64encode(media_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{base64_data}"

    def _get_astrbot_config_candidates(self) -> list[str]:
        home_dir = os.path.expanduser("~")
        data_dir = os.path.join(home_dir, ".astrbot", "data")
        candidates = [
            os.path.join(data_dir, "cmd_config.json"),
        ]

        config_dir = os.path.join(data_dir, "config")
        if os.path.isdir(config_dir):
            try:
                abconf_files = [
                    os.path.join(config_dir, name)
                    for name in os.listdir(config_dir)
                    if name.startswith("abconf_") and name.endswith(".json")
                ]
                abconf_files.sort(
                    key=lambda path: os.path.getmtime(path),
                    reverse=True,
                )
                candidates = abconf_files + candidates
            except Exception as e:
                logger.debug(f"读取 AstrBot 配置列表失败: {e}")

        return candidates

    def _load_astrbot_provider_registry(self) -> dict[str, Any]:
        for path in self._get_astrbot_config_candidates():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and (
                    isinstance(data.get("provider"), list)
                    or isinstance(data.get("provider_sources"), list)
                ):
                    return data
            except Exception as e:
                logger.debug(f"读取 AstrBot provider 配置失败 {path}: {e}")
        return {}

    def _get_astrbot_image_caption_settings(self) -> dict[str, str]:
        registry = self._load_astrbot_provider_registry()
        provider_settings = registry.get("provider_settings", {}) or {}
        provider_ltm_settings = registry.get("provider_ltm_settings", {}) or {}

        provider_id = str(
            provider_settings.get("default_image_caption_provider_id", "") or ""
        ).strip()
        if not provider_id and self._coerce_bool(
            provider_ltm_settings.get("image_caption", False)
        ):
            provider_id = str(
                provider_ltm_settings.get("image_caption_provider_id", "") or ""
            ).strip()
        if not provider_id:
            provider_id = str(registry.get("image_caption_provider_id", "") or "").strip()

        prompt = str(provider_settings.get("image_caption_prompt", "") or "").strip()
        if not prompt:
            prompt = str(registry.get("image_caption_prompt", "") or "").strip()

        return {
            "provider_id": provider_id,
            "prompt": prompt,
        }

    @staticmethod
    def _looks_like_gemini_model(model_name: str) -> bool:
        return "gemini" in str(model_name or "").strip().lower()

    @staticmethod
    def _is_official_gemini_api_base(api_base: str) -> bool:
        normalized = str(api_base or "").strip().lower()
        return "generativelanguage.googleapis.com" in normalized

    async def _get_current_chat_provider_id(self, umo: str | None = None) -> str:
        try:
            getter = getattr(self.context, "get_current_chat_provider_id", None)
            if getter:
                provider_id = await getter(umo=umo)
                return str(provider_id or "").strip()
        except Exception as e:
            logger.debug(f"获取当前聊天 provider_id 失败: {e}")
        return ""

    async def _supports_native_gemini_video_audio(
        self,
        *,
        provider=None,
        umo: str | None = None,
    ) -> bool:
        try:
            provider_id = await self._get_current_chat_provider_id(umo=umo)
            runtime = self._resolve_provider_runtime_info(
                provider_id=provider_id,
                provider=provider,
            )
            model_name = str(runtime.get("model", "") or "").strip()
            api_key = str(runtime.get("api_key", "") or "").strip()
            api_base = str(runtime.get("api_base", "") or "").strip()
            return bool(
                self._looks_like_gemini_model(model_name)
                and api_key
                and self._is_official_gemini_api_base(api_base)
            )
        except Exception as e:
            logger.debug(f"判断 Gemini 原生视频能力失败: {e}")
            return False

    async def _call_astrbot_image_caption_provider(
        self,
        *,
        media_bytes: bytes,
        mime_type: str,
        scene: str,
        active_window_title: str,
    ) -> str:
        settings = self._get_astrbot_image_caption_settings()
        provider_id = str(settings.get("provider_id", "") or "").strip()
        if not provider_id:
            return ""

        getter = getattr(self.context, "get_provider_by_id", None)
        if not callable(getter):
            logger.debug("当前 AstrBot context 不支持 get_provider_by_id，跳过图片转述 provider")
            return ""

        provider = None
        try:
            provider = getter(provider_id)
        except Exception as e:
            logger.debug(f"获取图片转述 provider 失败 {provider_id}: {e}")
            return ""

        if not provider:
            logger.warning(f"找不到 AstrBot 图片转述 provider: {provider_id}")
            return ""

        data_url = self._build_data_url(media_bytes, mime_type)
        base_prompt = self._build_vision_prompt(scene, active_window_title)
        caption_prompt = str(settings.get("prompt", "") or "").strip()
        prompt_parts = []
        if caption_prompt:
            prompt_parts.append(caption_prompt)
        if base_prompt and base_prompt not in prompt_parts:
            prompt_parts.append(base_prompt)
        prompt = "\n\n".join(part for part in prompt_parts if part).strip()
        if not prompt:
            prompt = "请用中文简洁描述这张图片内容。"

        try:
            response = await asyncio.wait_for(
                provider.text_chat(
                    prompt=prompt,
                    image_urls=[data_url],
                ),
                timeout=60.0,
            )
        except Exception as e:
            logger.warning(f"AstrBot 图片转述 provider 调用失败 {provider_id}: {e}")
            return ""

        completion_text = str(
            getattr(response, "completion_text", "") or getattr(response, "text", "") or ""
        ).strip()
        if completion_text:
            logger.info(f"已使用 AstrBot 图片转述 provider 识屏: {provider_id}")
        return completion_text

    def _resolve_provider_runtime_info(
        self,
        provider_id: str = "",
        provider=None,
    ) -> dict[str, Any]:
        registry = self._load_astrbot_provider_registry()
        provider_entries = registry.get("provider", []) or []
        provider_sources = registry.get("provider_sources", []) or []
        provider_settings = registry.get("provider_settings", {}) or {}

        current_provider_id = str(provider_id or "").strip()
        if not current_provider_id:
            current_provider_id = str(
                provider_settings.get("default_provider_id", "") or ""
            ).strip()

        model_name = ""
        provider_entry = None
        if current_provider_id:
            provider_entry = next(
                (
                    item
                    for item in provider_entries
                    if str(item.get("id", "") or "").strip() == current_provider_id
                ),
                None,
            )

        if provider_entry is None and provider is not None:
            for attr_name in ("model", "model_name", "provider_id", "id"):
                attr_value = getattr(provider, attr_name, None)
                if not attr_value:
                    continue
                attr_str = str(attr_value).strip()
                if not model_name:
                    model_name = attr_str
                matched = next(
                    (
                        item
                        for item in provider_entries
                        if attr_str
                        and (
                            str(item.get("id", "") or "").strip() == attr_str
                            or str(item.get("model", "") or "").strip() == attr_str
                        )
                    ),
                    None,
                )
                if matched is not None:
                    provider_entry = matched
                    current_provider_id = str(matched.get("id", "") or "").strip()
                    break

        if provider_entry is not None and not model_name:
            model_name = str(provider_entry.get("model", "") or "").strip()

        provider_source_id = ""
        api_base = ""
        api_key = ""
        if provider_entry is not None:
            provider_source_id = str(provider_entry.get("provider_source_id", "") or "").strip()
            source_entry = next(
                (
                    item
                    for item in provider_sources
                    if str(item.get("id", "") or "").strip() == provider_source_id
                ),
                None,
            )
            if source_entry:
                api_base = str(source_entry.get("api_base", "") or "").strip()
                key_list = source_entry.get("key", []) or []
                if key_list:
                    api_key = str(key_list[0] or "").strip()

        env_api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
        env_api_base = str(os.environ.get("GEMINI_API_BASE") or "").strip()
        if env_api_key:
            api_key = env_api_key
        if env_api_base:
            api_base = env_api_base

        if not api_base and api_key and self._looks_like_gemini_model(model_name):
            api_base = self.GEMINI_API_BASE

        return {
            "provider_id": current_provider_id,
            "model": model_name,
            "api_base": api_base,
            "api_key": api_key,
            "provider_source_id": provider_source_id,
        }

    async def _gemini_upload_file(
        self,
        *,
        api_base: str,
        api_key: str,
        media_bytes: bytes,
        mime_type: str,
        display_name: str,
    ) -> dict[str, Any]:
        import aiohttp

        start_headers = {
            "x-goog-api-key": api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(media_bytes)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        }
        start_payload = {"file": {"display_name": display_name}}
        start_url = f"{api_base.rstrip('/')}/upload/v1beta/files"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                start_url,
                headers=start_headers,
                json=start_payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                response.raise_for_status()
                upload_url = response.headers.get("X-Goog-Upload-URL") or response.headers.get(
                    "x-goog-upload-url"
                )
                if not upload_url:
                    raise RuntimeError("Gemini Files API 未返回上传地址。")

            upload_headers = {
                "x-goog-api-key": api_key,
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Length": str(len(media_bytes)),
            }
            async with session.post(
                upload_url,
                headers=upload_headers,
                data=media_bytes,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as response:
                response.raise_for_status()
                result = await response.json()
        return result.get("file", result)

    async def _gemini_wait_file_active(
        self,
        *,
        api_base: str,
        api_key: str,
        file_name: str,
    ) -> dict[str, Any]:
        import aiohttp

        endpoint = file_name if str(file_name).startswith("files/") else f"files/{file_name}"
        url = f"{api_base.rstrip('/')}/v1beta/{endpoint}"
        deadline = time.time() + float(self.GEMINI_FILE_POLL_TIMEOUT_SECONDS)

        async with aiohttp.ClientSession() as session:
            while time.time() < deadline:
                async with session.get(
                    url,
                    headers={"x-goog-api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                state = str(
                    ((result.get("state") or {}) if isinstance(result.get("state"), dict) else {})
                    .get("name", result.get("state", ""))
                    or ""
                ).upper()
                if state == "ACTIVE":
                    return result
                if state == "FAILED":
                    raise RuntimeError("Gemini Files API 处理视频失败。")
                await asyncio.sleep(self.GEMINI_FILE_POLL_INTERVAL_SECONDS)

        raise RuntimeError("Gemini Files API 处理视频超时。")

    async def _gemini_delete_file(
        self,
        *,
        api_base: str,
        api_key: str,
        file_name: str,
    ) -> None:
        import aiohttp

        endpoint = file_name if str(file_name).startswith("files/") else f"files/{file_name}"
        url = f"{api_base.rstrip('/')}/v1beta/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    url,
                    headers={"x-goog-api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status not in {200, 204}:
                        logger.debug(f"删除 Gemini 临时文件失败: HTTP {response.status}")
        except Exception as e:
            logger.debug(f"删除 Gemini 临时文件失败: {e}")

    @staticmethod
    def _extract_text_from_gemini_response(payload: dict[str, Any]) -> str:
        parts: list[str] = []
        for candidate in payload.get("candidates", []) or []:
            content = candidate.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = str(part.get("text", "") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    async def _call_native_gemini_multimodal(
        self,
        *,
        provider_id: str,
        provider,
        interaction_prompt: str,
        system_prompt: str,
        media_bytes: bytes,
        media_kind: str,
        mime_type: str,
    ):
        import aiohttp

        runtime = self._resolve_provider_runtime_info(provider_id=provider_id, provider=provider)
        model_name = str(runtime.get("model", "") or "").strip()
        api_key = str(runtime.get("api_key", "") or "").strip()
        api_base = str(runtime.get("api_base", "") or "").strip()

        if not (
            self._looks_like_gemini_model(model_name)
            and api_key
            and self._is_official_gemini_api_base(api_base)
        ):
            return None

        if not interaction_prompt.strip():
            raise RuntimeError("Gemini 原生多模态调用缺少提示词。")

        uploaded_file_name = ""
        try:
            if media_kind == "video":
                uploaded_file = await self._gemini_upload_file(
                    api_base=api_base,
                    api_key=api_key,
                    media_bytes=media_bytes,
                    mime_type=mime_type,
                    display_name=f"screen-companion-{uuid.uuid4()}.mp4",
                )
                uploaded_file_name = str(uploaded_file.get("name", "") or "").strip()
                file_info = await self._gemini_wait_file_active(
                    api_base=api_base,
                    api_key=api_key,
                    file_name=uploaded_file_name,
                )
                media_part = {
                    "file_data": {
                        "mime_type": mime_type,
                        "file_uri": str(file_info.get("uri", "") or "").strip(),
                    }
                }
            else:
                media_part = {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64.b64encode(media_bytes).decode("utf-8"),
                    }
                }

            payload: dict[str, Any] = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            media_part,
                            {"text": interaction_prompt},
                        ],
                    }
                ]
            }
            if system_prompt.strip():
                payload["system_instruction"] = {
                    "parts": [{"text": system_prompt}],
                }

            url = f"{api_base.rstrip('/')}/v1beta/models/{model_name}:generateContent"
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=180),
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

            response_text = self._extract_text_from_gemini_response(result)
            if not response_text:
                raise RuntimeError("Gemini 原生多模态返回为空。")
            return SimpleNamespace(completion_text=response_text)
        finally:
            if uploaded_file_name:
                await self._gemini_delete_file(
                    api_base=api_base,
                    api_key=api_key,
                    file_name=uploaded_file_name,
                )

    async def _call_provider_multimodal_direct(
        self,
        provider,
        interaction_prompt: str,
        system_prompt: str,
        media_bytes: bytes,
        media_kind: str = "image",
        mime_type: str = "image/jpeg",
        provider_id: str = "",
    ):
        native_response = await self._call_native_gemini_multimodal(
            provider_id=provider_id,
            provider=provider,
            interaction_prompt=interaction_prompt,
            system_prompt=system_prompt,
            media_bytes=media_bytes,
            media_kind=media_kind,
            mime_type=mime_type,
        )
        if native_response is not None:
            return native_response

        if media_kind == "video" and not self._coerce_bool(
            getattr(self, "allow_unsafe_video_direct_fallback", False)
        ):
            raise RuntimeError(
                "当前 provider 不支持原生视频上传，已拦截视频直发以避免过度消耗 token。"
                "请开启外部视觉 API，或切换到官方 Gemini API 并配置 GEMINI_API_KEY。"
            )
        if media_kind == "video":
            logger.warning(
                "当前 provider 不支持原生视频上传，但已按配置允许回退到兼容视频直发。"
                "这可能导致请求体很大，并带来较高的 token 消耗。"
            )

        data_url = self._build_data_url(media_bytes, mime_type)
        multimodal_contexts = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": interaction_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ]

        def _looks_like_context_image_payload_error(error: Exception) -> bool:
            error_text = str(error or "").lower()
            if not error_text:
                return False
            markers = (
                "image_url",
                "unknown variant",
                "failed to deserialize",
                "invalid_request_error",
                "messages[",
                "expected `text`",
                "expected 'text'",
            )
            return any(marker in error_text for marker in markers)

        try:
            return await provider.text_chat(
                prompt="",
                system_prompt=system_prompt,
                contexts=multimodal_contexts,
            )
        except TypeError:
            if media_kind == "image":
                return await provider.text_chat(
                    prompt=interaction_prompt,
                    system_prompt=system_prompt,
                    image_urls=[data_url],
                )
            raise RuntimeError(
                "当前 AstrBot provider 不支持直接视频多模态上下文，请开启外部视觉 API。"
            )
        except Exception as e:
            if media_kind == "image" and _looks_like_context_image_payload_error(e):
                logger.warning(
                    "当前 provider 的多模态 contexts 载荷未被后端接受，"
                    "正在改用 image_urls 方式重试图片识别。"
                )
                return await provider.text_chat(
                    prompt=interaction_prompt,
                    system_prompt=system_prompt,
                    image_urls=[data_url],
                )
            raise

    async def _run_screen_assist(
        self,
        event: AstrMessageEvent,
        task_id: str = "manual",
        custom_prompt: str = "",
        history_user_text: str = "/kp",
        capture_context: dict[str, Any] | None = None,
        capture_timeout: float | None = None,
        analysis_timeout: float | None = None,
    ) -> str | None:
        debug_mode = self.debug
        if debug_mode:
            logger.info(f"[Task {task_id}] status update")

        if capture_context is None:
            effective_capture_timeout = (
                float(capture_timeout)
                if capture_timeout is not None
                else self._get_capture_context_timeout()
            )
            capture_context = await asyncio.wait_for(
                self._capture_recognition_context(),
                timeout=effective_capture_timeout,
            )
        capture_context.setdefault(
            "trigger_reason",
            "用户手动发起识屏请求" if task_id.startswith("manual") or task_id in {"manual", "manual_recording"} else f"任务 {task_id} 发起识屏",
        )
        media_bytes = capture_context["media_bytes"]
        media_kind = str(capture_context.get("media_kind", "image") or "image")
        active_window_title = capture_context.get("active_window_title", "")
        if debug_mode:
            logger.info(
                f"[{task_id}] 识屏素材已准备，模式: {media_kind}, 大小: {len(media_bytes)} bytes, 活动窗口: {active_window_title}"
            )

        effective_analysis_timeout = (
            float(analysis_timeout)
            if analysis_timeout is not None
            else self._get_screen_analysis_timeout(media_kind)
        )
        components = await asyncio.wait_for(
            self._analyze_screen(
                capture_context,
                session=event,
                active_window_title=active_window_title,
                custom_prompt=custom_prompt,
                task_id=task_id,
                user_request_text=history_user_text,
            ),
            timeout=effective_analysis_timeout,
        )
        if debug_mode:
            logger.info(f"[{task_id}] 分析完成，组件数量: {len(components)}")

        if not components or not isinstance(components[0], Plain):
            if debug_mode:
                logger.warning(f"[{task_id}] 未获取到有效识别结果")
            return None

        screen_result = components[0].text
        if debug_mode:
            logger.info(f"[{task_id}] 屏幕识别结果: {screen_result}")
        try:
            self._remember_recent_assistant_reply(
                str(getattr(event, "unified_msg_origin", "") or ""),
                screen_result,
            )
        except Exception as e:
            if debug_mode:
                logger.debug(f"[{task_id}] 记录最近助手回复失败: {e}")

        try:
            from astrbot.core.agent.message import (
                AssistantMessageSegment,
                TextPart,
                UserMessageSegment,
            )

            if hasattr(self.context, "conversation_manager"):
                conv_mgr = self.context.conversation_manager
                uid = event.unified_msg_origin
                curr_cid = await conv_mgr.get_curr_conversation_id(uid)

                if curr_cid:
                    user_msg = UserMessageSegment(
                        content=[TextPart(text=str(history_user_text or "/kp"))]
                    )
                    assistant_msg = AssistantMessageSegment(
                        content=[TextPart(text=screen_result)]
                    )
                    await conv_mgr.add_message_pair(
                        cid=curr_cid,
                        user_message=user_msg,
                        assistant_message=assistant_msg,
                    )
                    if debug_mode:
                        logger.info(f"[Task {task_id}] status update")
        except Exception as e:
            if debug_mode:
                logger.debug(f"[{task_id}] 添加对话历史失败: {e}")

        self._remember_screen_analysis_trace(capture_context.get("_analysis_trace"))
        return screen_result

    def _check_recording_env(self, check_mic: bool = False) -> tuple[bool, str]:
        dep_ok, dep_msg = self._check_dependencies(check_mic=check_mic)
        if not dep_ok:
            return False, dep_msg

        if sys.platform != "win32":
            return False, "\u5f55\u5c4f\u89c6\u9891\u8bc6\u522b\u76ee\u524d\u4ec5\u652f\u6301 Windows \u684c\u9762\u73af\u5883\u3002"

        ffmpeg_path = self._get_ffmpeg_path()
        if not ffmpeg_path:
            return (
                False,
                "\u672a\u68c0\u6d4b\u5230 ffmpeg\uff0c\u8bf7\u5c06 ffmpeg.exe \u653e\u5230\u63d2\u4ef6\u76ee\u5f55\u4e0b\u7684 bin \u6587\u4ef6\u5939\uff0c"
                "\u6216\u5728\u914d\u7f6e\u4e2d\u586b\u5199 ffmpeg_path\uff0c\u6216\u52a0\u5165 PATH\u3002"
            )

        return True, ""

    def _check_screenshot_env(self, check_mic: bool = False) -> tuple[bool, str]:
        dep_ok, dep_msg = self._check_dependencies(check_mic=check_mic)
        if not dep_ok and "ffmpeg" not in str(dep_msg or "").lower():
            return False, dep_msg

        try:
            import pyautogui

            if sys.platform.startswith("linux"):
                if not os.environ.get("DISPLAY") and not os.environ.get(
                    "WAYLAND_DISPLAY"
                ):
                    return (
                        False,
                        "Detected Linux without an available graphical display. Please run it in a desktop session or with X11 forwarding.",
                    )

            size = pyautogui.size()
            if size[0] <= 0 or size[1] <= 0:
                return False, "Unable to capture the screen properly."

            return True, ""
        except Exception as e:
            if self._get_runtime_flag("use_shared_screenshot_dir"):
                shared_dir = str(getattr(self, "shared_screenshot_dir", "") or "").strip()
                if shared_dir:
                    return True, ""
            return False, f"自我检查失败: {str(e)}"

    def _classify_browser_content(self, window_title: str) -> str:
        """根据浏览器窗口标题分类内容类型。"""
        title_lower = window_title.lower()
        
        # 工作相关网站关键词
        work_keywords = [
            "google", "baidu", "bing", "search", "查询", "搜索",
            "github", "gitlab", "coding", "stackoverflow", "stackexchange",
            "docs", "documentation", "wiki", "教程", "guide", "manual",
            "office", "excel", "word", "powerpoint", "spreadsheet", "document",
            "gmail", "outlook", "email", "mail", "邮件",
            "jira", "trello", "asana", "project", "task", "todo",
            "slack", "teams", "discord", "chat", "沟通", "协作",
            "figma", "design", "photoshop", "illustrator", "原型", "设计",
            "analytics", "data", "report", "dashboard", "分析", "报表",
            "code", "programming", "developer", "dev", "编程", "开发",
            "cloud", "aws", "azure", "gcp", "cloudflare", "服务器", "云",
            "crm", "erp", "sap", "salesforce", "客户", "管理",
            "learning", "course", "education", "学习", "课程", "教育"
        ]
        
        # 娱乐相关网站关键词
        entertainment_keywords = [
            "youtube", "bilibili", "netflix", "hulu", "disney+", "视频", "电影", "剧集",
            "music", "spotify", "apple music", "网易云", "qq音乐", "音乐", "歌曲",
            "game", "gaming", "游戏", "steam", "epic", "游戏平台",
            "facebook", "instagram", "twitter", "x", "tiktok", "douyin", "社交", "微博",
            "news", "新闻", "头条", "资讯",
            "shopping", "电商", "淘宝", "京东", "拼多多", "购物", "商城",
            "sports", "体育", "足球", "篮球", "赛事",
            "entertainment", "娱乐", "明星", "综艺",
            "anime", "动画", "漫画", "番剧",
            "porn", "xxx", "色情", "成人"
        ]
        
        # 检查工作相关关键词
        for keyword in work_keywords:
            if keyword in title_lower:
                return "浏览-工作"
        
        # 检查娱乐相关关键词
        for keyword in entertainment_keywords:
            if keyword in title_lower:
                return "浏览-娱乐"
        
        # 默认返回普通浏览
        return "浏览"

    def _identify_scene(self, window_title: str) -> str:
        """Identify a coarse scene label from the current window title."""
        if not window_title:
            return "未知"

        app_scene = infer_scene_from_window_title(window_title)
        if app_scene:
            if app_scene == "浏览":
                return self._classify_browser_content(window_title)
            return app_scene

        title_lower = window_title.lower()

        keyword_groups = {
            "编程": [
                "code", "vscode", "visual studio", "intellij", "pycharm", "idea",
                "eclipse", "sublime", "atom", "notepad++", "vim", "emacs",
                "phpstorm", "webstorm", "goland", "rider", "android studio", "xcode",
                "terminal", "powershell", "cmd", "git", "github", "gitlab", "coding",
                "dev", "developer", "program", "programming", "debug", "compile", "build",
                "python", "java", "c++", "c#", "javascript", "typescript", "html", "css",
                "ide", "editor", "console", "shell", "bash", "zsh", "powershell"
            ],
            "设计": [
                "photoshop", "illustrator", "figma", "sketch", "xd", "gimp", "canva",
                "photopea", "coreldraw", "blender", "maya", "3d", "design",
                "creative", "art", "graphic", "ui", "ux", "wireframe", "prototype",
                "adobe", "affinity", "paint", "draw", "illustration", "animation"
            ],
            "浏览": [
                "chrome", "firefox", "edge", "safari", "opera", "browser", "???",
                "chrome.exe", "firefox.exe", "edge.exe", "safari.exe", "opera.exe",
                "browser", "web", "internet", "chrome", "firefox", "edge", "safari", "opera"
            ],
            "办公": [
                "word", "excel", "powerpoint", "office", "??", "??", "wps", "outlook",
                "office365", "onenote", "access", "project", "visio",
                "document", "spreadsheet", "presentation", "calendar", "task", "todo",
                "work", "office", "business", "report", "data", "analysis", "excel"
            ],
            "游戏": [
                "steam", "epic", "battle.net", "valorant", "csgo", "dota", "minecraft",
                "game", "league", "lol", "overwatch", "fortnite", "pubg", "apex",
                "genshin", "roblox", "warcraft", "diablo", "starcraft", "hearthstone",
                "fifa", "nba", "call of duty", "cod", "assassin's creed", "ac",
                "grand theft auto", "gta", "the witcher", "cyberpunk", "fallout",
                "game", "gaming", "play", "player", "level", "mission", "quest",
                "character", "weapon", "map", "server", "multiplayer", "singleplayer"
            ],
            "视频": [
                "youtube", "bilibili", "netflix", "vlc", "potplayer", "movie", "video", "??",
                "youku", "tudou", "iqiyi", "letv", "mkv", "mp4", "wmv", "avi",
                "media player", "kmplayer", "mplayer",
                "video", "movie", "film", "tv", "show", "series", "episode", "streaming",
                "watch", "player", "media", "video", "movie", "film", "tv", "show"
            ],
            "阅读": [
                "novel", "reader", "ebook", "pdf", "reading", "??", "???", "???",
                "adobe reader", "foxit", "kindle", "ibooks", "epub", "mobi",
                "book", "read", "reading", "novel", "story", "document", "pdf", "epub"
            ],
            "音乐": [
                "spotify", "apple music", "music", "itunes", "?????", "qq??", "musicbee",
                "网易云", "netease", "kuwo", "kugou", "qq music", "winamp", "foobar",
                "music", "song", "audio", "player", "music", "song", "audio", "playlist"
            ],
            "社交": [
                "discord", "wechat", "qq", "skype", "zoom", "teams", "slack",
                "whatsapp", "telegram", "signal", "messenger", "facebook", "instagram",
                "twitter", "x", "linkedin", "tiktok", "douyin",
                "chat", "message", "social", "contact", "friend", "conversation"
            ],
            "邮件": [
                "outlook", "gmail", "mail", "thunderbird", "mailchimp", "protonmail",
                "邮件", "email", "inbox", "mail", "email", "message", "inbox", "outbox"
            ],
            "工具": [
                "calculator", "notepad", "paint", "snip", "snipping", "screenshot",
                "explorer", "finder", "file explorer", "task manager", "control panel",
                "tool", "utility", "app", "application", "program", "software"
            ],
        }

        # 首先尝试精确匹配
        for scene, keywords in keyword_groups.items():
            if any(keyword in title_lower for keyword in keywords):
                # 如果是浏览器场景，进一步分类
                if scene == "浏览":
                    return self._classify_browser_content(window_title)
                return scene

        # 尝试更宽松的匹配，检查窗口标题中是否包含常见的场景相关词汇
        loose_match = {
            "编程": ["代码", "程序", "开发", "debug", "编译", "运行"],
            "设计": ["设计", "创意", "美术", "绘图", "编辑"],
            "办公": ["文档", "表格", "演示", "会议", "工作"],
            "游戏": ["游戏", "游玩", "关卡", "任务", "角色"],
            "视频": ["视频", "电影", "电视", "节目", "播放"],
            "阅读": ["阅读", "书籍", "小说", "文档", "文章"],
            "音乐": ["音乐", "歌曲", "音频", "播放"],
            "社交": ["聊天", "消息", "社交", "联系", "朋友"],
            "邮件": ["邮件", "邮箱", "邮件", "发送", "接收"],
        }

        for scene, keywords in loose_match.items():
            if any(keyword in title_lower for keyword in keywords):
                return scene

        # 最后，根据窗口标题的长度和内容进行判断
        if len(title_lower) > 10:
            # 如果标题较长，可能是浏览器或其他应用
            if any(browser in title_lower for browser in ["chrome", "firefox", "edge", "safari", "opera"]):
                return "浏览"
            elif any(video in title_lower for video in ["youtube", "bilibili", "netflix", "video", "movie"]):
                return "视频"
            elif any(game in title_lower for game in ["game", "steam", "epic"]):
                return "游戏"

        return "未知"

    def _get_time_prompt(self, allow_rest_hint: bool = False) -> str:
        """返回当前时间段对应的语气提示。"""
        now = datetime.datetime.now()
        hour = now.hour

        if 6 <= hour < 12:
            return "当前是早上，语气可以更清醒、轻快一些。"
        elif 12 <= hour < 18:
            return "当前是白天，建议以自然、直接、有帮助为主。"
        elif 18 <= hour < 22:
            return "当前是晚上，语气可以更放松，但建议仍要具体。"
        elif allow_rest_hint:
            return "当前已较晚，尽量低打扰、少用播报式开场；如本轮已明确触发休息提醒，可以顺带轻提一次，其余内容仍以当前任务为主。"
        else:
            return "当前已较晚，尽量低打扰、少用播报式开场；不要仅因为时间较晚就主动催用户休息或反复劝睡。"

    def _get_holiday_prompt(self) -> str:
        """获取节假日提示词。"""
        now = datetime.datetime.now()
        date = now.date()
        month = date.month
        day = date.day
        holidays = {
        }


        if (month, day) in holidays:
            holiday_prompt = holidays[(month, day)]
            logger.info(f"识别到节假日提示: {holiday_prompt}")
            return holiday_prompt
        return ""

    def _get_system_status_prompt(self) -> tuple:
        """获取系统状态提示词。"""
        system_prompt = ""
        system_high_load = False
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            battery = None
            if hasattr(psutil, "sensors_battery"):
                try:
                    battery = psutil.sensors_battery()
                except Exception as battery_error:
                    logger.debug(f"获取电池状态失败: {battery_error}")
            battery_threshold = getattr(self, "battery_threshold", 20)
            if battery and getattr(battery, "percent", None) is not None and battery.percent < battery_threshold:
                system_prompt += " 当前设备电量偏低，若建议涉及长时间操作，请顺手提醒保存进度。"

            memory_threshold = getattr(self, "memory_threshold", 80)
            if cpu_percent > 80 or memory_percent > memory_threshold:
                if system_prompt:
                    system_prompt += " "
                system_prompt += " 当前系统负载较高，请避免建议用户同时做太重的操作。"
                system_high_load = True
                logger.info(
                    f"系统资源使用过高: CPU={cpu_percent}%, 内存={memory_percent}%"
                )
        except ImportError:
            logger.debug("Debug event")
        except Exception as e:
            logger.debug(f"系统状态检测失败: {e}")
        return system_prompt, system_high_load

    async def _get_weather_prompt(self, target_date: datetime.date = None) -> str:
        """获取天气提示词。"""
        weather_prompt = ""
        weather_api_key = self.weather_api_key
        weather_city = self.weather_city

        if weather_api_key and weather_city:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    if target_date:
                        # 获取历史天气
                        timestamp = int(datetime.datetime.combine(target_date, datetime.datetime.min.time()).timestamp())
                        url = f"http://api.openweathermap.org/data/2.5/onecall/timemachine?lat={self.weather_lat}&lon={self.weather_lon}&dt={timestamp}&appid={weather_api_key}&units=metric&lang=zh_cn"
                    else:
                        # 获取当前天气
                        url = f"http://api.openweathermap.org/data/2.5/weather?q={weather_city}&appid={weather_api_key}&units=metric&lang=zh_cn"
                    
                    async with session.get(url) as response:
                        if response.status == 200:
                            weather_data = await response.json()
                            
                            if target_date:
                                # 解析历史天气数据
                                weather_main = weather_data.get("current", {}).get("weather", [{}])[0].get(
                                    "main", ""
                                )
                                weather_desc = weather_data.get("current", {}).get("weather", [{}])[0].get(
                                    "description", ""
                                )
                                temp = weather_data.get("current", {}).get("temp", 0)
                            else:
                                # 解析当前天气数据
                                weather_main = weather_data.get("weather", [{}])[0].get(
                                    "main", ""
                                )
                                weather_desc = weather_data.get("weather", [{}])[0].get(
                                    "description", ""
                                )
                                temp = weather_data.get("main", {}).get("temp", 0)

                            if target_date:
                                weather_prompt = f"当日天气 {weather_desc}，约 {temp}°C。"
                            else:
                                weather_prompt = f"当前天气 {weather_desc}，约 {temp}°C。"
                            
                            logger.info(f"天气信息获取成功: {weather_prompt}")
                        else:
                            logger.debug(f"获取天气信息失败: {response.status}")
            except Exception as e:
                logger.debug(f"天气感知失败: {e}")
        return weather_prompt

    async def _gather_screen_analysis_context(
        self,
        *,
        active_window_title: str,
        debug_mode: bool,
        allow_rest_hint: bool = False,
    ) -> dict[str, str]:
        scene = "未知"
        scene_prompt = ""
        time_prompt = ""
        holiday_prompt = ""
        system_status_prompt = ""
        weather_prompt = ""

        if active_window_title:
            try:
                scene = self._identify_scene(active_window_title)
                scene_prompt = self._get_scene_preference(
                    scene,
                    active_window_title=active_window_title,
                )
            except Exception as e:
                if debug_mode:
                    logger.debug(f"场景识别失败: {e}")

        try:
            time_prompt = self._get_time_prompt(allow_rest_hint=allow_rest_hint)
        except Exception as e:
            if debug_mode:
                logger.debug(f"获取时间提示失败: {e}")

        try:
            holiday_prompt = self._get_holiday_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"获取节日提示失败: {e}")

        try:
            system_status_prompt, _ = self._get_system_status_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"获取系统状态失败: {e}")

        try:
            weather_prompt = await self._get_weather_prompt()
        except Exception as e:
            if debug_mode:
                logger.debug(f"获取天气提示失败: {e}")

        return {
            "scene": scene,
            "scene_prompt": scene_prompt,
            "time_prompt": time_prompt,
            "holiday_prompt": holiday_prompt,
            "system_status_prompt": system_status_prompt,
            "weather_prompt": weather_prompt,
        }

    async def _collect_recent_conversation_context(
        self,
        session=None,
        *,
        debug_mode: bool,
    ) -> list[str]:
        contexts: list[str] = []
        try:
            if not hasattr(self.context, "conversation_manager"):
                return contexts

            conv_mgr = self.context.conversation_manager
            uid = ""
            try:
                uid = session.unified_msg_origin if session else ""
            except Exception as e:
                if debug_mode:
                    logger.debug(f"读取会话 UID 失败: {e}")

            if not uid:
                return contexts

            try:
                curr_cid = await conv_mgr.get_curr_conversation_id(uid)
                if curr_cid:
                    conversation = await conv_mgr.get_conversation(uid, curr_cid)
                    if conversation and conversation.history:
                        for msg in conversation.history[-8:]:
                            if msg.get("role") in {"user", "assistant"}:
                                content = str(msg.get("content", "") or "").strip()
                                if content:
                                    role = "用户" if msg.get("role") == "user" else "助手"
                                    contexts.append(f"{role}: {content}")
            except Exception as e:
                if debug_mode:
                    logger.debug(f"读取对话上下文失败: {e}")
        except Exception as e:
            if debug_mode:
                logger.debug(f"收集上下文失败: {e}")
        return contexts

    async def _recognize_screen_material(
        self,
        *,
        capture_context: dict[str, Any],
        use_external_vision: bool,
        scene: str,
        active_window_title: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "text": "",
            "used_text_pipeline": False,
            "source": "",
        }

        media_kind = str(capture_context.get("media_kind", "image") or "image")
        mime_type = str(capture_context.get("mime_type", "image/jpeg") or "image/jpeg")
        media_bytes = capture_context.get("media_bytes", b"") or b""

        if media_kind == "image" and media_bytes:
            recognition_text = await self._call_astrbot_image_caption_provider(
                media_bytes=media_bytes,
                mime_type=mime_type,
                scene=scene,
                active_window_title=active_window_title,
            )
            recognition_text = self._compress_recognition_text(recognition_text)
            if recognition_text and not self._is_screen_error_text(recognition_text):
                result["text"] = recognition_text
                result["used_text_pipeline"] = True
                result["source"] = "astrbot_image_caption"
                return result

        if not use_external_vision:
            return result

        recognition_text = await self._call_external_vision_api(
            media_bytes,
            media_kind=media_kind,
            mime_type=mime_type,
            scene=scene,
            active_window_title=active_window_title,
        )
        result["text"] = self._compress_recognition_text(recognition_text)
        result["used_text_pipeline"] = True
        result["source"] = "external_vision_api"
        return result

    async def _request_screen_interaction(
        self,
        *,
        provider: Any,
        use_external_vision: bool,
        interaction_prompt: str,
        system_prompt: str,
        media_bytes: bytes,
        media_kind: str,
        mime_type: str,
        umo: str | None,
    ) -> Any:
        timeout_seconds = self._get_interaction_timeout(
            media_kind,
            use_external_vision,
        )
        if use_external_vision:
            return await asyncio.wait_for(
                provider.text_chat(
                    prompt=interaction_prompt,
                    system_prompt=system_prompt,
                ),
                timeout=timeout_seconds,
            )

        return await asyncio.wait_for(
            self._call_provider_multimodal_direct(
                provider=provider,
                interaction_prompt=interaction_prompt,
                system_prompt=system_prompt,
                media_bytes=media_bytes,
                media_kind=media_kind,
                mime_type=mime_type,
                provider_id=await self._get_current_chat_provider_id(umo=umo),
            ),
            timeout=timeout_seconds,
        )

    async def _analyze_screen(
        self,
        capture_context: dict[str, Any],
        session=None,
        active_window_title: str = "",
        custom_prompt: str = "",
        task_id: str = "unknown",
        user_request_text: str = "",
    ) -> list[BaseMessageComponent]:
        """Analyze the current screenshot or recording context and generate a reply."""
        should_send_rest_reminder, rest_reminder_info = self._should_send_rest_reminder()
        if self._is_in_rest_time_range() and not (should_send_rest_reminder and not custom_prompt):
            logger.info(f"[任务 {task_id}] 当前处于休息时段，跳过识屏。")
            return []

        if not self._is_in_active_time_range():
            logger.info(f"[任务 {task_id}] 当前不在主动互动时段，跳过识屏。")
            return []

        provider = self.context.get_using_provider()
        if not provider:
            return [Plain("当前没有可用的 AstrBot 模型提供方。")]

        umo = None
        if session and hasattr(session, "unified_msg_origin"):
            umo = session.unified_msg_origin

        system_prompt = await self._get_persona_prompt(umo)
        debug_mode = self._get_runtime_flag("debug")
        media_kind = str(capture_context.get("media_kind", "image") or "image")
        mime_type = str(capture_context.get("mime_type", "image/jpeg") or "image/jpeg")
        media_bytes = capture_context.get("media_bytes", b"") or b""
        use_external_vision = self._get_runtime_flag("use_external_vision")
        effective_use_external_vision = use_external_vision
        analysis_trace = {
            "task_id": task_id,
            "trigger_reason": str(capture_context.get("trigger_reason", "") or ""),
            "media_kind": media_kind,
            "analysis_material_kind": media_kind,
            "sampling_strategy": "",
            "frame_count": 0,
            "frame_labels": [],
            "active_window_title": active_window_title,
            "scene": "",
            "recognition_summary": "",
            "reply_preview": "",
            "stored_as_observation": False,
            "stored_in_diary": False,
            "used_full_video": media_kind == "video",
            "status": "running",
            "memory_hints": [],
            "rest_reminder_planned": False,
        }
        analysis_trace["latest_window_title"] = str(
            capture_context.get("latest_window_title", "") or ""
        )
        analysis_trace["clip_active_window_title"] = str(
            capture_context.get("clip_active_window_title", "") or ""
        )
        capture_context["_rest_reminder_planned"] = False
        capture_context["_rest_reminder_info"] = {}

        analysis_context = await self._gather_screen_analysis_context(
            active_window_title=active_window_title,
            debug_mode=debug_mode,
            allow_rest_hint=should_send_rest_reminder and not custom_prompt,
        )
        scene = analysis_context["scene"]
        scene_prompt = analysis_context["scene_prompt"]
        time_prompt = analysis_context["time_prompt"]
        holiday_prompt = analysis_context["holiday_prompt"]
        system_status_prompt = analysis_context["system_status_prompt"]
        weather_prompt = analysis_context["weather_prompt"]
        analysis_trace["scene"] = scene

        contexts = await self._collect_recent_conversation_context(
            session,
            debug_mode=debug_mode,
        )
        reply_interval_guidance, reply_interval_info = self._build_reply_interval_guidance(
            task_id
        )
        analysis_trace["reply_interval_seconds"] = int(
            reply_interval_info.get("elapsed_seconds", 0) or 0
        )
        analysis_trace["reply_interval_bucket"] = str(
            reply_interval_info.get("bucket", "") or ""
        )
        presence_mode = self._build_presence_mode_snapshot(
            task_id,
            scene=scene,
            change_snapshot={
                "changed": "变化" in str(capture_context.get("trigger_reason", "") or ""),
                "scene": scene,
            },
        )
        analysis_trace["presence_mode"] = str(presence_mode.get("mode", "") or "")
        preserve_full_video_for_audio = False
        if media_kind == "video" and not effective_use_external_vision:
            preserve_full_video_for_audio = await self._supports_native_gemini_video_audio(
                provider=provider,
                umo=umo,
            )
            analysis_trace["native_video_audio_capable"] = preserve_full_video_for_audio

        try:
            if debug_mode:
                logger.info("开始分析当前识屏素材")
                logger.debug(f"System prompt: {system_prompt}")
                logger.debug(f"Media kind: {media_kind}")
                logger.debug(f"Mime type: {mime_type}")
                logger.debug(f"Media size: {len(media_bytes)} bytes")

            effective_capture_context = capture_context
            effective_media_kind = media_kind
            effective_mime_type = mime_type
            effective_media_bytes = media_bytes
            material_label = "录屏视频" if media_kind == "video" else "截图"
            sampling_profile = self._get_scene_behavior_profile(scene)
            sampled_capture_context = None
            recognition_capture_context = capture_context

            if media_kind == "video":
                sampled_capture_context = await self._build_video_sample_capture_context(
                    capture_context,
                    scene=scene,
                    use_external_vision=effective_use_external_vision,
                )
                if sampled_capture_context:
                    analysis_trace["sampling_strategy"] = str(
                        sampled_capture_context.get("sampling_strategy", "keyframe_sheet")
                    )
                    analysis_trace["frame_count"] = int(
                        sampled_capture_context.get("frame_count", 0) or 0
                    )
                    analysis_trace["frame_labels"] = list(
                        sampled_capture_context.get("frame_labels", []) or []
                    )
                    analysis_trace["has_live_anchor_frame"] = bool(
                        sampled_capture_context.get("has_live_anchor_frame")
                    )
                    if self._should_keep_sampled_video_only(
                        scene,
                        use_external_vision=use_external_vision,
                        preserve_full_video_for_audio=preserve_full_video_for_audio,
                    ):
                        effective_capture_context = sampled_capture_context
                        effective_media_kind = str(
                            sampled_capture_context.get("media_kind", "image") or "image"
                        )
                        effective_mime_type = str(
                            sampled_capture_context.get("mime_type", "image/jpeg")
                            or "image/jpeg"
                        )
                        effective_media_bytes = (
                            sampled_capture_context.get("media_bytes", b"") or b""
                        )
                        material_label = "录屏关键帧拼图"
                        analysis_trace["analysis_material_kind"] = effective_media_kind
                        analysis_trace["used_full_video"] = False
                        if use_external_vision:
                            recognition_capture_context = sampled_capture_context

            recognition_result = await self._recognize_screen_material(
                capture_context=recognition_capture_context,
                use_external_vision=effective_use_external_vision,
                scene=scene,
                active_window_title=active_window_title,
            )
            recognition_text = str(recognition_result.get("text", "") or "")
            recognition_source = str(recognition_result.get("source", "") or "")
            effective_use_external_vision = bool(
                recognition_result.get("used_text_pipeline", False)
            )
            if (
                media_kind == "video"
                and effective_use_external_vision
                and sampled_capture_context is not None
                and recognition_capture_context is sampled_capture_context
                and self._looks_uncertain_screen_result(recognition_text)
            ):
                recognition_result = await self._recognize_screen_material(
                    capture_context=capture_context,
                    use_external_vision=effective_use_external_vision,
                    scene=scene,
                    active_window_title=active_window_title,
                )
                recognition_text = str(recognition_result.get("text", "") or "")
                recognition_source = str(recognition_result.get("source", "") or "")
                effective_use_external_vision = bool(
                    recognition_result.get("used_text_pipeline", False)
                )
                analysis_trace["analysis_material_kind"] = "video"
                analysis_trace["used_full_video"] = True
                material_label = "录屏视频"

            analysis_trace["recognition_source"] = recognition_source
            if (
                recognition_source == "external_vision_api"
                and effective_use_external_vision
                and self._is_screen_error_text(recognition_text)
            ):
                logger.warning(
                    f"[任务 {task_id}] 外部视觉识别失败，尝试回退到当前 provider 多模态链路: {recognition_text}"
                )
                effective_use_external_vision = False
                recognition_text = ""
                analysis_trace["sampling_strategy"] = (
                    f"{analysis_trace['sampling_strategy']}+provider_fallback"
                    if analysis_trace["sampling_strategy"]
                    else "provider_fallback"
                )
                analysis_trace["analysis_material_kind"] = effective_media_kind
            fact_digest = self._build_screen_fact_digest(
                scene=scene,
                active_window_title=active_window_title,
                recognition_text=recognition_text,
                media_kind=media_kind,
                latest_window_title=str(
                    capture_context.get("latest_window_title", "") or ""
                ),
                clip_active_window_title=str(
                    capture_context.get("clip_active_window_title", "") or ""
                ),
            )
            analysis_trace["fact_summary"] = str(fact_digest.get("summary", "") or "")
            analysis_trace["fact_lines"] = list(fact_digest.get("fact_lines", []) or [])
            analysis_trace["app_name"] = str(fact_digest.get("app_name", "") or "")
            analysis_trace["display_title"] = str(
                fact_digest.get("display_title", "") or ""
            )
            analysis_trace["activity_description"] = str(
                fact_digest.get("activity_description", "") or ""
            )
            analysis_trace["user_request"] = self._truncate_preview_text(
                user_request_text,
                limit=120,
            )
            request_intent = self._evaluate_user_request_intent(
                user_request_text=user_request_text,
                fact_digest=fact_digest,
                recognition_text=recognition_text,
                contexts=contexts,
            )
            analysis_trace["request_intent_type"] = str(
                request_intent.get("intent_type", "") or ""
            )
            analysis_trace["request_intent_action"] = str(
                request_intent.get("action", "") or ""
            )

            prompt_parts: list[str] = []
            intent_first_guide = self._build_intent_first_screen_reply_guide(
                request_intent=request_intent,
                context_count=len(contexts),
            )
            if intent_first_guide:
                prompt_parts.append(intent_first_guide)
            if fact_digest.get("prompt_block"):
                prompt_parts.append(str(fact_digest.get("prompt_block", "")))
            if effective_use_external_vision:
                prompt_parts.extend(
                    [
                        "你是屏幕伴侣，请结合下面的识屏结果与对话上下文，自然地继续陪伴用户。",
                        f"当前场景：{scene}",
                        f"识别结果：{recognition_text or '未获得有效识别结果。'}",
                        "请优先判断用户正在做什么、可能卡在哪一步，以及现在最值得提醒的一条建议。",
                    ]
                )
            else:
                prompt_parts.extend(
                    [
                        f"你会直接收到一份当前桌面的{material_label}作为多模态输入，请先理解素材内容，再决定如何回复用户。",
                        f"当前场景：{scene}",
                        f"素材类型：{media_kind}",
                        "请只基于当前素材与已有上下文做判断；如果看不清或信息不足，要明确说明不确定。",
                        "请优先关注用户正在做什么、进行到哪一步，以及此刻最值得提醒的一条建议。",
                    ]
                )

            if contexts:
                prompt_parts.append("最近对话：\n" + "\n".join(contexts))
                prompt_parts.append(
                    "连续性要求：把这条消息视作同一段持续陪伴的延续，优先补充新的变化、判断或下一步；"
                    "不要每条都重新用情绪化称呼开场，也不要重复上一条已经说过的提醒。"
                )
            analysis_trace["memory_hints"] = []
            analysis_trace["preference_hints"] = []
            analysis_trace["wrap_up_detected"] = False

            if custom_prompt:
                prompt_parts.append(f"额外要求：{custom_prompt}")
            else:
                if not effective_use_external_vision and analysis_trace["trigger_reason"]:
                    trigger_reason = analysis_trace["trigger_reason"]
                    prompt_parts.append(f"触发背景：{trigger_reason}")

            if not should_send_rest_reminder:
                prompt_parts.append(
                    "如果最近几条消息已经提过休息、熬夜或睡觉，这次不要再重复这些提醒。"
                )

            if should_send_rest_reminder and not custom_prompt:
                prompt_parts.append(
                    "用户快到平时休息的时间了。请只在这次回复里顺带轻提醒一次休息，"
                    "语气要自然、克制、不要说教，也不要打断当前任务。"
                )
                analysis_trace["rest_reminder_planned"] = True
                capture_context["_rest_reminder_planned"] = True
                capture_context["_rest_reminder_info"] = dict(rest_reminder_info or {})

            prompt_parts.append(
                self._build_grounded_screen_reply_guide(
                    fact_digest=fact_digest,
                    custom_prompt=custom_prompt,
                    context_count=len(contexts),
                )
            )

            prompt_parts.append(
                self._build_companion_response_guide(
                    scene=scene,
                    recognition_text=recognition_text,
                    custom_prompt=custom_prompt,
                    context_count=len(contexts),
                )
            )

            latest_window_title = self._normalize_window_title(
                capture_context.get("latest_window_title", "")
            )
            clip_window_title = self._normalize_window_title(
                capture_context.get("clip_active_window_title", "")
            )
            if media_kind == "video" and latest_window_title:
                if (
                    clip_window_title
                    and latest_window_title.casefold() != clip_window_title.casefold()
                ):
                    prompt_parts.append(
                        f"时序补充：这段录屏对应的是刚刚过去的一小段画面，"
                        f"更接近当前时刻的活动窗口是《{latest_window_title}》。"
                        "如果录屏尾段和此刻状态略有错位，请优先按更接近当前的线索理解用户现在在做什么。"
                    )
                elif analysis_trace.get("has_live_anchor_frame"):
                    prompt_parts.append(
                        "时序补充：关键帧拼图最后一张标注为“现在”，是触发分析时刚补抓的当前画面。"
                        "判断用户此刻状态时，请优先参考这张最新画面，再结合前面的录屏变化。"
                    )

            if media_kind == "video":
                if effective_media_kind == "video":
                    prompt_parts.append(
                        "补充要求：如果视频里有可辨识的系统音频、提示音、语音或音乐，也请结合音频一起判断当前进展。"
                        "如果没有听清、音轨不明显，或模型当前无法可靠利用音频，请直接说明不确定，不要编造音频内容。"
                    )
                else:
                    prompt_parts.append(
                        "补充要求：当前收到的是录屏关键帧拼图，只能依据画面判断，请不要假设视频中的音频内容。"
                    )

            interaction_prompt = "\n\n".join(part for part in prompt_parts if part)

            try:
                interaction_response = await self._request_screen_interaction(
                    provider=provider,
                    use_external_vision=effective_use_external_vision,
                    interaction_prompt=interaction_prompt,
                    system_prompt=system_prompt,
                    media_bytes=effective_media_bytes,
                    media_kind=effective_media_kind,
                    mime_type=effective_mime_type,
                    umo=umo,
                )
            except asyncio.TimeoutError:
                logger.error("LLM 响应超时")
                analysis_trace["status"] = "timeout"
                capture_context["_analysis_trace"] = analysis_trace
                return [Plain("这次识屏响应超时了，请稍后再试。")]

            response_text = "我看过了，但这一轮还没成功生成回复。"
            if (
                interaction_response
                and hasattr(interaction_response, "completion_text")
                and interaction_response.completion_text
            ):
                response_text = interaction_response.completion_text
            elif debug_mode:
                logger.warning("模型返回为空")

            if not effective_use_external_vision:
                recognition_text = self._compress_recognition_text(response_text)

            analysis_trace["recognition_summary"] = self._truncate_preview_text(
                recognition_text or response_text,
                limit=120,
            )
            observation_stored = self._add_observation(
                scene,
                recognition_text or response_text,
                active_window_title,
                extra={
                    "trigger_reason": analysis_trace["trigger_reason"],
                    "material_kind": media_kind,
                    "analysis_material_kind": analysis_trace["analysis_material_kind"],
                    "sampling_strategy": analysis_trace["sampling_strategy"],
                    "frame_count": analysis_trace["frame_count"],
                    "frame_labels": analysis_trace["frame_labels"],
                    "recognition_summary": analysis_trace["recognition_summary"],
                    "used_full_video": analysis_trace["used_full_video"],
                },
            )
            analysis_trace["stored_as_observation"] = observation_stored
            if observation_stored:
                self._update_long_term_memory(
                    scene,
                    active_window_title,
                    1,
                    memory_summary=recognition_text or response_text,
                    response_preview=response_text,
                )

                self._update_activity(
                    scene,
                    active_window_title,
                    source="screen_analysis",
                )
            response_text = self._polish_response_text(
                response_text,
                scene,
                contexts=contexts,
                allow_rest_hint=bool(analysis_trace.get("rest_reminder_planned")),
                task_id=task_id,
            )
            analysis_trace["reply_preview"] = self._truncate_preview_text(
                response_text,
                limit=140,
            )
            analysis_trace["status"] = "ok"
            capture_context["_analysis_trace"] = analysis_trace
            self._adjust_interaction_frequency(response_text)
            self._record_screen_analysis_result(True)

        except Exception as e:
            logger.error(f"识屏分析失败: {e}")
            error_msg = str(e).lower()
            error_type = "unknown"
            error_text = "这次识屏分析失败了，请稍后再试。"

            if "timeout" in error_msg:
                error_type = "timeout"
                error_text = "这次识屏请求超时了，请稍后再试。"
            elif "api" in error_msg:
                error_type = "api"
                error_text = "外部接口调用失败了，请检查配置或稍后再试。"
            elif "vision" in error_msg or "video" in error_msg:
                error_type = "vision"
                error_text = "当前模型暂时不支持这次多模态识别，请检查视觉配置。"

            analysis_trace["status"] = f"error:{error_type}"
            analysis_trace["reply_preview"] = error_text
            capture_context["_analysis_trace"] = analysis_trace
            self._record_screen_analysis_result(False, error_type=error_type)
            return [Plain(error_text)]

        if media_kind != "image":
            return [Plain(response_text)]

        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"screen_shot_{uuid.uuid4()}.jpg")
        with open(temp_file_path, "wb") as f:
            f.write(media_bytes)

        if self.save_local:
            try:
                data_dir = self.plugin_config.data_dir
                data_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = str(data_dir / "screen_shot_latest.jpg")
                shutil.copy2(temp_file_path, screenshot_path)
            except Exception as e:
                logger.error(f"保存最新截图失败: {e}")

        try:
            return [Plain(response_text), Image(file=temp_file_path)]
        finally:
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as e:
                logger.error(f"清理临时截图失败: {e}")
