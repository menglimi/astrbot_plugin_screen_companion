# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import BaseMessageComponent, Plain

from ..web_server import WebServer


class ScreenCompanionProactiveMixin:
    AWAY_AUTO_PAUSE_EXCLUDED_SCENES = frozenset({"视频", "浏览-娱乐", "阅读"})

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
        """获取当前生效的预设参数。"""
        if self.current_preset_index >= 0 and self.current_preset_index < len(self.parsed_custom_presets):
            preset = self.parsed_custom_presets[self.current_preset_index]
            return preset["check_interval"], preset["trigger_probability"]
        return self.check_interval, self.trigger_probability

    def _sync_window_companion_effective_params(
        self,
        check_interval: int | None = None,
        trigger_probability: int | None = None,
    ) -> None:
        """同步窗口陪伴当前继承到的主动触发参数。"""
        if check_interval is None or trigger_probability is None:
            check_interval, trigger_probability = self._get_current_preset_params()

        self.window_companion_effective_check_interval = max(
            10, int(check_interval or self.check_interval or 10)
        )
        self.window_companion_effective_trigger_probability = max(
            0,
            min(
                100,
                int(
                    trigger_probability
                    if trigger_probability is not None
                    else getattr(self, "trigger_probability", 0)
                ),
            ),
        )

    def _parse_window_companion_targets(self):
        """Parse window companion rules from config text."""
        self.parsed_window_companion_targets = []
        raw_text = str(getattr(self, "window_companion_targets", "") or "").strip()
        if not raw_text:
            return self.parsed_window_companion_targets

        for line in raw_text.splitlines():
            entry = line.strip()
            if not entry:
                continue

            keyword, prompt = entry, ""
            if "|" in entry:
                keyword, prompt = entry.split("|", 1)

            keyword = keyword.strip()
            prompt = prompt.strip()
            if not keyword:
                continue

            self.parsed_window_companion_targets.append(
                {
                    "keyword": keyword,
                    "keyword_lower": keyword.casefold(),
                    "prompt": prompt,
                }
            )

        return self.parsed_window_companion_targets

    def _list_open_window_titles(self) -> list[str]:
        """Return de-duplicated open window titles."""
        try:
            import pygetwindow
        except ImportError:
            return []
        except Exception as e:
            logger.debug(f"读取窗口列表失败: {e}")
            return []

        raw_titles = []
        try:
            raw_titles = list(pygetwindow.getAllTitles())
        except Exception:
            try:
                raw_titles = [getattr(window, "title", "") for window in pygetwindow.getAllWindows()]
            except Exception as e:
                logger.debug(f"读取窗口标题失败: {e}")
                return []

        titles = []
        seen = set()
        for title in raw_titles:
            normalized = self._normalize_window_title(title)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(normalized)
        return titles

    def _match_window_companion_target(self, window_titles):
        """Find the first configured window companion rule that matches."""
        if not window_titles or not getattr(self, "parsed_window_companion_targets", None):
            return None, ""

        for rule in self.parsed_window_companion_targets:
            keyword = rule.get("keyword_lower", "")
            if not keyword:
                continue
            for title in window_titles:
                if keyword in str(title or "").casefold():
                    return rule, title
        return None, ""

    def _get_default_target(self) -> str:
        """Resolve the proactive message target."""
        target = str(getattr(self, "proactive_target", "") or "").strip()
        if target:
            return self._normalize_target(target)

        get_primary_admin_id = getattr(self, "_get_primary_admin_id", None)
        if callable(get_primary_admin_id):
            admin_id = str(get_primary_admin_id() or "").strip()
        else:
            admin_id = str(getattr(self, "admin_qq", "") or "").strip()

        if admin_id:
            return self._build_private_target(admin_id)
        return ""

    def _get_available_platforms(self) -> list[Any]:
        """Return loaded platform instances, preferring non-webchat adapters."""
        platform_manager = getattr(self.context, "platform_manager", None)
        if not platform_manager:
            return []

        platforms = list(getattr(platform_manager, "platform_insts", []) or [])
        if not platforms:
            return []

        filtered = []
        for platform in platforms:
            try:
                meta = platform.meta()
                if str(getattr(meta, "name", "") or "").strip() == "webchat":
                    continue
            except Exception:
                pass
            filtered.append(platform)
        return filtered or platforms

    def _get_preferred_platform_id(self) -> str:
        """Resolve the platform instance ID used for proactive messages."""
        platforms = self._get_available_platforms()
        if platforms:
            try:
                platform_id = str(getattr(platforms[0].meta(), "id", "") or "").strip()
                if platform_id:
                    return platform_id
            except Exception as e:
                logger.debug(f"获取默认平台 ID 失败: {e}")
        return "default"

    def _build_private_target(self, session_id: str) -> str:
        """Build a private-chat target with the active platform instance ID."""
        session_id = str(session_id or "").strip()
        if not session_id:
            return ""
        return f"{self._get_preferred_platform_id()}:FriendMessage:{session_id}"

    def _normalize_target(self, target: str) -> str:
        """Rewrite legacy proactive targets to the active platform instance ID."""
        target = str(target or "").strip()
        if not target:
            return ""

        parts = target.split(":", 2)
        if len(parts) != 3:
            return target

        platform_token, message_type, session_id = parts
        platforms = self._get_available_platforms()
        if not platforms:
            return target

        for platform in platforms:
            try:
                meta = platform.meta()
                platform_id = str(getattr(meta, "id", "") or "").strip()
                platform_name = str(getattr(meta, "name", "") or "").strip()
            except Exception:
                continue

            if platform_token in {platform_id, platform_name}:
                normalized = f"{platform_id}:{message_type}:{session_id}"
                if normalized != target:
                    logger.info(f"主动消息目标已规范化: {target} -> {normalized}")
                return normalized

        legacy_platform_tokens = {
            "default",
            "aiocqhttp",
            "qq_official",
            "qq_official_webhook",
            "telegram",
            "discord",
            "wecom",
            "wecom_ai_bot",
            "weixin_official_account",
            "line",
            "kook",
            "satori",
            "lark",
            "dingtalk",
            "misskey",
            "slack",
        }
        if len(platforms) == 1 and platform_token in legacy_platform_tokens:
            try:
                platform_id = str(getattr(platforms[0].meta(), "id", "") or "").strip()
            except Exception:
                platform_id = ""
            if platform_id:
                normalized = f"{platform_id}:{message_type}:{session_id}"
                if normalized != target:
                    logger.info(f"主动消息目标已回退到当前平台实例 ID: {target} -> {normalized}")
                return normalized

        return target

    def _create_virtual_event(self, target: str):
        """Build a lightweight virtual event for proactive tasks."""
        event = type("VirtualEvent", (), {})()
        event.unified_msg_origin = self._normalize_target(target)
        event.config = self.plugin_config
        return event

    async def _send_proactive_message(
        self, target: str, message_chain: MessageChain
    ) -> bool:
        """Send a proactive message via the resolved platform instance."""
        target = self._normalize_target(target)
        if not target:
            return False

        session = None
        try:
            from astrbot.core.platform.message_session import MessageSesion

            session = MessageSesion.from_str(target)
        except Exception as e:
            logger.debug(f"解析主动消息目标失败，将回退到 context.send_message: {e}")

        if session is not None:
            platforms = self._get_available_platforms()
            matched_platform = None
            for platform in platforms:
                try:
                    meta = platform.meta()
                    platform_id = str(getattr(meta, "id", "") or "").strip()
                    platform_name = str(getattr(meta, "name", "") or "").strip()
                except Exception:
                    continue
                if session.platform_name in {platform_id, platform_name}:
                    matched_platform = platform
                    if session.platform_name != platform_id:
                        session = MessageSesion(
                            platform_id, session.message_type, session.session_id
                        )
                    break

            if matched_platform is None and platforms:
                matched_platform = platforms[0]
                try:
                    fallback_platform_id = str(
                        getattr(matched_platform.meta(), "id", "") or ""
                    ).strip()
                    if fallback_platform_id:
                        session = MessageSesion(
                            fallback_platform_id,
                            session.message_type,
                            session.session_id,
                        )
                        logger.info(
                            f"主动消息目标未命中平台，已回退为 {fallback_platform_id}:{session.message_type.value}:{session.session_id}"
                        )
                except Exception as e:
                    logger.debug(f"构造主动消息回退会话失败: {e}")

            if matched_platform is not None:
                try:
                    await matched_platform.send_by_session(session, message_chain)
                    return True
                except Exception as e:
                    logger.warning(f"主动消息直发失败，将回退到 context.send_message: {e}")

        try:
            await self.context.send_message(target, message_chain)
            return True
        except Exception as e:
            logger.error(f"发送主动消息失败: {e}")
            return False

    async def _send_plain_message(self, target: str, text: str) -> bool:
        """Send a plain proactive message if possible."""
        target = str(target or "").strip()
        text = str(text or "").strip()
        if not target or not text:
            return False

        sent = await self._send_proactive_message(
            target, MessageChain([Plain(text)])
        )
        if sent:
            remember_reply = getattr(self, "_remember_recent_assistant_reply", None)
            if callable(remember_reply):
                remember_reply(target, text)
            remember_message = getattr(self, "_remember_recent_companion_message", None)
            if callable(remember_message):
                remember_message(target, "assistant", text)
        return sent

    def _resolve_proactive_target(self, fallback_event: Any = None) -> str:
        target = self._get_default_target()
        if not target and fallback_event is not None:
            try:
                target = str(getattr(fallback_event, "unified_msg_origin", "") or "").strip()
            except Exception as e:
                logger.debug(f"读取回退主动消息目标失败: {e}")
        return self._normalize_target(target)

    def _build_message_chain(
        self, components: list[BaseMessageComponent] | None
    ) -> MessageChain:
        chain = MessageChain()
        for comp in components or []:
            chain.chain.append(comp)
        return chain

    def _extract_plain_text(
        self, components: list[BaseMessageComponent] | None
    ) -> str:
        chunks: list[str] = []
        for comp in components or []:
            if isinstance(comp, Plain):
                text = str(getattr(comp, "text", "") or "")
                if text:
                    chunks.append(text)
        return "".join(chunks)

    async def _send_component_text(
        self,
        target: str,
        components: list[BaseMessageComponent] | None,
        *,
        prefix: str = "",
    ) -> bool:
        text = self._extract_plain_text(components)
        if not text:
            return False
        if prefix:
            text = f"{prefix}\n{text}"
        return await self._send_plain_message(target, text)

    async def _send_segmented_text(
        self,
        target: str,
        text: str,
        *,
        max_length: int = 1000,
        delay_seconds: float = 0.5,
        should_continue: Any = None,
    ) -> bool:
        target = str(target or "").strip()
        text = str(text or "").strip()
        if not target or not text:
            return False

        segments = self._split_message(text, max_length=max_length)
        if not segments:
            return False

        sent = False
        for index, segment in enumerate(segments):
            if should_continue is not None and not should_continue():
                break
            if not segment.strip():
                continue
            sent = await self._send_plain_message(target, segment) or sent
            if index < len(segments) - 1 and delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        return sent

    def _ensure_away_pause_runtime_state(self) -> dict[str, Any]:
        self._ensure_runtime_state()
        state = getattr(self, "_away_pause_runtime_state", None)
        if not isinstance(state, dict):
            state = {}
            self._away_pause_runtime_state = state

        state.setdefault("active", False)
        state.setdefault("started_at", 0.0)
        state.setdefault("scene", "")
        state.setdefault("task_id", "")
        state.setdefault("target", "")
        state.setdefault("pause_reason", "")
        state.setdefault("long_notice_sent", False)
        return state

    def _reset_away_pause_runtime_state(self) -> None:
        state = self._ensure_away_pause_runtime_state()
        state.update(
            {
                "active": False,
                "started_at": 0.0,
                "scene": "",
                "task_id": "",
                "target": "",
                "pause_reason": "",
                "long_notice_sent": False,
            }
        )

    def _resolve_away_pause_scene(self, task_id: str) -> str:
        scene = ""
        try:
            snapshot_builder = getattr(self, "_build_current_activity_snapshot", None)
            if callable(snapshot_builder):
                snapshot = snapshot_builder()
                if isinstance(snapshot, dict):
                    scene = str(snapshot.get("scene", "") or "").strip()
        except Exception:
            scene = ""

        if not scene:
            try:
                active_window_title, _ = self._get_active_window_info()
                active_window_title = self._normalize_window_title(active_window_title)
                if active_window_title:
                    scene = self._identify_scene(active_window_title)
            except Exception:
                scene = ""

        if not scene:
            try:
                scene = str(
                    self._ensure_auto_screen_runtime_state(task_id).get("last_scene", "") or ""
                ).strip()
            except Exception:
                scene = ""

        normalize_scene = getattr(self, "_normalize_scene_label", None)
        if callable(normalize_scene):
            try:
                return str(normalize_scene(scene) or "").strip()
            except Exception:
                return str(scene or "").strip()
        return str(scene or "").strip()

    def _scene_allows_away_auto_pause(self, scene: str) -> bool:
        normalized_scene = str(scene or "").strip()
        if not normalized_scene or normalized_scene == "未知":
            return True
        return normalized_scene not in self.AWAY_AUTO_PAUSE_EXCLUDED_SCENES

    async def _get_away_pause_long_reply(
        self,
        target: str,
        *,
        idle_seconds: int,
        scene: str,
    ) -> str:
        idle_label = self._format_elapsed_seconds(idle_seconds)
        scene_label = str(scene or "当前任务").strip() or "当前任务"
        fallback = f"你已经离开电脑前大概 {idle_label} 了，我先安静守着，等你回来再继续。"

        provider = self.context.get_using_provider()
        if not provider:
            return fallback

        try:
            system_prompt = await self._get_persona_prompt(target)
            prompt = (
                "用户已经离开电脑前一段时间，你准备继续保持低打扰等待。"
                f"\n当前离开时长：约 {idle_label}"
                f"\n离开前场景：{scene_label}"
                "\n请以你的性格写一句到两句简短消息：表达你注意到对方离开了，你先暂停观察、安静等他回来。"
                "\n要求：不要催促，不要复盘，不要连续提问，不要编造离开期间发生的事情。"
            )
            response = await asyncio.wait_for(
                provider.text_chat(prompt=prompt, system_prompt=system_prompt),
                timeout=45.0,
            )
            if response and hasattr(response, "completion_text") and response.completion_text:
                return str(response.completion_text).strip() or fallback
        except Exception as e:
            logger.debug(f"生成长时间离开提醒失败: {e}")
        return fallback

    def _get_away_pause_runtime_status(self) -> dict[str, Any]:
        state = self._ensure_away_pause_runtime_state()
        active = bool(state.get("active", False))
        started_at = float(state.get("started_at", 0.0) or 0.0)
        away_seconds = max(0, int(time.time() - started_at)) if active and started_at > 0 else 0
        away_label = self._format_elapsed_seconds(away_seconds) if away_seconds > 0 else ""
        scene = str(state.get("scene", "") or "").strip()
        return {
            "enabled": bool(getattr(self, "enable_away_auto_pause", False)),
            "available": bool(getattr(self, "enable_input_stats", False)),
            "active": active,
            "scene": scene,
            "scene_label": scene or "未锁定场景",
            "away_seconds": away_seconds,
            "away_label": away_label,
            "detail": (
                f"已自动挂起约 {away_label}，等待用户回到电脑前。"
                if active and away_label
                else "当前未触发离开自动挂起。"
            ),
            "long_notice_sent": bool(state.get("long_notice_sent", False)),
        }

    async def _handle_away_auto_pause(
        self,
        event: Any,
        *,
        task_id: str,
    ) -> bool:
        self._ensure_runtime_state()
        state = self._ensure_away_pause_runtime_state()
        if not bool(getattr(self, "enable_away_auto_pause", False)):
            if state.get("active"):
                self._reset_away_pause_runtime_state()
            return False
        if not bool(getattr(self, "enable_input_stats", False)):
            if state.get("active"):
                self._reset_away_pause_runtime_state()
            return False

        presence_reader = getattr(self, "_get_input_presence_snapshot", None)
        presence = presence_reader() if callable(presence_reader) else {}
        presence_status = str(presence.get("presence_status", "disabled") or "disabled")
        idle_seconds = max(0, int(presence.get("idle_seconds", 0) or 0))
        scene = self._resolve_away_pause_scene(task_id)
        allows_pause = self._scene_allows_away_auto_pause(scene)
        pause_threshold = max(300, int(getattr(self, "away_auto_pause_threshold", 1200) or 1200))
        long_threshold = max(
            pause_threshold + 60,
            int(getattr(self, "away_long_notice_threshold", 3600) or 3600),
        )
        target = self._resolve_proactive_target(event)
        should_pause = allows_pause and idle_seconds >= pause_threshold and presence_status in {"idle", "away"}

        if should_pause:
            if not bool(state.get("active", False)):
                state.update(
                    {
                        "active": True,
                        "started_at": time.time(),
                        "scene": scene,
                        "task_id": str(task_id or "").strip(),
                        "target": target,
                        "pause_reason": str(presence.get("presence_detail", "") or "").strip(),
                        "long_notice_sent": False,
                    }
                )
                if target:
                    end_response = await self._get_end_response(target)
                    intro = "看你像是暂时不在电脑前，我先把这边的自动观察挂起。"
                    await self._send_plain_message(target, f"{intro}\n{end_response}".strip())
                logger.info(f"[任务 {task_id}] 用户疑似离开电脑前，已进入自动挂起")
            elif not bool(state.get("long_notice_sent", False)):
                away_seconds = max(
                    idle_seconds,
                    int(time.time() - float(state.get("started_at", 0.0) or 0.0)),
                )
                if away_seconds >= long_threshold:
                    long_target = str(state.get("target", "") or target).strip()
                    if long_target:
                        long_reply = await self._get_away_pause_long_reply(
                            long_target,
                            idle_seconds=away_seconds,
                            scene=str(state.get("scene", "") or scene),
                        )
                        await self._send_plain_message(long_target, long_reply)
                    state["long_notice_sent"] = True
            return True

        if bool(state.get("active", False)):
            if presence_status == "active":
                resume_target = str(state.get("target", "") or target).strip()
                paused_seconds = max(
                    idle_seconds,
                    int(time.time() - float(state.get("started_at", 0.0) or 0.0)),
                )
                self._reset_away_pause_runtime_state()
                if resume_target:
                    start_response = await self._get_start_response(resume_target)
                    intro = (
                        "看到你回来继续操作了，我把这边的自动观察接上。"
                        if paused_seconds < long_threshold
                        else "你回来了，我把这边的自动观察重新接上。"
                    )
                    await self._send_plain_message(resume_target, f"{intro}\n{start_response}".strip())
                logger.info(f"[任务 {task_id}] 检测到用户回到电脑前，已恢复自动观察")
                return False
            return True

        return False

    def _build_window_companion_prompt(self, window_title: str, extra_prompt: str = "") -> str:
        """Build a focused prompt for window companion sessions."""
        pieces = [
            f"这是你被指定要陪伴的窗口：《{window_title}》。",
            "请更关注这个窗口里的当前任务、卡点和下一步，不要泛泛播报画面。",
            "如果适合给建议，优先给和当前任务直接相关、能立刻派上用场的建议。",
            "保持对话的连续性，关注用户的任务进展，提供具体的建议。",
            "注意观察窗口内容的变化，及时调整你的回应，确保与当前场景相关。",
            "如果发现用户遇到困难，提供具体的解决方案和步骤指导。",
        ]
        if extra_prompt:
            pieces.append(extra_prompt.strip())
        return "\n".join(piece for piece in pieces if piece)

    def _is_window_companion_session_active(self) -> bool:
        task = (getattr(self, "auto_tasks", {}) or {}).get(
            getattr(self, "WINDOW_COMPANION_TASK_ID", "")
        )
        return bool(task and not task.done())

    def _window_companion_rule_key(self, rule: dict | None) -> str:
        if not isinstance(rule, dict):
            return ""
        return str(rule.get("keyword_lower", "") or "").strip()

    def _window_companion_rules_match(self, left: dict | None, right: dict | None) -> bool:
        left_key = self._window_companion_rule_key(left)
        right_key = self._window_companion_rule_key(right)
        return bool(left_key and right_key and left_key == right_key)

    async def _start_window_companion_session(self, window_title: str, rule: dict) -> bool:
        """Start automatic companion mode for a matched window."""
        self._ensure_runtime_state()
        if not self.enabled or not self.enable_window_companion:
            return False
        if self._is_window_companion_session_active():
            return False

        target = self._get_default_target()
        if not target:
            logger.warning("窗口陪伴已匹配到目标窗口，但没有可用的主动消息目标，已跳过启动")
            return False

        ok, err_msg = self._check_env(check_mic=False)
        if not ok:
            logger.warning(f"窗口陪伴启动失败: {err_msg}")
            return False

        event = self._create_virtual_event(target)
        self._sync_window_companion_effective_params()
        self.window_companion_active_title = window_title
        self.window_companion_active_target = target
        self.window_companion_active_rule = dict(rule or {})
        self.window_companion_missing_since = 0.0
        self.is_running = True
        self.state = "active"
        self.auto_tasks[self.WINDOW_COMPANION_TASK_ID] = asyncio.create_task(
            self._auto_screen_task(
                event,
                task_id=self.WINDOW_COMPANION_TASK_ID,
                custom_prompt=self._build_window_companion_prompt(
                    window_title, (rule or {}).get("prompt", "")
                ),
            )
        )

        start_response = await self._get_start_response(target)
        intro = f"检测到《{window_title}》已经打开，我来陪你。"
        await self._send_plain_message(target, f"{intro}\n{start_response}".strip())
        logger.info(f"窗口陪伴已启动: {window_title}")
        return True

    async def _stop_window_companion_session(self, reason: str = "window_closed") -> bool:
        """Stop the automatic companion session for the matched window."""
        self._ensure_runtime_state()
        task_id = getattr(self, "WINDOW_COMPANION_TASK_ID", "")
        task = (getattr(self, "auto_tasks", {}) or {}).get(task_id)
        if not task and not getattr(self, "window_companion_active_title", ""):
            return False

        active_title = str(getattr(self, "window_companion_active_title", "") or "").strip()
        target = str(getattr(self, "window_companion_active_target", "") or "").strip()

        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("等待窗口陪伴任务停止超时")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"停止窗口陪伴任务失败: {e}")

        self.auto_tasks.pop(task_id, None)
        self.window_companion_active_title = ""
        self.window_companion_active_target = ""
        self.window_companion_active_rule = {}
        self.window_companion_missing_since = 0.0
        self._sync_window_companion_effective_params()

        if not self.auto_tasks:
            self.is_running = False
            self.state = "inactive"

        if target and active_title:
            end_response = await self._get_end_response(target)
            if reason == "disabled":
                outro = f"《{active_title}》的窗口陪伴已经关闭，我先退到旁边。"
            else:
                outro = f"《{active_title}》已经关掉了，我先退到旁边。"
            await self._send_plain_message(target, f"{outro}\n{end_response}".strip())

        logger.info(f"窗口陪伴已停止: {active_title or 'unknown'} ({reason})")
        return True

    async def _window_companion_task(self):
        """Watch configured windows and start or stop companion sessions automatically."""
        self._ensure_runtime_state()
        while self.running and self._is_current_process_instance():
            interval = max(2, int(getattr(self, "window_companion_check_interval", 5) or 5))
            grace_seconds = max(
                interval * 2,
                int(
                    getattr(
                        self,
                        "window_companion_reattach_grace_seconds",
                        getattr(self, "WINDOW_COMPANION_REATTACH_GRACE_SECONDS", 300),
                    )
                    or getattr(self, "WINDOW_COMPANION_REATTACH_GRACE_SECONDS", 300)
                ),
            )
            try:
                if not self.enable_window_companion or not getattr(
                    self, "parsed_window_companion_targets", None
                ):
                    if self._is_window_companion_session_active() or getattr(
                        self, "window_companion_active_title", ""
                    ):
                        await self._stop_window_companion_session(reason="disabled")
                    await asyncio.sleep(interval)
                    continue

                window_titles = self._list_open_window_titles()
                matched_rule, matched_title = self._match_window_companion_target(window_titles)
                active_session = self._is_window_companion_session_active()
                active_title = str(getattr(self, "window_companion_active_title", "") or "").strip()
                active_rule = getattr(self, "window_companion_active_rule", {}) or {}
                active_exists = bool(
                    active_title
                    and any(active_title.casefold() == title.casefold() for title in window_titles)
                )
                matched_same_rule = bool(
                    matched_rule
                    and matched_title
                    and self._window_companion_rules_match(active_rule, matched_rule)
                )

                if matched_rule and matched_title and not active_session:
                    await self._start_window_companion_session(matched_title, matched_rule)
                elif active_session:
                    if active_exists or matched_same_rule:
                        if matched_same_rule and active_title.casefold() != matched_title.casefold():
                            logger.info(
                                f"Window companion resumed on recreated window: {active_title or 'unknown'} -> {matched_title}"
                            )
                            self.window_companion_active_title = matched_title
                            self.window_companion_active_rule = dict(matched_rule or {})
                        self.window_companion_missing_since = 0.0
                    else:
                        missing_since = float(
                            getattr(self, "window_companion_missing_since", 0.0) or 0.0
                        )
                        now_ts = time.time()
                        if missing_since <= 0:
                            self.window_companion_missing_since = now_ts
                            logger.info(
                                "Window companion target disappeared briefly, waiting before sending an end reminder"
                            )
                        elif (now_ts - missing_since) >= grace_seconds:
                            await self._stop_window_companion_session(reason="window_closed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"窗口陪伴监测异常: {e}")

            await asyncio.sleep(interval)

    def _ensure_webui_password(self) -> bool:
        """确保 WebUI 在需要认证时拥有可用密码。"""
        # 检查密码是否已经设置
        current_password = str(self.plugin_config.webui.password or "").strip()
        # 仅当开启认证且密码为空时，自动生成密码
        if (
            self.plugin_config.webui.enabled
            and self.plugin_config.webui.auth_enabled
            and not current_password
        ):
            # 生成随机密码
            generated = f"{secrets.randbelow(1000000):06d}"
            # 保存密码
            self.plugin_config.webui.password = generated
            self.plugin_config.save_webui_config()
            logger.info(f"WebUI 访问密码已自动生成: {generated}")
            logger.info("请在配置中查看或修改此密码")
            return True
        return False

    def _snapshot_webui_runtime(self) -> tuple[bool, str, int, str, int]:
        """返回当前 WebUI 运行时快照。"""
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
        self._ensure_runtime_state()
        webui_lock = getattr(self, "_webui_lock", None)
        if webui_lock is None:
            self._webui_lock = asyncio.Lock()
            webui_lock = self._webui_lock

        async with webui_lock:
            logger.info("检测到 WebUI 配置变更，正在重启 WebUI...")

            if not self.webui_enabled:
                # WebUI 已禁用，停止旧服务即可
                if self.web_server:
                    await self.web_server.stop()
                    self.web_server = None
                    await asyncio.sleep(0.6)
                return

            old_server = self.web_server
            old_server_active = bool(
                old_server and getattr(old_server, "_started", False)
            )
            self.web_server = None

            try:
                # 同端口重启时必须先停旧服务，否则新服务一定会撞端口。
                if old_server_active:
                    try:
                        await old_server.stop()
                        await asyncio.sleep(0.6)
                    except Exception as e:
                        logger.warning(f"停止旧 WebUI 服务时出错: {e}")

                new_server = WebServer(self, host=self.webui_host, port=self.webui_port)
                success = await new_server.start()
                if success:
                    self.web_server = new_server
                    logger.info("WebUI 重启成功")
                else:
                    logger.error(
                        f"WebUI 重启失败，原因: 无法绑定 {self.webui_host}:{self.webui_port}"
                    )
                    if old_server_active and old_server:
                        restored = await old_server.start()
                        if restored:
                            self.web_server = old_server
                            logger.info("新 WebUI 启动失败，已恢复旧的 WebUI 服务")
            except Exception as e:
                logger.error(f"重启 WebUI 失败: {e}")
                if old_server_active and old_server:
                    try:
                        restored = await old_server.start()
                        if restored:
                            self.web_server = old_server
                            logger.info("重启失败后已恢复旧的 WebUI 服务")
                    except Exception as restore_error:
                        logger.warning(f"恢复旧 WebUI 服务失败: {restore_error}")
