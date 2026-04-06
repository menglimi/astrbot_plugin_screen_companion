# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

# 基于上游 astrbot_plugin_live_dashboard 的 app_descriptions 思路做了本地适配：
# 1. 保留常用应用描述与标题模板
# 2. 输出更适合作为提示词上下文的中性描述
# 3. 提供窗口标题 -> 应用名 / 场景 / 自然描述 的统一入口

DEFAULT_DESCRIPTION = "正在处理当前内容"

APP_PLACEHOLDER_VALUES = {
    "",
    "unknown",
    "null",
    "none",
    "windows",
    "macos",
    "linux",
    "android",
    "ios",
}

TITLE_PLACEHOLDER_VALUES = {
    "",
    "unknown",
    "null",
    "none",
    "主页",
    "首页",
    "新标签页",
    "new tab",
    "start page",
}

APP_DESCRIPTIONS: dict[str, str] = {
    "Telegram": "正在 Telegram 上聊天",
    "QQ": "正在 QQ 上聊天",
    "TIM": "正在 TIM 上聊天",
    "微信": "正在微信上聊天",
    "WeChat": "正在微信上聊天",
    "Discord": "正在 Discord 上聊天",
    "Slack": "正在 Slack 上沟通",
    "飞书": "正在飞书上办公",
    "Lark": "正在飞书上办公",
    "钉钉": "正在钉钉上办公",
    "企业微信": "正在企业微信上办公",
    "ChatGPT": "正在和 ChatGPT 对话",
    "Claude": "正在和 Claude 对话",
    "Gemini": "正在和 Gemini 对话",
    "Copilot": "正在和 Copilot 对话",
    "Kimi": "正在和 Kimi 对话",
    "豆包": "正在和豆包对话",
    "DeepSeek": "正在和 DeepSeek 对话",
    "Perplexity": "正在用 Perplexity 搜索",
    "Chrome": "正在用 Chrome 浏览内容",
    "Google Chrome": "正在用 Chrome 浏览内容",
    "Microsoft Edge": "正在用 Edge 浏览内容",
    "Firefox": "正在用 Firefox 浏览内容",
    "Safari": "正在用 Safari 浏览内容",
    "Opera": "正在用 Opera 浏览内容",
    "Arc": "正在用 Arc 浏览内容",
    "Brave": "正在用 Brave 浏览内容",
    "Vivaldi": "正在用 Vivaldi 浏览内容",
    "Bilibili": "正在看 B 站内容",
    "哔哩哔哩": "正在看 B 站内容",
    "YouTube": "正在看 YouTube 内容",
    "Netflix": "正在看流媒体内容",
    "Spotify": "正在听 Spotify",
    "网易云音乐": "正在听网易云音乐",
    "QQ音乐": "正在听 QQ 音乐",
    "VS Code": "正在用 VS Code 写代码",
    "Visual Studio Code": "正在用 VS Code 写代码",
    "Visual Studio": "正在用 Visual Studio 写代码",
    "Cursor": "正在用 Cursor 写代码",
    "Windsurf": "正在用 Windsurf 写代码",
    "Zed": "正在用 Zed 写代码",
    "PyCharm": "正在用 PyCharm 写代码",
    "IntelliJ IDEA": "正在用 IDEA 写代码",
    "WebStorm": "正在用 WebStorm 写代码",
    "GoLand": "正在用 GoLand 写代码",
    "Android Studio": "正在用 Android Studio 写代码",
    "CLion": "正在用 CLion 写代码",
    "RustRover": "正在用 RustRover 写代码",
    "Sublime Text": "正在用 Sublime Text 编辑内容",
    "Notepad++": "正在用 Notepad++ 编辑内容",
    "Vim": "正在用 Vim 编辑内容",
    "Neovim": "正在用 Neovim 编辑内容",
    "Docker Desktop": "正在用 Docker 处理容器",
    "GitHub Desktop": "正在用 GitHub Desktop 管理代码",
    "Postman": "正在用 Postman 调接口",
    "Insomnia": "正在用 Insomnia 调接口",
    "DBeaver": "正在用 DBeaver 查数据库",
    "Navicat": "正在用 Navicat 查数据库",
    "Figma": "正在用 Figma 做设计",
    "Photoshop": "正在用 Photoshop 修图",
    "Adobe Photoshop": "正在用 Photoshop 修图",
    "Illustrator": "正在用 Illustrator 画图",
    "Adobe Illustrator": "正在用 Illustrator 画图",
    "Premiere Pro": "正在用 Premiere 剪视频",
    "Adobe Premiere Pro": "正在用 Premiere 剪视频",
    "After Effects": "正在用 AE 做特效",
    "Adobe After Effects": "正在用 AE 做特效",
    "Blender": "正在用 Blender 做 3D",
    "剪映": "正在用剪映剪视频",
    "CapCut": "正在用剪映剪视频",
    "Word": "正在写文档",
    "Microsoft Word": "正在写文档",
    "Excel": "正在看表格",
    "Microsoft Excel": "正在看表格",
    "PowerPoint": "正在做演示文稿",
    "Microsoft PowerPoint": "正在做演示文稿",
    "Notion": "正在用 Notion 记录内容",
    "Obsidian": "正在用 Obsidian 记录内容",
    "Typora": "正在用 Typora 写内容",
    "WPS": "正在用 WPS 处理文档",
    "WPS Office": "正在用 WPS 处理文档",
    "PDF": "正在阅读文档",
    "Kindle": "正在阅读",
    "微信读书": "正在阅读",
    "Steam": "正在 Steam 上玩游戏",
    "Epic Games": "正在 Epic 上玩游戏",
    "Battle.net": "正在战网上玩游戏",
}

