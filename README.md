# 我会一直看着你（`astrbot_plugin_screen_companion`）

面向 AstrBot 的屏幕伴侣插件。它会结合截图分析、环境感知、长期记忆、日记记录和 WebUI，为用户提供更自然、更有价值的陪伴式互动体验。

## 主要功能

- 自动截图观察，按设定间隔和触发概率分析当前屏幕
- 观察去重和低价值过滤，减少流水账和噪音记忆
- 自然语言识屏求助，可选开启后支持“帮我看看这题/这局/这个页面”
- 长期记忆和日记系统，支持持续积累、压缩和按天回顾
- WebUI 管理面板，支持查看运行状态、日记、观察记录、长期记忆和配置
- Docker 共享截图目录适配，默认关闭，普通桌面环境优先实时截图
- 窗口自动陪伴，可指定窗口关键字，窗口出现时自动把 Bot 叫来，关闭时自动退出

## 运行环境

推荐在带图形界面的桌面环境中使用：

- Windows
- macOS
- Linux 图形桌面

需要具备：

- 屏幕截图权限
- 如启用麦克风监听，需要麦克风权限
- 已正确配置视觉模型或外部视觉 API

## 安装

1. 克隆仓库

```bash
git clone https://github.com/menglimi/astrbot_plugin_screen_companion.git
```

2. 将插件目录放入 AstrBot 插件目录，例如：

```text
C:\Users\你的用户名\.astrbot\data\plugins\
```

3. 安装依赖

```bash
pip install -r requirements.txt
```

4. 重启 AstrBot

## 依赖

常见依赖包括：

- `pyautogui`
- `Pillow`
- `aiohttp`
- `psutil`
- `numpy`
- `pyaudio`（启用麦克风监听时）
- `pygetwindow`（Windows 活动窗口支持）

## Docker 截图说明

- 普通桌面部署：保持 `use_shared_screenshot_dir = false`，插件会直接实时截图
- Docker 或无法直接截图的环境：开启 `use_shared_screenshot_dir`，并配置 `shared_screenshot_dir`
- 开启共享截图目录后，插件会优先读取目录中的最新截图；若当前实例也能截图，还会同步更新 `screenshot_<时间戳>.jpg` 和 `screenshot_latest.jpg`

## 常用指令

| 指令 | 说明 |
| --- | --- |
| `/kp` | 立即截图并分析当前屏幕 |
| `/kps` | 切换自动观察状态 |
| `/kpi start` | 启动自动观察任务 |
| `/kpi stop` | 停止自动观察任务 |
| `/kpi list` | 查看当前运行中的自动任务 |
| `/kpi y [序号] [间隔] [概率]` | 新增或修改自定义预设 |
| `/kpi ys [序号]` | 切换到指定预设 |
| `/kpi presets` | 查看全部预设 |
| `/kpi add [间隔] [提示词]` | 新增一个自定义观察任务 |
| `/kpi diary [YYYY-MM-DD]` | 查看指定日期日记 |
| `/kpi recent [天数]` | 查看最近几天日记 |
| `/kpi complete [YYYY-MM-DD]` | 补写指定日期日记 |
| `/kpi debug [on/off]` | 切换调试模式 |
| `/kpi webui [start/stop]` | 启动或停止 WebUI |

## WebUI

启动方式：

```text
/kpi webui start
```

默认访问地址：

```text
http://127.0.0.1:8898
```

当前 WebUI 支持：

- 运行状态查看和任务停止
- 配置中心分组编辑
- 今日日记与历史日记阅读
- 今日观察时间轴展示
- 观察记录筛选、分页、删除、批量删除
- 长期记忆浏览
- 服务自检与版本显示
- 当前窗口读取和窗口自动陪伴配置

## 2.5.0 更新摘要

- 新增窗口自动陪伴和窗口候选读取接口
- WebUI 配置中心支持快速加入窗口陪伴目标
- WebUI 端口增加非法值回退与重载重试
- 修复登录后偶发 `500`
- 修复静态资源 `404`
- 持续清理日志和文案乱码

## 外部图片分析 API

启用 WebUI 后，可选开放外部图片分析接口。

前提：

1. 启用 WebUI
2. 开启“允许外部 API 调用”
3. 设置 WebUI 密码

文件上传接口：

```http
POST /api/analyze
```

Base64 接口：

```http
POST /api/analyze/base64
```

## 配置建议

优先关注以下配置项：

- `enabled`
- `check_interval`
- `trigger_probability`
- `active_time_range`
- `rest_time_range`
- `vision_api_url`
- `vision_api_key`
- `vision_api_model`
- `enable_diary`
- `diary_time`
- `enable_learning`
- `custom_presets`
- `enable_window_companion`
- `window_companion_targets`
- `webui.enabled`
- `webui.port`
- `webui.auth_enabled`
- `webui.allow_external_api`

## 隐私与安全

该插件会读取屏幕内容，并可能将图片与文本发送给外部模型服务。请务必注意：

- 不要在未获授权的环境中使用
- 不要用于监控他人或侵犯隐私
- 谨慎配置外部 API 地址和密钥
- 如开放外部 API，请务必启用认证

## 开发维护

建议所有源码文件统一使用 `UTF-8` 编码。仓库已提供 `.editorconfig` 约束常见编辑器行为。

提交前可以运行：

```bash
python scripts/check_text_health.py --strict
```

这个脚本会检查：

- 非 `UTF-8` 编码文件
- 常见乱码片段
- 遗留的占位文本与可疑问号占位

## 后续优化方向

- 继续清理历史乱码与占位文案
- 进一步拆分 `main.py`
- 完善测试和异常自检
