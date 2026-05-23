# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import datetime
import json
import os
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent


class ScreenCompanionCommandSupportMixin:
    async def _render_webui_status(self, event: AstrMessageEvent):
        """查看 WebUI 信息。"""
        self._ensure_runtime_state()
        page_api_ready = bool(getattr(self, "page_api", None))
        webui_running = self.web_server is not None and getattr(self.web_server, "_started", False)
        response = "WebUI 状态：已迁移至 AstrBot 插件拓展页面\n"
        response += "入口：AstrBot 控制台 -> 插件管理 -> 屏幕伴侣 -> 屏幕伴侣\n"
        response += f"拓展页面 API：{'已注册' if page_api_ready else '未注册'}"

        if webui_running:
            actual_port = getattr(self.web_server, "port", self.webui_port)
            host = self.webui_host
            access_url = f"http://127.0.0.1:{actual_port}" if host == "0.0.0.0" else f"http://{host}:{actual_port}"
            auth_status = "已启用" if self.webui_auth_enabled else "未启用"
            response += "\n\n兼容独立 WebUI：运行中"
            response += f"\n访问地址：{access_url}"
            response += f"\n认证状态：{auth_status}"
        else:
            response += "\n\n兼容独立 WebUI：未运行。需要旧端口入口时可用 /kpi webui start 手动启动。"
        
        yield event.plain_result(response)

    async def _render_status_report(self, event: AstrMessageEvent):
        """输出当前运行状态和关键诊断信息。"""
        report = await self._build_kpi_doctor_report(event)
        yield event.plain_result(report)

    async def _render_preset_list(self, event: AstrMessageEvent):
        """列出所有自定义预设 /kpi p"""
        if not self.parsed_custom_presets:
            yield event.plain_result(
                "当前还没有自定义预设。\n"
                "用法: /kpi y [预设序号] [间隔秒数] [触发概率]\n"
                "例如: /kpi y 1 90 30"
            )
            return
        
        msg = "当前自定义预设：\n"
        for i, preset in enumerate(self.parsed_custom_presets):
            current_marker = ""
            if i == self.current_preset_index:
                current_marker = " <- 当前使用"
            msg += f"{i}. {preset['name']}: {preset['check_interval']} 秒间隔，{preset['trigger_probability']}% 触发概率{current_marker}\n"
        
        msg += f"\n当前使用: {'预设 ' + str(self.current_preset_index) if self.current_preset_index >= 0 else '手动配置'}"
        msg += "\n切换预设: /kpi [预设序号]，例如 /kpi 0"
        yield event.plain_result(msg)

    def _refresh_diary_storage_runtime(self) -> None:
        diary_storage = str(getattr(self, "diary_storage", "") or "").strip()
        if not diary_storage:
            diary_storage = str(getattr(self.plugin_config, "diary_dir", "") or "").strip()
            self.diary_storage = diary_storage
        os.makedirs(self.diary_storage, exist_ok=True)
        self.diary_metadata_file = os.path.join(self.diary_storage, "diary_metadata.json")
        self.pending_diary_entries_file = os.path.join(
            self.diary_storage,
            "pending_diary_entries.json",
        )
        self._load_diary_metadata()
        self._load_pending_diary_entries()
        self.last_diary_date = self._get_latest_saved_diary_date()

    @staticmethod
    def _parse_diary_date_value(value: Any) -> datetime.date | None:
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        try:
            return datetime.datetime.fromisoformat(text).date()
        except Exception:
            return None

    def _normalize_pending_diary_entry(
        self,
        item: dict[str, Any] | None,
    ) -> dict[str, str] | None:
        if not isinstance(item, dict):
            return None
        content = str(item.get("content") or "").strip()
        if not content:
            return None

        timestamp_text = str(item.get("timestamp") or "").strip()
        entry_date = self._parse_diary_date_value(item.get("date"))
        if entry_date is None and timestamp_text:
            entry_date = self._parse_diary_date_value(timestamp_text)
        if entry_date is None:
            entry_date = self._resolve_diary_target_date()

        time_text = str(item.get("time") or "").strip()
        if not time_text and timestamp_text:
            try:
                time_text = datetime.datetime.fromisoformat(timestamp_text).strftime(
                    "%H:%M:%S"
                )
            except Exception:
                time_text = ""
        if len(time_text) == 5:
            time_text = f"{time_text}:00"
        if not time_text:
            time_text = "00:00:00"

        return {
            "date": entry_date.isoformat(),
            "time": time_text[:8],
            "content": content,
            "active_window": self._normalize_window_title(
                item.get("active_window") or ""
            )
            or "当前窗口",
            "timestamp": timestamp_text
            or f"{entry_date.isoformat()}T{time_text[:8]}",
        }

    @staticmethod
    def _sort_pending_diary_entries(
        entries: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        return sorted(
            entries,
            key=lambda item: (
                str(item.get("date", "") or ""),
                str(item.get("timestamp", "") or item.get("time", "") or ""),
                str(item.get("active_window", "") or ""),
            ),
        )

    def _load_pending_diary_entries(self) -> None:
        pending_file = str(getattr(self, "pending_diary_entries_file", "") or "").strip()
        self.diary_entries = []
        if not pending_file or not os.path.exists(pending_file):
            return
        try:
            with open(pending_file, "r", encoding="utf-8") as f:
                raw_entries = json.load(f)
            normalized_entries = []
            for item in raw_entries if isinstance(raw_entries, list) else []:
                normalized = self._normalize_pending_diary_entry(item)
                if normalized:
                    normalized_entries.append(normalized)
            self.diary_entries = self._sort_pending_diary_entries(normalized_entries)
            self._prune_pending_diary_entries(save_if_changed=True)
        except Exception as e:
            logger.error(f"加载待写日记条目失败: {e}")
            self.diary_entries = []

    def _save_pending_diary_entries(self) -> None:
        pending_file = str(getattr(self, "pending_diary_entries_file", "") or "").strip()
        if not pending_file:
            return
        try:
            os.makedirs(self.diary_storage, exist_ok=True)
            with open(pending_file, "w", encoding="utf-8") as f:
                json.dump(
                    self._sort_pending_diary_entries(
                        list(getattr(self, "diary_entries", []) or [])
                    ),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"保存待写日记条目失败: {e}")

    def _prune_pending_diary_entries(
        self,
        *,
        retention_days: int = 7,
        save_if_changed: bool = False,
    ) -> None:
        entries = list(getattr(self, "diary_entries", []) or [])
        today = datetime.date.today()
        cleaned_entries: list[dict[str, str]] = []
        for item in entries:
            normalized = self._normalize_pending_diary_entry(item)
            if not normalized:
                continue
            entry_date = self._parse_diary_date_value(normalized.get("date"))
            if entry_date is None:
                continue
            if (today - entry_date).days > retention_days:
                continue
            if self._has_saved_diary_for_date(entry_date):
                continue
            cleaned_entries.append(normalized)
        cleaned_entries = self._sort_pending_diary_entries(cleaned_entries)
        if cleaned_entries != entries:
            self.diary_entries = cleaned_entries
            if save_if_changed:
                self._save_pending_diary_entries()

    def _get_diary_file_path(self, target_date: datetime.date) -> str:
        return os.path.join(
            self.diary_storage,
            f"diary_{target_date.strftime('%Y%m%d')}.md",
        )

    def _has_saved_diary_for_date(self, target_date: datetime.date) -> bool:
        return os.path.exists(self._get_diary_file_path(target_date))

    def _get_latest_saved_diary_date(self) -> datetime.date | None:
        try:
            latest_date = None
            for filename in os.listdir(self.diary_storage):
                if not (filename.startswith("diary_") and filename.endswith(".md")):
                    continue
                candidate = self._parse_diary_date_value(filename[6:14])
                if candidate and (latest_date is None or candidate > latest_date):
                    latest_date = candidate
            return latest_date
        except Exception:
            return None

    def _get_pending_diary_entries_for_date(
        self,
        target_date: datetime.date,
    ) -> list[dict[str, str]]:
        date_key = target_date.isoformat()
        return [
            dict(entry)
            for entry in list(getattr(self, "diary_entries", []) or [])
            if str(entry.get("date", "") or "").strip() == date_key
        ]

    def _replace_pending_diary_entries_for_date(
        self,
        target_date: datetime.date,
        entries: list[dict[str, Any]],
    ) -> None:
        date_key = target_date.isoformat()
        kept_entries = [
            dict(entry)
            for entry in list(getattr(self, "diary_entries", []) or [])
            if str(entry.get("date", "") or "").strip() != date_key
        ]
        normalized_new_entries = []
        for item in entries:
            payload = dict(item or {})
            payload["date"] = date_key
            normalized = self._normalize_pending_diary_entry(payload)
            if normalized:
                normalized_new_entries.append(normalized)
        self.diary_entries = self._sort_pending_diary_entries(
            kept_entries + normalized_new_entries
        )
        self._prune_pending_diary_entries()
        self._save_pending_diary_entries()

    def _clear_pending_diary_entries_for_date(self, target_date: datetime.date) -> None:
        self._replace_pending_diary_entries_for_date(target_date, [])

    @staticmethod
    def _is_diary_due_for_date(
        target_date: datetime.date,
        now: datetime.datetime,
        *,
        hour: int,
        minute: int,
    ) -> bool:
        scheduled_at = datetime.datetime.combine(
            target_date,
            datetime.time(hour=hour, minute=minute),
        )
        return now >= scheduled_at

    def _get_due_diary_dates(
        self,
        now: datetime.datetime | None = None,
    ) -> list[datetime.date]:
        current = now or datetime.datetime.now()
        hour, minute = map(
            int,
            self._normalize_clock_text(self.diary_time, "00:00").split(":"),
        )
        current_target_date = self._resolve_diary_target_date(current)
        candidate_dates = {
            entry_date
            for entry_date in (
                self._parse_diary_date_value(entry.get("date"))
                for entry in list(getattr(self, "diary_entries", []) or [])
            )
            if entry_date
            and self._is_diary_due_for_date(
                entry_date,
                current,
                hour=hour,
                minute=minute,
            )
        }
        if (
            self._is_diary_due_for_date(
                current_target_date,
                current,
                hour=hour,
                minute=minute,
            )
            and not self._has_saved_diary_for_date(current_target_date)
        ):
            candidate_dates.add(current_target_date)
        return sorted(candidate_dates)

    def _persist_diary_document(
        self,
        *,
        target_date: datetime.date,
        diary_content: str,
        structured_summary: dict[str, Any] | None = None,
    ) -> bool:
        diary_path = self._get_diary_file_path(target_date)
        try:
            with open(diary_path, "w", encoding="utf-8") as f:
                f.write(diary_content)
            normalized_summary = structured_summary if isinstance(structured_summary, dict) else {}
            self._save_diary_structured_summary(target_date, normalized_summary)
            self._remember_diary_summary_memories(target_date, normalized_summary)
            self._update_memory_priorities()
            self._save_long_term_memory()
            self._clear_pending_diary_entries_for_date(target_date)
            self.last_diary_date = target_date
            logger.info(f"日记已保存到: {diary_path}")
            return True
        except Exception as e:
            logger.error(f"保存日记失败: {e}")
            return False

    async def _handle_diary_command(self, event: AstrMessageEvent, date: str = None):
        """处理日记查看命令。"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("补写日记失败了，这次没有成功保存。")
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
                    "日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD，例如：/kpi d 20260302"
                )
                return
        else:
            now = datetime.datetime.now()
            target_date = self._resolve_diary_target_date(now)
            if now.hour < 2:
                yield event.plain_result(
                    f"当前时间还在凌晨两点前，默认查看 {target_date.strftime('%Y年%m月%d日')} 的日记。"
                )

        # 构建日记文件路径
        diary_filename = f"diary_{target_date.strftime('%Y%m%d')}.md"
        diary_path = os.path.join(self.diary_storage, diary_filename)

        if not os.path.exists(diary_path):
            yield event.plain_result(
                f"{target_date.strftime('%Y年%m月%d日')} 的日记还不存在。"
            )
            return

        try:
            with open(diary_path, encoding="utf-8") as f:
                diary_content = f.read()
            
            # 更新日记查看状态
            date_str = target_date.strftime("%Y%m%d")
            self._update_diary_view_status(date_str)
            diary_message = self._format_diary_preview_message(
                target_date,
                diary_content,
            )

            if self.diary_auto_recall:
                logger.info(f"日记消息将在 {self.diary_recall_time} 秒后自动撤回")

                # 启动自动撤回任务
                async def recall_message():
                    await asyncio.sleep(self.diary_recall_time)
                    try:
                        logger.info(f"日记消息已到达自动撤回时间: {self.diary_recall_time} 秒")
                    except Exception as e:
                        logger.error(f"自动撤回日记记录失败: {e}")

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

            # 同时生成日记被查看时的补充回复（异步进行）
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
                                MessageChain([Plain("喂，你怎么又偷看我的日记呀，真是的……")])
                            )
                    except Exception as e:
                        logger.error(f"生成日记被偷看回复失败: {e}")
                        await self.context.send_message(
                            event.unified_msg_origin, 
                            MessageChain([Plain("喂，你怎么又偷看我的日记呀，真是的……")])
                        )
                else:
                    await self.context.send_message(
                        event.unified_msg_origin, 
                        MessageChain([Plain("喂，你怎么又偷看我的日记呀，真是的……")])
                    )

            # 异步生成这条补充回复
            blame_task = asyncio.create_task(generate_blame())
            self.background_tasks.append(blame_task)

        except Exception as e:
            logger.error(f"读取日记失败: {e}")
            yield event.plain_result("读取这篇日记时出了点问题。")

    async def _handle_complete_command(self, event: AstrMessageEvent, date: str = None):
        """处理补写日记命令。"""
        import datetime
        import os

        if not self.enable_diary:
            yield event.plain_result("当前没有开启日记功能，暂时无法补写。")
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
                    "日期格式错误，请使用 YYYY-MM-DD 或 YYYYMMDD，例如：/kpi cd 20260302"
                )
                return
        else:
            now = datetime.datetime.now()
            target_date = self._resolve_diary_target_date(now)
            if now.hour < 2:
                yield event.plain_result(
                    f"当前时间还在凌晨两点前，默认补写 {target_date.strftime('%Y年%m月%d日')} 的日记。"
                )

        # 检查这一天的日记是否已经存在
        diary_filename = f"diary_{target_date.strftime('%Y%m%d')}.md"
        diary_path = os.path.join(self.diary_storage, diary_filename)

        if os.path.exists(diary_path):
            self._clear_pending_diary_entries_for_date(target_date)
            self.last_diary_date = target_date
            yield event.plain_result(
                f"{target_date.strftime('%Y年%m月%d日')} 的日记已经存在，无需补写。"
            )
            return

        # 生成补写日记
        provider = self.context.get_using_provider()
        if not provider:
            yield event.plain_result("当前没有可用的模型提供商，暂时无法补写日记。")
            return

        try:
            # 获取人格设定
            umo = None
            if event and hasattr(event, "unified_msg_origin"):
                umo = event.unified_msg_origin
            system_prompt = await self._get_persona_prompt(umo)
            # 兜底默认值，避免分支调整时出现未定义变量
            weather_info = ""
            observation_text = ""
            
            # 筛选当天的观察记录
            target_date_str = target_date.strftime("%Y-%m-%d")
            day_observations = []
            for obs in self.observations:
                if obs.get("timestamp", "").startswith(target_date_str):
                    day_observations.append(obs)

            activity_fallback_entries = self._build_diary_activity_fallback_entries(
                target_date,
                max_items=3,
            )
            activity_fallback_context = self._build_diary_activity_fallback_context(
                activity_fallback_entries
            )

            # 准备观察记录文本
            if day_observations:
                observation_text = "当天观察记录：\n"
                for i, obs in enumerate(day_observations, 1):
                    observation_text += (
                        f"{i}. 场景：{obs.get('scene', '未知')} - "
                        f"{obs.get('description', '')}\n"
                    )
                observation_text += "\n"
            if activity_fallback_context:
                observation_text += (
                    f"{activity_fallback_context}\n\n"
                    if observation_text
                    else f"{activity_fallback_context}\n\n"
                )

            completion_prompt = (
                f"请补写 {target_date.strftime('%Y年%m月%d日')} 的今日日记。\n"
                "要求：\n"
                "1. 保持和现有日记一致的自然口吻。\n"
                "2. 根据当天观察提炼重点，不要逐条堆叠流水账。\n"
                "3. 如果要给建议，优先给和当天任务直接相关的建议。\n"
                "4. 保留真实感，不要写成空泛鸡汤，也不要重复标题和日期。\n"
                "5. 字数控制在 220 到 420 字。\n"
            )

            if day_observations:
                completion_prompt += "\n当天观察记录：\n"
                for obs in day_observations:
                    completion_prompt += (
                        f"- {obs.get('scene', '未知')}："
                        f"{obs.get('description', '')}\n"
                    )
            if activity_fallback_entries:
                completion_prompt += "\n当天窗口轨迹补充：\n"
                for entry in activity_fallback_entries:
                    time_label = str(entry.get("time", "") or "").strip()[:5]
                    prefix = f"{time_label} " if time_label else ""
                    completion_prompt += (
                        f"- {prefix}{str(entry.get('content', '') or '').strip()}\n"
                    )


            reference_days = []
            for i in range(1, 3):  # 参考前两天的日记语气
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
                                "date": past_date.strftime("%Y-%m-%d"),
                                "content": past_diary_content,
                            }
                        )
                    except Exception as e:
                        logger.error(f"读取前几天日记失败: {e}")

            if reference_days:
                completion_prompt += "\n可参考前几天的日记语气：\n"
                for day in reference_days:
                    completion_prompt += f"\n### {day['date']}\n{str(day['content'])[:500]}\n"

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
                try:
                    weather_info = await self._get_weather_prompt(target_date)
                except Exception as e:
                    logger.debug(f"获取天气信息失败: {e}")

                reflection_text = self._ensure_diary_reflection_text(
                    response.completion_text,
                    observation_text,
                )
                structured_summary = self._build_diary_structured_summary(
                    [],
                    reflection_text,
                )
                if not structured_summary.get("suggestion_items"):
                    structured_summary["suggestion_items"] = (
                        self._extract_actionable_suggestions(
                            reflection_text,
                            limit=3,
                        )
                    )
                diary_content = self._build_diary_document(
                    target_date=target_date,
                    weekday=weekday,
                    weather_info=weather_info,
                    observation_text=observation_text,
                    reflection_text=reflection_text,
                    structured_summary=structured_summary,
                )

                # 保存日记文件
                try:
                    if self._persist_diary_document(
                        target_date=target_date,
                        diary_content=diary_content,
                        structured_summary=structured_summary,
                    ):
                        logger.info(f"补写日记已保存到: {diary_path}")
                        yield event.plain_result(
                            f"已补写并保存 {target_date.strftime('%Y年%m月%d日')} 的日记。"
                        )
                    else:
                        yield event.plain_result("补写成功了，但保存日记时出了点问题。")
                except Exception as e:
                    logger.error(f"保存补写日记失败: {e}")
                    yield event.plain_result("补写成功了，但保存日记时出了点问题。")
            else:
                yield event.plain_result("模型没有返回有效内容，这次补写没有成功。")
        except Exception as e:
            logger.error(f"补写日记失败: {e}")
            yield event.plain_result("补写日记时出了点问题，请稍后再试。")

    def _is_in_active_time_range(self):
        """检查当前时间是否在活跃时间段内。"""
        # 使用配置中的活跃时间段
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

    def _is_in_rest_time_range(self):
        """检查当前时间是否在休息时间段内。"""
        configured_range = self._get_configured_rest_range()
        if configured_range is None:
            return False

        try:
            now = datetime.datetime.now().time()
            start_minutes, end_minutes = configured_range
            inferred = self._infer_rest_behavior()
            effective_start_minutes = start_minutes
            inferred_rest_minutes = inferred.get("rest_extended_minutes")
            if inferred.get("available") and inferred_rest_minutes is not None:
                effective_start_minutes = int(inferred_rest_minutes) % (24 * 60)

            start_time = datetime.time(
                effective_start_minutes // 60,
                effective_start_minutes % 60,
            )
            end_time = datetime.time(end_minutes // 60, end_minutes % 60)

            if start_time <= end_time:
                return start_time <= now <= end_time
            else:
                # 跨午夜的情况
                return now >= start_time or now <= end_time
        except Exception as e:
            logger.error(f"解析休息时间段失败: {e}")
            return False

    def _is_in_rest_reminder_range(self):
        """检查当前是否应触发一次休息提醒。"""
        try:
            should_send, _ = self._should_send_rest_reminder()
            return should_send
        except Exception as e:
            logger.error(f"解析休息提醒时间段失败: {e}")
            return False

    def _add_diary_entry(self, content: str, active_window: str):
        """添加日记条目。"""
        if not self.enable_diary:
            return False

        should_store, reason = self._should_store_diary_entry(content, active_window)
        if not should_store:
            logger.info(f"跳过写入日记条目: {reason}")
            return False

        now = datetime.datetime.now()
        target_date = self._resolve_diary_target_date(now)
        entry = {
            "date": target_date.isoformat(),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": now.isoformat(timespec="seconds"),
            "content": content,
            "active_window": active_window,
        }
        same_day_entries = self._get_pending_diary_entries_for_date(target_date)
        same_day_entries.append(entry)
        if len(same_day_entries) > 18:
            same_day_entries = same_day_entries[-18:]
        self._replace_pending_diary_entries_for_date(target_date, same_day_entries)
        logger.info(f"添加日记条目: {entry}")
        return True

    async def _generate_diary(
        self,
        target_date: datetime.date | None = None,
        *,
        allow_empty: bool = False,
    ):
        """生成日记。"""
        if not self.enable_diary:
            return

        target_date = target_date or self._resolve_diary_target_date()
        if self._has_saved_diary_for_date(target_date):
            self._clear_pending_diary_entries_for_date(target_date)
            self.last_diary_date = target_date
            return

        pending_entries = self._get_pending_diary_entries_for_date(target_date)
        compacted_entries = self._compact_diary_entries(pending_entries)
        activity_fallback_entries: list[dict[str, str]] = []
        if len(compacted_entries) < 3:
            activity_fallback_entries = self._build_diary_activity_fallback_entries(
                target_date,
                max_items=max(2, 4 - len(compacted_entries)),
            )
            if activity_fallback_entries:
                logger.info(
                    f"日记素材不足，使用 {len(activity_fallback_entries)} 条窗口轨迹补充 {target_date.isoformat()} 的日记素材"
                )

        diary_source_entries = self._sort_pending_diary_entries(
            pending_entries + activity_fallback_entries
        )
        if not diary_source_entries and not allow_empty:
            return

        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekdays[target_date.weekday()]

        weather_info = ""
        try:
            weather_info = await self._get_weather_prompt()
        except Exception as e:
            logger.debug(f"获取天气信息失败: {e}")

        compacted_entries = self._compact_diary_entries(diary_source_entries)
        if not compacted_entries:
            logger.info("今日日记没有可用的高质量观察条目，转为生成简版日记")
            observation_text = (
                "（今天用户没给我看屏幕的机会，呜呜）"
                if not diary_source_entries
                else "（今天留下的观察线索太少了，我没能整理出完整的今日观察。）"
            )
            reflection_text = ""
            provider = self.context.get_using_provider()
            if provider:
                try:
                    system_prompt = await self._get_persona_prompt()
                    quiet_day_prompt = (
                        "今天留下来的屏幕线索很少，请写一段简短、自然、带一点陪伴感的日记。"
                        "可以提到今天观察不多、自己在安静等用户，也可以留一点对明天的期待。"
                        "字数控制在 120 到 220 字，不要写成工作汇报。"
                    )
                    response = await provider.text_chat(
                        prompt=quiet_day_prompt,
                        system_prompt=system_prompt,
                    )
                    if (
                        response
                        and hasattr(response, "completion_text")
                        and response.completion_text
                    ):
                        reflection_text = self._ensure_diary_reflection_text(
                            response.completion_text,
                            observation_text,
                        )
                except Exception as e:
                    logger.error(f"生成简版日记总结失败: {e}")

            structured_summary = self._build_diary_structured_summary([], reflection_text)
            reflection_text = self._ensure_diary_reflection_text(
                reflection_text,
                observation_text,
                structured_summary,
            )
            diary_content = self._build_diary_document(
                target_date=target_date,
                weekday=weekday,
                weather_info=weather_info,
                observation_text=observation_text,
                reflection_text=reflection_text,
                structured_summary=structured_summary,
            )
            self._persist_diary_document(
                target_date=target_date,
                diary_content=diary_content,
                structured_summary=structured_summary,
            )
            return

        observation_lines = []
        for entry in compacted_entries:
            time_label = (
                entry["start_time"]
                if entry["start_time"] == entry["end_time"]
                else f"{entry['start_time']}-{entry['end_time']}"
            )
            observation_lines.append(f"### {time_label} - {entry['active_window']}")
            if len(entry["points"]) == 1:
                observation_lines.append(entry["points"][0])
            else:
                for point in entry["points"]:
                    observation_lines.append(f"- {point}")
            observation_lines.append("")
        observation_text = "\n".join(observation_lines).strip()
        reflection_text = ""

        viewed_count = 0
        for i in range(1, 4):
            past_date = target_date - datetime.timedelta(days=i)
            past_date_str = past_date.strftime("%Y%m%d")
            if past_date_str in self.diary_metadata and self.diary_metadata[past_date_str].get("viewed", False):
                viewed_count += 1

        logger.info(f"最近三天日记查看次数: {viewed_count}")

        provider = self.context.get_using_provider()
        if provider:
            if len(compacted_entries) < 2:
                summary_prompt = (
                    "今天的观察还比较少，请写一段简短、自然、不过度脑补的今日日记。"
                    "可以更克制一点，但仍然要保留一点真实感和陪伴感。"
                    "字数控制在 180 到 320 字。"
                )
            else:
                reference_days = []
                if self.diary_reference_days > 0:
                    for i in range(1, self.diary_reference_days + 1):
                        past_date = target_date - datetime.timedelta(days=i)
                        past_diary_path = self._get_diary_file_path(past_date)
                        if os.path.exists(past_diary_path):
                            try:
                                with open(past_diary_path, encoding="utf-8") as f:
                                    past_diary_content = f.read()
                                reference_days.append(
                                    {
                                        "date": past_date.strftime("%Y-%m-%d"),
                                        "content": past_diary_content,
                                    }
                                )
                            except Exception as e:
                                logger.error(f"读取前几天日记失败: {e}")

                summary_prompt = self._build_diary_reflection_prompt(
                    observation_text=observation_text,
                    viewed_count=viewed_count,
                    reference_days=reference_days,
                )

            try:
                system_prompt = await self._get_persona_prompt()
                response = await provider.text_chat(
                    prompt=summary_prompt,
                    system_prompt=system_prompt,
                )
                if (
                    response
                    and hasattr(response, "completion_text")
                    and response.completion_text
                ):
                    reflection_text = self._ensure_diary_reflection_text(
                        response.completion_text,
                        observation_text,
                    )
            except Exception as e:
                logger.error(f"生成日记总结失败: {e}")

        structured_summary = self._build_diary_structured_summary(
            compacted_entries,
            reflection_text,
        )
        reflection_text = self._ensure_diary_reflection_text(
            reflection_text,
            observation_text,
            structured_summary,
        )
        if not structured_summary.get("suggestion_items"):
            structured_summary["suggestion_items"] = self._extract_actionable_suggestions(
                reflection_text,
                limit=3,
            )

        diary_content = self._build_diary_document(
            target_date=target_date,
            weekday=weekday,
            weather_info=weather_info,
            observation_text=observation_text,
            reflection_text=reflection_text,
            structured_summary=structured_summary,
        )

        if self._persist_diary_document(
            target_date=target_date,
            diary_content=diary_content,
            structured_summary=structured_summary,
        ):
            logger.info("日记生成完成，不自动发送，等待用户主动查看")
