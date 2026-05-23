# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import logger


class ScreenCompanionInputStatsMixin:
    INPUT_STATS_RETENTION_DAYS = 0
    INPUT_MOVE_SAMPLE_INTERVAL_SECONDS = 0.25
    INPUT_MOVE_MIN_PIXELS = 12
    INPUT_IDLE_THRESHOLD_SECONDS = 5 * 60
    INPUT_AWAY_THRESHOLD_SECONDS = 20 * 60

    def _ensure_input_stats_state(self) -> None:
        if not hasattr(self, "input_stats_daily") or not isinstance(getattr(self, "input_stats_daily", None), dict):
            self.input_stats_daily = {}
        if not hasattr(self, "enable_input_stats"):
            self.enable_input_stats = False
        if not hasattr(self, "input_stats_flush_interval"):
            self.input_stats_flush_interval = 60
        if not hasattr(self, "input_stats_file"):
            base_dir = str(getattr(self, "learning_storage", "") or "")
            self.input_stats_file = os.path.join(base_dir, "input_stats_daily.json") if base_dir else ""
        if not hasattr(self, "_input_stats_lock") or self._input_stats_lock is None:
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

    @staticmethod
    def _build_empty_input_stats_entry(day_key: str) -> dict[str, Any]:
        return {
            "date": day_key,
            "keys": 0,
            "clicks": 0,
            "scroll_steps": 0,
            "moves": 0,
            "move_pixels": 0,
            "last_event_at": "",
            "hourly": {},
            "minute_buckets": {},
        }

    def _prune_input_stats_history(self) -> None:
        if int(self.INPUT_STATS_RETENTION_DAYS or 0) <= 0:
            return
        retention_days = max(1, int(self.INPUT_STATS_RETENTION_DAYS))
        cutoff_date = datetime.now().date() - timedelta(days=retention_days - 1)
        removable_keys = []
        for day_key in list(getattr(self, "input_stats_daily", {}).keys()):
            try:
                day_value = datetime.strptime(str(day_key), "%Y-%m-%d").date()
            except Exception:
                removable_keys.append(day_key)
                continue
            if day_value < cutoff_date:
                removable_keys.append(day_key)
        for key in removable_keys:
            self.input_stats_daily.pop(key, None)

    def _sanitize_input_stats_daily(self, raw_data: Any) -> dict[str, dict[str, Any]]:
        cleaned: dict[str, dict[str, Any]] = {}
        if not isinstance(raw_data, dict):
            return cleaned

        for raw_day, payload in raw_data.items():
            day_key = str(raw_day or "").strip()
            try:
                datetime.strptime(day_key, "%Y-%m-%d")
            except Exception:
                continue

            item = self._build_empty_input_stats_entry(day_key)
            if isinstance(payload, dict):
                item["keys"] = max(0, int(payload.get("keys", 0) or 0))
                item["clicks"] = max(0, int(payload.get("clicks", 0) or 0))
                item["scroll_steps"] = max(0, int(payload.get("scroll_steps", 0) or 0))
                item["moves"] = max(0, int(payload.get("moves", 0) or 0))
                item["move_pixels"] = max(0, int(payload.get("move_pixels", 0) or 0))
                item["last_event_at"] = str(payload.get("last_event_at", "") or "").strip()

                hourly = payload.get("hourly", {})
                if isinstance(hourly, dict):
                    normalized_hourly = {}
                    for hour_key, hour_payload in hourly.items():
                        hour_text = str(hour_key or "").strip().zfill(2)
                        if not hour_text.isdigit():
                            continue
                        if not 0 <= int(hour_text) <= 23:
                            continue
                        info = hour_payload if isinstance(hour_payload, dict) else {}
                        normalized_hourly[hour_text] = {
                            "keys": max(0, int(info.get("keys", 0) or 0)),
                            "clicks": max(0, int(info.get("clicks", 0) or 0)),
                            "scroll_steps": max(0, int(info.get("scroll_steps", 0) or 0)),
                            "moves": max(0, int(info.get("moves", 0) or 0)),
                            "move_pixels": max(0, int(info.get("move_pixels", 0) or 0)),
                            "events": max(0, int(info.get("events", 0) or 0)),
                        }
                    item["hourly"] = normalized_hourly

                minute_buckets = payload.get("minute_buckets", {})
                if isinstance(minute_buckets, dict):
                    normalized_minutes = {}
                    for minute_key, minute_count in minute_buckets.items():
                        minute_text = str(minute_key or "").strip()
                        if len(minute_text) != 5 or minute_text[2] != ":":
                            continue
                        normalized_minutes[minute_text] = max(0, int(minute_count or 0))
                    item["minute_buckets"] = normalized_minutes

            cleaned[day_key] = item

        return cleaned

    def _load_input_stats_daily(self) -> None:
        self._ensure_input_stats_state()
        input_stats_file = str(getattr(self, "input_stats_file", "") or "").strip()
        if not input_stats_file or not os.path.exists(input_stats_file):
            self.input_stats_daily = {}
            self._refresh_input_stats_last_event_at()
            return
        try:
            with open(input_stats_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            self.input_stats_daily = self._sanitize_input_stats_daily(raw_data)
            self._prune_input_stats_history()
            self._refresh_input_stats_last_event_at()
        except Exception as e:
            logger.warning(f"加载输入统计失败: {e}")
            self.input_stats_daily = {}
            self._refresh_input_stats_last_event_at()

    def _save_input_stats_daily(self, force: bool = False) -> bool:
        self._ensure_input_stats_state()
        input_stats_file = str(getattr(self, "input_stats_file", "") or "").strip()
        if not input_stats_file:
            return False
        if not force and not bool(getattr(self, "_input_stats_dirty", False)):
            return False

        with self._input_stats_lock:
            self._prune_input_stats_history()
            payload = copy.deepcopy(self.input_stats_daily)
            self._input_stats_dirty = False

        try:
            os.makedirs(os.path.dirname(input_stats_file), exist_ok=True)
            with open(input_stats_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            self._input_stats_last_flush_time = time.time()
            return True
        except Exception as e:
            logger.warning(f"保存输入统计失败: {e}")
            with self._input_stats_lock:
                self._input_stats_dirty = True
            return False

    def _set_input_stats_status(self, status: str, detail: str) -> None:
        self._ensure_input_stats_state()
        self._input_stats_status = str(status or "").strip() or "unknown"
        self._input_stats_status_detail = str(detail or "").strip()

        runtime_event = getattr(self, "_remember_learning_runtime_event", None)
        if callable(runtime_event):
            runtime_event(
                "input_stats",
                self._input_stats_status,
                self._input_stats_status_detail or "本地输入统计状态已更新",
            )

    def _get_or_create_input_stats_day(self, day_key: str) -> dict[str, Any]:
        existing = self.input_stats_daily.get(day_key)
        if isinstance(existing, dict):
            return existing
        entry = self._build_empty_input_stats_entry(day_key)
        self.input_stats_daily[day_key] = entry
        return entry

    def _refresh_input_stats_last_event_at(self) -> str:
        self._ensure_input_stats_state()
        latest_event_at = ""
        with self._input_stats_lock:
            for day_key in sorted((getattr(self, "input_stats_daily", {}) or {}).keys(), reverse=True):
                entry = self.input_stats_daily.get(day_key, {})
                if not isinstance(entry, dict):
                    continue
                candidate = str(entry.get("last_event_at", "") or "").strip()
                if candidate:
                    latest_event_at = candidate
                    break
            self._input_stats_last_event_at = latest_event_at
        return latest_event_at

    def _record_input_event(
        self,
        kind: str,
        amount: int = 1,
        *,
        now_dt: datetime | None = None,
        count_event: bool = True,
    ) -> None:
        self._ensure_input_stats_state()
        now = now_dt or datetime.now()
        day_key = now.strftime("%Y-%m-%d")
        hour_key = now.strftime("%H")
        minute_key = now.strftime("%H:%M")
        amount_value = max(0, int(amount or 0))
        if amount_value <= 0:
            return

        with self._input_stats_lock:
            entry = self._get_or_create_input_stats_day(day_key)
            if kind == "keys":
                entry["keys"] += amount_value
            elif kind == "clicks":
                entry["clicks"] += amount_value
            elif kind == "scroll_steps":
                entry["scroll_steps"] += amount_value
            elif kind == "moves":
                entry["moves"] += 1
                entry["move_pixels"] += amount_value
            else:
                return

            hourly = entry.setdefault("hourly", {})
            hour_bucket = hourly.setdefault(
                hour_key,
                {
                    "keys": 0,
                    "clicks": 0,
                    "scroll_steps": 0,
                    "moves": 0,
                    "move_pixels": 0,
                    "events": 0,
                },
            )
            if kind == "moves":
                hour_bucket["moves"] += 1
                hour_bucket["move_pixels"] += amount_value
            else:
                hour_bucket[kind] += amount_value
            if count_event:
                hour_bucket["events"] += amount_value
            else:
                hour_bucket["events"] += 1

            minute_buckets = entry.setdefault("minute_buckets", {})
            minute_buckets[minute_key] = max(0, int(minute_buckets.get(minute_key, 0) or 0)) + 1
            entry["last_event_at"] = now.isoformat()
            self._input_stats_last_event_at = entry["last_event_at"]
            self._input_stats_dirty = True

    def _handle_input_key_press(self, _key: Any) -> None:
        self._record_input_event("keys", 1)

    def _handle_input_mouse_click(self, _x: int, _y: int, _button: Any, pressed: bool) -> None:
        if pressed:
            self._record_input_event("clicks", 1)

    def _handle_input_mouse_scroll(self, _x: int, _y: int, dx: int, dy: int) -> None:
        steps = max(abs(int(dx or 0)), abs(int(dy or 0)), 1)
        self._record_input_event("scroll_steps", steps)

    def _handle_input_mouse_move(self, x: int, y: int) -> None:
        self._ensure_input_stats_state()
        now_ts = time.time()
        last_position = getattr(self, "_input_stats_last_mouse_position", None)
        self._input_stats_last_mouse_position = (int(x or 0), int(y or 0))
        if not last_position:
            return
        if now_ts - float(getattr(self, "_input_stats_last_move_time", 0.0) or 0.0) < self.INPUT_MOVE_SAMPLE_INTERVAL_SECONDS:
            return

        dx = float((x or 0) - last_position[0])
        dy = float((y or 0) - last_position[1])
        distance = int(round(math.hypot(dx, dy)))
        if distance < self.INPUT_MOVE_MIN_PIXELS:
            return

        self._input_stats_last_move_time = now_ts
        self._record_input_event("moves", distance, count_event=False)

    def _stop_input_stats_listener(self, *, reason: str = "manual") -> None:
        self._ensure_input_stats_state()
        listeners = list(getattr(self, "_input_stats_listeners", []) or [])
        self._input_stats_listeners = []
        for listener in listeners:
            try:
                listener.stop()
            except Exception:
                continue

        self._input_stats_last_mouse_position = None
        self._input_stats_last_move_time = 0.0
        self._save_input_stats_daily(force=True)

        if not self.enable_input_stats:
            self._set_input_stats_status("disabled", "本地输入统计未启用")
        elif reason == "shutdown":
            self._set_input_stats_status("stopped", "插件已停止，本地输入统计监听已关闭")
        else:
            self._set_input_stats_status("stopped", "本地输入统计监听已关闭")

    def _ensure_input_stats_listener(self) -> bool:
        self._ensure_input_stats_state()
        if not self.enable_input_stats:
            self._set_input_stats_status("disabled", "本地输入统计未启用")
            return False
        if getattr(self, "_input_stats_listeners", None):
            self._set_input_stats_status("running", "本地输入统计正在监听键盘和鼠标")
            return True

        try:
            from pynput import keyboard, mouse
        except ImportError:
            self._set_input_stats_status(
                "missing_dependency",
                "未安装 pynput。请先确认已安装 requirements.txt；旧版安装流程也可以单独执行 requirements-optional-input.txt。",
            )
            return False
        except Exception as e:
            self._set_input_stats_status("error", f"加载 pynput 失败: {e}")
            return False

        listeners = []
        try:
            keyboard_listener = keyboard.Listener(on_press=self._handle_input_key_press)
            mouse_listener = mouse.Listener(
                on_click=self._handle_input_mouse_click,
                on_scroll=self._handle_input_mouse_scroll,
                on_move=self._handle_input_mouse_move,
            )
            listeners = [keyboard_listener, mouse_listener]
            for listener in listeners:
                listener.start()
            self._input_stats_listeners = listeners
            self._set_input_stats_status("running", "本地输入统计已启动，将记录键盘和鼠标输入。")
            return True
        except Exception as e:
            for listener in listeners:
                try:
                    listener.stop()
                except Exception:
                    continue
            self._input_stats_listeners = []
            self._set_input_stats_status("error", f"启动本地输入统计失败: {e}")
            return False

    async def _input_stats_flush_task(self) -> None:
        self._ensure_input_stats_state()
        while getattr(self, "running", False) and not bool(getattr(self, "_is_stopping", False)):
            await asyncio.sleep(10)
            flush_interval = max(10, int(getattr(self, "input_stats_flush_interval", 60) or 60))
            last_flush_time = float(getattr(self, "_input_stats_last_flush_time", 0.0) or 0.0)
            if bool(getattr(self, "_input_stats_dirty", False)) and (time.time() - last_flush_time) >= flush_interval:
                await asyncio.to_thread(self._save_input_stats_daily)

    def _get_input_stats_runtime_status(self) -> dict[str, Any]:
        self._ensure_input_stats_state()
        payload = self._build_input_stats_payload(days=7)
        return {
            "enabled": bool(self.enable_input_stats),
            "status": str(getattr(self, "_input_stats_status", "disabled") or "disabled"),
            "detail": str(getattr(self, "_input_stats_status_detail", "") or ""),
            "today": payload.get("today", {}),
            "presence_status": payload.get("presence_status", "disabled"),
            "presence_label": payload.get("presence_label", "未启用本地输入统计"),
            "presence_detail": payload.get("presence_detail", ""),
            "idle_seconds": int(payload.get("idle_seconds", 0) or 0),
            "idle_label": payload.get("idle_label", ""),
            "latest_event_at": payload.get("latest_event_at", ""),
        }

    def _get_input_presence_snapshot(self) -> dict[str, Any]:
        self._ensure_input_stats_state()
        last_event_at = str(getattr(self, "_input_stats_last_event_at", "") or "").strip()
        if not last_event_at:
            last_event_at = self._refresh_input_stats_last_event_at()
        presence = self._build_input_presence(last_event_at)
        return {
            "enabled": bool(self.enable_input_stats),
            "status": str(getattr(self, "_input_stats_status", "disabled") or "disabled"),
            "detail": str(getattr(self, "_input_stats_status_detail", "") or ""),
            **presence,
        }

    @staticmethod
    def _format_move_distance(move_pixels: int | float) -> str:
        pixels = max(0, int(move_pixels or 0))
        if pixels >= 10000:
            return f"{pixels / 1000:.1f}k px"
        return f"{pixels} px"

    @staticmethod
    def _format_count(value: int | float, suffix: str = "") -> str:
        count = max(0, int(value or 0))
        return f"{count}{suffix}"

    @staticmethod
    def _parse_input_stats_event_time(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    @classmethod
    def _format_elapsed_seconds(cls, value: int | float | None) -> str:
        seconds = max(0, int(value or 0))
        if seconds <= 15:
            return "刚刚"
        if seconds < 60:
            return "1 分钟内"
        if seconds < 3600:
            return f"{int(math.ceil(seconds / 60))} 分钟"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours >= 24:
            days = hours // 24
            remain_hours = hours % 24
            if remain_hours > 0:
                return f"{days} 天 {remain_hours} 小时"
            return f"{days} 天"
        if minutes > 0:
            return f"{hours} 小时 {minutes} 分钟"
        return f"{hours} 小时"

    def _build_input_presence(self, last_event_at: Any) -> dict[str, Any]:
        event_time = self._parse_input_stats_event_time(last_event_at)
        if event_time is None:
            if not bool(getattr(self, "enable_input_stats", False)):
                return {
                    "presence_status": "disabled",
                    "presence_label": "未启用输入统计",
                    "presence_detail": "当前只按窗口活动估算工作节奏。",
                    "idle_seconds": 0,
                    "idle_label": "",
                    "latest_event_at": "",
                }
            return {
                "presence_status": "no_data",
                "presence_label": "等待输入样本",
                "presence_detail": "输入监听已启动，等你开始敲键盘或移动鼠标后这里会变得更准确。",
                "idle_seconds": 0,
                "idle_label": "",
                "latest_event_at": "",
            }

        idle_seconds = max(0, int((datetime.now() - event_time).total_seconds()))
        idle_label = self._format_elapsed_seconds(idle_seconds)
        if idle_seconds <= self.INPUT_IDLE_THRESHOLD_SECONDS:
            return {
                "presence_status": "active",
                "presence_label": "刚刚还有输入",
                "presence_detail": f"最近 {idle_label} 有过键鼠输入，当前状态更接近真实在场。",
                "idle_seconds": idle_seconds,
                "idle_label": idle_label,
                "latest_event_at": event_time.isoformat(),
            }
        if idle_seconds <= self.INPUT_AWAY_THRESHOLD_SECONDS:
            return {
                "presence_status": "idle",
                "presence_label": "短暂离开",
                "presence_detail": f"最近 {idle_label} 没有输入，可能是在看屏幕、思考或临时走开。",
                "idle_seconds": idle_seconds,
                "idle_label": idle_label,
                "latest_event_at": event_time.isoformat(),
            }
        return {
            "presence_status": "away",
            "presence_label": "长时间空闲",
            "presence_detail": f"已经约 {idle_label} 没有输入，更像是离开工位或暂停使用。",
            "idle_seconds": idle_seconds,
            "idle_label": idle_label,
            "latest_event_at": event_time.isoformat(),
        }

    def _summarize_input_stats_entry(self, day_key: str, raw_entry: dict[str, Any] | None) -> dict[str, Any]:
        entry = raw_entry if isinstance(raw_entry, dict) else self._build_empty_input_stats_entry(day_key)
        keys = max(0, int(entry.get("keys", 0) or 0))
        clicks = max(0, int(entry.get("clicks", 0) or 0))
        scroll_steps = max(0, int(entry.get("scroll_steps", 0) or 0))
        moves = max(0, int(entry.get("moves", 0) or 0))
        move_pixels = max(0, int(entry.get("move_pixels", 0) or 0))
        hourly = entry.get("hourly", {}) if isinstance(entry.get("hourly", {}), dict) else {}
        minute_buckets = entry.get("minute_buckets", {}) if isinstance(entry.get("minute_buckets", {}), dict) else {}
        active_minutes = len(minute_buckets)
        total_inputs = keys + clicks + scroll_steps
        peak_hour = ""
        peak_hour_value = -1
        for hour_key, hour_payload in hourly.items():
            info = hour_payload if isinstance(hour_payload, dict) else {}
            events = int(info.get("events", 0) or 0)
            if events > peak_hour_value:
                peak_hour_value = events
                peak_hour = str(hour_key).zfill(2)

        peak_hour_label = f"{peak_hour}:00-{peak_hour}:59" if peak_hour else "暂无"
        last_event_at = str(entry.get("last_event_at", "") or "").strip()
        try:
            day_date = datetime.strptime(day_key, "%Y-%m-%d").date()
        except Exception:
            day_date = datetime.now().date()
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        if day_date == today:
            label = "今天"
        elif day_date == yesterday:
            label = "昨天"
        else:
            label = day_date.strftime("%m-%d")

        return {
            "date": day_key,
            "label": label,
            "keys": keys,
            "keys_label": self._format_count(keys, " 次"),
            "clicks": clicks,
            "clicks_label": self._format_count(clicks, " 次"),
            "scroll_steps": scroll_steps,
            "scroll_steps_label": self._format_count(scroll_steps, " 格"),
            "moves": moves,
            "moves_label": self._format_count(moves, " 段"),
            "move_pixels": move_pixels,
            "move_pixels_label": self._format_move_distance(move_pixels),
            "total_inputs": total_inputs,
            "total_inputs_label": self._format_count(total_inputs, " 次"),
            "active_minutes": active_minutes,
            "active_minutes_label": self._format_count(active_minutes, " 分钟"),
            "peak_hour": peak_hour,
            "peak_hour_label": peak_hour_label,
            "last_event_at": last_event_at,
            "last_event_time_label": last_event_at[11:16] if len(last_event_at) >= 16 else "",
        }

    def _build_input_stats_payload(self, days: int = 7) -> dict[str, Any]:
        self._ensure_input_stats_state()
        with self._input_stats_lock:
            raw_daily = copy.deepcopy(getattr(self, "input_stats_daily", {}) or {})

        today = datetime.now().date()
        target_days = max(1, int(days or 7))
        day_keys = [
            (today - timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in reversed(range(target_days))
        ]
        recent_days = [
            self._summarize_input_stats_entry(day_key, raw_daily.get(day_key))
            for day_key in day_keys
        ]
        all_days = [
            self._summarize_input_stats_entry(day_key, raw_daily.get(day_key))
            for day_key in sorted(raw_daily.keys())
        ]
        today_summary = recent_days[-1] if recent_days else self._summarize_input_stats_entry(today.strftime("%Y-%m-%d"), {})
        total_inputs = sum(int(item.get("total_inputs", 0) or 0) for item in recent_days)
        total_active_minutes = sum(int(item.get("active_minutes", 0) or 0) for item in recent_days)
        all_total_inputs = sum(int(item.get("total_inputs", 0) or 0) for item in all_days)
        all_active_minutes = sum(int(item.get("active_minutes", 0) or 0) for item in all_days)
        all_active_days = sum(
            1
            for item in all_days
            if int(item.get("total_inputs", 0) or 0) > 0
            or int(item.get("move_pixels", 0) or 0) > 0
        )
        window_has_data = any(
            int(item.get("total_inputs", 0) or 0) > 0
            or int(item.get("move_pixels", 0) or 0) > 0
            for item in recent_days
        )
        has_any_data = window_has_data or all_active_days > 0
        latest_event_at = ""
        event_days = all_days if all_days else recent_days
        for item in reversed(event_days):
            candidate = str(item.get("last_event_at", "") or "").strip()
            if candidate:
                latest_event_at = candidate
                break
        presence = self._build_input_presence(latest_event_at if has_any_data else "")

        return {
            "enabled": bool(self.enable_input_stats),
            "available": has_any_data,
            "status": str(getattr(self, "_input_stats_status", "disabled") or "disabled"),
            "detail": str(getattr(self, "_input_stats_status_detail", "") or ""),
            "today": today_summary,
            "recent_days": recent_days,
            "window_total_inputs": total_inputs,
            "window_total_inputs_label": self._format_count(total_inputs, " 次"),
            "window_active_minutes": total_active_minutes,
            "window_active_minutes_label": self._format_count(total_active_minutes, " 分钟"),
            "all_total_inputs": all_total_inputs,
            "all_total_inputs_label": self._format_count(all_total_inputs, " 次"),
            "all_active_minutes": all_active_minutes,
            "all_active_minutes_label": self._format_count(all_active_minutes, " 分钟"),
            "all_days_count": len(all_days),
            "all_days_count_label": self._format_count(len(all_days), " 天"),
            "all_active_days": all_active_days,
            "all_active_days_label": self._format_count(all_active_days, " 天"),
            "retention_days": int(self.INPUT_STATS_RETENTION_DAYS),
            "retention_days_label": (
                "永久"
                if int(self.INPUT_STATS_RETENTION_DAYS or 0) <= 0
                else self._format_count(int(self.INPUT_STATS_RETENTION_DAYS), " 天")
            ),
            "latest_event_at": latest_event_at,
            **presence,
        }

    @staticmethod
    def _format_input_stats_time_ranges(
        minute_buckets: dict[str, Any] | None,
        *,
        limit: int = 6,
    ) -> list[str]:
        if not isinstance(minute_buckets, dict) or not minute_buckets:
            return []

        minute_keys = sorted(
            minute_key
            for minute_key in minute_buckets.keys()
            if isinstance(minute_key, str) and len(minute_key) == 5 and minute_key[2] == ":"
        )
        if not minute_keys:
            return []

        ranges: list[tuple[int, int]] = []
        current_start: int | None = None
        current_end: int | None = None

        for minute_key in minute_keys:
            hour = int(minute_key[:2])
            minute = int(minute_key[3:])
            current_value = hour * 60 + minute
            if current_start is None:
                current_start = current_value
                current_end = current_value
                continue
            if current_value <= (current_end or current_value) + 1:
                current_end = current_value
                continue
            ranges.append((current_start, current_end or current_start))
            current_start = current_value
            current_end = current_value

        if current_start is not None:
            ranges.append((current_start, current_end or current_start))

        def format_clock(total_minutes: int) -> str:
            hour = max(0, min(23, total_minutes // 60))
            minute = max(0, min(59, total_minutes % 60))
            return f"{hour:02d}:{minute:02d}"

        labels = []
        for start_value, end_value in ranges[: max(1, int(limit or 6))]:
            if start_value == end_value:
                labels.append(format_clock(start_value))
            else:
                labels.append(f"{format_clock(start_value)}-{format_clock(end_value)}")
        return labels

    def _build_today_input_stats_report(self) -> dict[str, Any]:
        self._ensure_input_stats_state()
        payload = self._build_input_stats_payload(days=1)
        today_key = datetime.now().strftime("%Y-%m-%d")
        with self._input_stats_lock:
            raw_entry = copy.deepcopy((getattr(self, "input_stats_daily", {}) or {}).get(today_key, {}))
        summary = payload.get("today", {}) if isinstance(payload, dict) else {}
        minute_buckets = raw_entry.get("minute_buckets", {}) if isinstance(raw_entry, dict) else {}
        active_ranges = self._format_input_stats_time_ranges(minute_buckets, limit=8)

        total_activity = (
            int(summary.get("total_inputs", 0) or 0)
            + int(summary.get("moves", 0) or 0)
        )
        available = bool(
            payload.get("enabled")
            and (
                total_activity > 0
                or int(summary.get("move_pixels", 0) or 0) > 0
                or bool(str(summary.get("last_event_at", "") or "").strip())
            )
        )

        return {
            "enabled": bool(payload.get("enabled")),
            "available": available,
            "status": str(payload.get("status", "") or ""),
            "detail": str(payload.get("detail", "") or ""),
            "presence_label": str(payload.get("presence_label", "") or ""),
            "presence_detail": str(payload.get("presence_detail", "") or ""),
            "idle_label": str(payload.get("idle_label", "") or ""),
            "latest_event_at": str(payload.get("latest_event_at", "") or ""),
            "today": summary,
            "active_ranges": active_ranges,
            "active_ranges_label": "、".join(active_ranges) if active_ranges else "暂无",
        }

    def _format_today_input_stats_text(self) -> str:
        report = self._build_today_input_stats_report()
        if not report.get("enabled"):
            detail = str(report.get("detail", "") or "本地输入统计未启用。")
            return f"今日本地输入统计\n\n{detail}"

        if not report.get("available"):
            lines = ["今日本地输入统计"]
            detail = str(report.get("detail", "") or "").strip()
            presence_detail = str(report.get("presence_detail", "") or "").strip()
            if detail:
                lines.append("")
                lines.append(detail)
            elif presence_detail:
                lines.append("")
                lines.append(presence_detail)
            else:
                lines.append("")
                lines.append("今天还没有采集到有效的键盘或鼠标输入。")
            return "\n".join(lines)

        today = report.get("today", {}) if isinstance(report.get("today"), dict) else {}
        lines = [
            "今日本地输入统计",
            "",
            f"- 键盘：{today.get('keys_label', '0 次')}",
            f"- 点击：{today.get('clicks_label', '0 次')}",
            f"- 滚轮：{today.get('scroll_steps_label', '0 格')}",
            f"- 鼠标移动：{today.get('moves_label', '0 段')} / {today.get('move_pixels_label', '0 px')}",
            f"- 活跃分钟：{today.get('active_minutes_label', '0 分钟')}",
            f"- 输入总量：{today.get('total_inputs_label', '0 次')}",
            f"- 高峰时段：{today.get('peak_hour_label', '暂无')}",
            f"- 活跃区间：{report.get('active_ranges_label', '暂无')}",
        ]

        latest_event_at = str(today.get("last_event_at", "") or "").strip()
        if latest_event_at:
            lines.append(
                f"- 最近一次输入：{today.get('last_event_time_label', latest_event_at[11:16] if len(latest_event_at) >= 16 else latest_event_at)}"
            )
        presence_label = str(report.get("presence_label", "") or "").strip()
        if presence_label:
            detail = str(report.get("presence_detail", "") or "").strip()
            lines.append(f"- 当前在场感：{presence_label}{f'，{detail}' if detail else ''}")
        return "\n".join(lines)