TITLE_TEMPLATES: list[tuple[tuple[str, ...], str]] = [
    (("ChatGPT", "Claude", "Gemini", "Kimi", "豆包", "DeepSeek"), "正在和「{title}」对话"),
    (("VS Code", "Visual Studio Code", "Cursor", "Windsurf", "Zed"), "正在写「{title}」"),
    (
        (
            "Visual Studio",
            "PyCharm",
            "IntelliJ IDEA",
            "WebStorm",
            "GoLand",
            "Android Studio",
            "CLion",
            "RustRover",
        ),
        "正在处理「{title}」",
    ),
    (("Postman", "Insomnia"), "正在调「{title}」"),
    (("DBeaver", "Navicat"), "正在查「{title}」数据库"),
    (("Figma",), "正在做「{title}」设计"),
    (("Photoshop", "Adobe Photoshop"), "正在修「{title}」"),
    (("Illustrator", "Adobe Illustrator"), "正在画「{title}」"),
    (("Premiere Pro", "Adobe Premiere Pro", "剪映", "CapCut"), "正在剪「{title}」"),
    (("After Effects", "Adobe After Effects"), "正在处理「{title}」特效"),
    (("Blender",), "正在做「{title}」"),
    (("Word", "Microsoft Word", "Typora", "Obsidian", "Notion", "WPS", "WPS Office"), "正在写「{title}」"),
    (("Excel", "Microsoft Excel"), "正在看「{title}」表格"),
    (("PowerPoint", "Microsoft PowerPoint"), "正在做「{title}」演示文稿"),
    (("Kindle", "微信读书", "PDF"), "正在看「{title}」"),
    (("Chrome", "Google Chrome", "Microsoft Edge", "Firefox", "Safari", "Opera", "Arc", "Brave", "Vivaldi"), "正在看「{title}」"),
    (("Bilibili", "哔哩哔哩", "YouTube", "Netflix"), "正在看「{title}」"),
    (("Spotify", "网易云音乐", "QQ音乐"), "正在听「{title}」"),
    (("Steam", "Epic Games", "Battle.net"), "正在玩「{title}」"),
]

APP_SCENES: dict[str, str] = {
    "Telegram": "社交",
    "QQ": "社交",
    "TIM": "社交",
    "微信": "社交",
    "WeChat": "社交",
    "Discord": "社交",
    "Slack": "办公",
    "飞书": "办公",
    "Lark": "办公",
    "钉钉": "办公",
    "企业微信": "办公",
    "ChatGPT": "浏览-工作",
    "Claude": "浏览-工作",
    "Gemini": "浏览-工作",
    "Copilot": "浏览-工作",
    "Kimi": "浏览-工作",
    "豆包": "浏览-工作",
    "DeepSeek": "浏览-工作",
    "Perplexity": "浏览-工作",
    "Chrome": "浏览",
    "Google Chrome": "浏览",
    "Microsoft Edge": "浏览",
    "Firefox": "浏览",
    "Safari": "浏览",
    "Opera": "浏览",
    "Arc": "浏览",
    "Brave": "浏览",
    "Vivaldi": "浏览",
    "Bilibili": "浏览-娱乐",
    "哔哩哔哩": "浏览-娱乐",
    "YouTube": "浏览-娱乐",
    "Netflix": "视频",
    "Spotify": "音乐",
    "网易云音乐": "音乐",
    "QQ音乐": "音乐",
    "VS Code": "编程",
    "Visual Studio Code": "编程",
    "Visual Studio": "编程",
    "Cursor": "编程",
    "Windsurf": "编程",
    "Zed": "编程",
    "PyCharm": "编程",
    "IntelliJ IDEA": "编程",
    "WebStorm": "编程",
    "GoLand": "编程",
    "Android Studio": "编程",
    "CLion": "编程",
    "RustRover": "编程",
    "Docker Desktop": "工具",
    "GitHub Desktop": "编程",
    "Postman": "编程",
    "Insomnia": "编程",
    "DBeaver": "工具",
    "Navicat": "工具",
    "Figma": "设计",
    "Photoshop": "设计",
    "Adobe Photoshop": "设计",
    "Illustrator": "设计",
    "Adobe Illustrator": "设计",
    "Premiere Pro": "设计",
    "Adobe Premiere Pro": "设计",
    "After Effects": "设计",
    "Adobe After Effects": "设计",
    "Blender": "设计",
    "剪映": "设计",
    "CapCut": "设计",
    "Word": "办公",
    "Microsoft Word": "办公",
    "Excel": "办公",
    "Microsoft Excel": "办公",
    "PowerPoint": "办公",
    "Microsoft PowerPoint": "办公",
    "Notion": "办公",
    "Obsidian": "阅读",
    "Typora": "阅读",
    "WPS": "办公",
    "WPS Office": "办公",
    "PDF": "阅读",
    "Kindle": "阅读",
    "微信读书": "阅读",
    "Steam": "游戏",
    "Epic Games": "游戏",
    "Battle.net": "游戏",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _is_placeholder(value: str, *, placeholder_values: set[str]) -> bool:
    text = _normalize_text(value)
    if not text:
        return True
    return text.lower() in placeholder_values or text in placeholder_values


def _sanitize_description(value: str) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    return text.replace("喵~", "").replace("喵", "").strip("，。；; ")


def _clean_display_title(title: str) -> str:
    normalized = _normalize_text(title)
    if _is_placeholder(normalized, placeholder_values=TITLE_PLACEHOLDER_VALUES):
        return ""
    normalized = re.sub(r"\s+", " ", normalized)
    if len(normalized) > 80:
        normalized = normalized[:77].rstrip("，。；;,. ") + "..."
    return normalized


ALL_APP_NAMES: list[str] = []
for bucket in (APP_DESCRIPTIONS.keys(), APP_SCENES.keys()):
    for app_name in bucket:
        if app_name not in ALL_APP_NAMES:
            ALL_APP_NAMES.append(app_name)
for aliases, _template in TITLE_TEMPLATES:
    for app_name in aliases:
        if app_name not in ALL_APP_NAMES:
            ALL_APP_NAMES.append(app_name)

ALL_APP_NAMES_SORTED = sorted(ALL_APP_NAMES, key=len, reverse=True)
APP_DESCRIPTIONS_LOWER = {name.lower(): _sanitize_description(desc) for name, desc in APP_DESCRIPTIONS.items()}
APP_SCENES_LOWER = {name.lower(): scene for name, scene in APP_SCENES.items()}
TITLE_TEMPLATES_LOWER: dict[str, str] = {}
CANONICAL_APP_NAMES: dict[str, str] = {}
for aliases, template in TITLE_TEMPLATES:
    canonical_name = aliases[0]
    for alias in aliases:
        TITLE_TEMPLATES_LOWER[alias.lower()] = template
        CANONICAL_APP_NAMES.setdefault(alias.lower(), canonical_name)
for app_name in ALL_APP_NAMES:
    CANONICAL_APP_NAMES.setdefault(app_name.lower(), app_name)


def _split_window_candidates(window_title: str) -> list[str]:
    separators = (" - ", " | ", " — ", " – ", " · ", " • ", " —", " — ")
    candidates = [window_title]
    for separator in separators:
        next_candidates: list[str] = []
        for item in candidates:
            if separator in item:
                next_candidates.extend(part.strip() for part in item.split(separator))
            else:
                next_candidates.append(item)
        candidates = next_candidates

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = _normalize_text(candidate)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def _resolve_canonical_app_name(app_name: str) -> str:
    normalized = _normalize_text(app_name)
    if not normalized:
        return ""
    return CANONICAL_APP_NAMES.get(normalized.lower(), normalized)


def extract_app_name(window_title: str) -> str:
    title = _normalize_text(window_title)
    if _is_placeholder(title, placeholder_values=APP_PLACEHOLDER_VALUES):
        return ""

    candidates = _split_window_candidates(title)
    exact_matches: list[tuple[int, int, str]] = []
    for index, candidate in enumerate(candidates):
        key = candidate.lower()
        if key in CANONICAL_APP_NAMES:
            canonical = _resolve_canonical_app_name(candidate)
            scene = APP_SCENES_LOWER.get(key, "")
            score = 0 if scene == "浏览" else 1
            exact_matches.append((score, index, canonical))
    if exact_matches:
        exact_matches.sort(key=lambda item: (-item[0], item[1], -len(item[2])))
        return exact_matches[0][2]

    lowered_title = title.lower()
    contains_matches: list[tuple[int, int, str]] = []
    for app_name in ALL_APP_NAMES_SORTED:
        key = app_name.lower()
        if key in lowered_title:
            scene = APP_SCENES_LOWER.get(key, "")
            score = 0 if scene == "浏览" else 1
            contains_matches.append((score, len(app_name), _resolve_canonical_app_name(app_name)))
    if contains_matches:
        contains_matches.sort(key=lambda item: (-item[0], -item[1]))
        return contains_matches[0][2]

    return ""


def extract_display_title(window_title: str, app_name: str = "") -> str:
    title = _normalize_text(window_title)
    if _is_placeholder(title, placeholder_values=TITLE_PLACEHOLDER_VALUES):
        return ""

    normalized_app_name = _resolve_canonical_app_name(app_name)
    if not normalized_app_name:
        normalized_app_name = extract_app_name(title)

    candidates = _split_window_candidates(title)
    filtered_candidates = [
        candidate
        for candidate in candidates
        if candidate.casefold() != normalized_app_name.casefold()
    ]

    preferred_candidates = [
        candidate
        for candidate in filtered_candidates
        if not _is_placeholder(candidate, placeholder_values=TITLE_PLACEHOLDER_VALUES)
    ]
    preferred_candidates = [
        candidate
        for candidate in preferred_candidates
        if len(candidate) >= 2 and candidate.casefold() != title.casefold()
    ]
    if preferred_candidates:
        return _clean_display_title(preferred_candidates[0])

    stripped = title
    if normalized_app_name:
        patterns = [
            rf"^\s*{re.escape(normalized_app_name)}\s*[-|—–·•]\s*",
            rf"\s*[-|—–·•]\s*{re.escape(normalized_app_name)}\s*$",
        ]
        for pattern in patterns:
            stripped = re.sub(pattern, "", stripped, flags=re.IGNORECASE)
    stripped = _clean_display_title(stripped)
    if stripped.casefold() == normalized_app_name.casefold():
        return ""
    return stripped


def infer_scene_from_window_title(window_title: str) -> str:
    app_name = extract_app_name(window_title)
    if not app_name:
        return ""
    return APP_SCENES_LOWER.get(app_name.lower(), "")


def describe_window_activity(window_title: str, scene: str = "") -> dict[str, str]:
    title = _normalize_text(window_title)
    app_name = extract_app_name(title)
    display_title = extract_display_title(title, app_name=app_name)
    normalized_scene = _normalize_text(scene) or infer_scene_from_window_title(title)

    description = ""
    if app_name and display_title:
        template = TITLE_TEMPLATES_LOWER.get(app_name.lower(), "")
        if template:
            description = template.format(title=display_title)
    if not description and app_name:
        description = APP_DESCRIPTIONS_LOWER.get(app_name.lower(), "")
    if not description and display_title:
        if normalized_scene in {"编程", "设计", "办公", "阅读"}:
            description = f"正在处理「{display_title}」"
        elif normalized_scene in {"视频", "浏览", "浏览-工作", "浏览-娱乐"}:
            description = f"正在看「{display_title}」"
        elif normalized_scene == "音乐":
            description = f"正在听「{display_title}」"
        elif normalized_scene == "游戏":
            description = f"正在处理「{display_title}」"
    if not description:
        description = DEFAULT_DESCRIPTION

    return {
        "app_name": app_name,
        "display_title": display_title,
        "scene": normalized_scene,
        "description": _sanitize_description(description),
    }
