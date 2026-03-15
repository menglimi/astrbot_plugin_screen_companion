# 我会一直看着你（`astrbot_plugin_screen_companion`）

面向 AstrBot 的屏幕伴侣插件。它会结合截图或录屏、多模态识别、环境感知、长期记忆、日记和 WebUI，为用户提供更自然的陪伴式互动。

## 主要功能

- 自动识屏：按设定间隔和触发概率分析当前屏幕内容。
- 识别素材开关：关闭时识别图片，开启时识别视频。
- 识别链路切换：支持“外部视觉 API 两步识别”和“直接发送给 AstrBot 的多模态识别”。
- 自然语言识屏求助：支持“帮我看看这个页面”“这题怎么做”等自然语言触发。
- 长期记忆与日记：记录观察、压缩记忆，并按天生成日记。
- WebUI 管理面板：查看运行状态、观察记录、活动统计、日记和配置。
- Docker / 共享目录适配：无法直接截图时可切换到共享截图目录模式。
- 窗口自动陪伴：命中特定窗口时自动触发陪伴与识屏。

## 运行环境

推荐在有图形界面的桌面环境中使用：

- Windows
- macOS
- Linux 图形桌面

额外要求：

- 截图模式需要桌面截图权限。
- 录屏模式目前主要面向 Windows，且需要可用的 `ffmpeg`。
- `ffmpeg` 是一个开源的多媒体处理工具，用于录制桌面视频。
- 如不下载 ffmpeg，则无法使用**录屏模式**（`screen_recognition_mode`），只能使用截图模式。

## ffmpeg 安装（录屏模式必需）

### Windows 快速配置（推荐）

1. 下载 ffmpeg：
   - 访问 https://www.gyan.dev/ffmpeg/builds/（推荐）
   - 下载 `ffmpeg-release-essentials.zip`

2. 解压下载的 ZIP 文件

3. 使用指令自动配置：
   ```
   /kpi ffmpeg [解压后的 ffmpeg.exe 路径]
   ```
   例如：`/kpi ffmpeg C:\Users\你的用户名\Downloads\ffmpeg\bin\ffmpeg.exe`
   
   插件会自动将 ffmpeg 复制到插件目录的 bin 文件夹。

### 手动配置

将 `ffmpeg.exe` 复制到以下位置之一：
- 插件目录：`astrbot_plugin_screen_companion/bin/ffmpeg.exe`
- 或配置 `ffmpeg_path` 为完整路径

### macOS 安装步骤

```bash
brew install ffmpeg
```

### Linux 安装步骤

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

- 如启用麦克风监听，需要对应麦克风权限。
- 如使用外部视觉 API，需要正确配置视觉模型地址、密钥和模型名。

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

## 如何从零放置 `ffmpeg.exe` 到 `bin/ffmpeg.exe`

如果你想直接使用插件内置查找路径，而不是自己配置系统 `PATH`，可以按下面的步骤处理：

1. 下载 Windows 版 ffmpeg 压缩包。
   - 可从 ffmpeg 官网跳转的 Windows 构建页下载。
   - 下载内容通常是一个 `.zip` 或 `.7z` 压缩包。
2. 解压压缩包。
3. 在解压后的目录中找到 `ffmpeg.exe`。
   - 常见位置类似：`解压目录\\bin\\ffmpeg.exe`
4. 进入本插件目录，在插件根目录下确认有一个 `bin` 文件夹。
   - 如果没有，就手动新建一个 `bin` 文件夹。
5. 把刚才找到的 `ffmpeg.exe` 复制到这个位置：

```text
插件目录\bin\ffmpeg.exe
```

例如，如果你的插件目录是：

```text
C:\Users\你的用户名\.astrbot\data\plugins\astrbot_plugin_screen_companion
```

那么最终文件应该放在：

```text
C:\Users\你的用户名\.astrbot\data\plugins\astrbot_plugin_screen_companion\bin\ffmpeg.exe
```

放好后的目录结构大致如下：

```text
astrbot_plugin_screen_companion/
├─ bin/
│  └─ ffmpeg.exe
├─ core/
├─ web/
├─ main.py
└─ README.md
```

完成后重启 AstrBot，再执行一次 `/kpr` 或切换到录屏模式即可。如果仍提示未找到 `ffmpeg`，请先确认：

- 文件名确实是 `ffmpeg.exe`
- 文件确实放在 `bin` 文件夹里，而不是压缩包的其他子目录里
- AstrBot 已经重启，拿到了最新文件
- 你下载的是 Windows 可执行文件，而不是源码包

## 依赖

常见依赖包括：

- `pyautogui`
- `Pillow`
- `aiohttp`
- `psutil`
- `numpy`
- `pyaudio`：仅在启用麦克风监听时需要
- `pygetwindow`：Windows 活动窗口识别时需要
- `ffmpeg`：录屏模式需要

## 识别素材开关

### `screen_recognition_mode = false`

- 使用当前截图作为识别素材。
- 适合普通桌面环境。
- 兼容性最好。

### `screen_recognition_mode = true`

- 本地通过 `ffmpeg` 录制最近一段桌面 mp4。
- 触发对话时停止当前录制，读取最近一段视频并重新开始下一轮录制。
- 适合需要让模型理解连续操作过程的场景。
- 默认录屏参数为 `1 fps`、`10 秒`，也可以通过 `recording_fps` 和 `recording_duration_seconds` 调整。

## 识别链路

### `use_external_vision = true`

两步识别链路：

1. 本地准备截图或录屏素材。
2. 发送给外部视觉 API 获取识别文本。
3. 再把识别文本和对话上下文交给 AstrBot 生成回复。

适合当前 AstrBot provider 多模态兼容性不稳定，或者希望单独使用视觉模型时。

### `use_external_vision = false`

直接多模态链路：

1. 本地准备截图或录屏素材。
2. 把图片或视频转成 base64。
3. 作为多模态消息直接发送给 AstrBot 当前 provider。

注意：

- 图片直发通常更稳。
- 视频直发依赖当前 provider 是否真正支持 `data:video/mp4;base64,...` 形式的输入。
- 如果当前聊天 provider 是官方 Gemini API，插件现在会优先改走 Gemini 原生多模态接口：
  - 图片走 `inline_data`
  - 视频优先走 Gemini `Files API`
- 如果当前 provider 只是 OpenAI 兼容网关上的 Gemini 模型，插件会回退到原有的兼容模式，不会强行调用 Google 的原生上传接口。
- 默认情况下，非 Gemini 原生链路上的视频直发会被安全拦截，以避免请求体过大和 token 消耗失控。
- 如果你确实要强制继续兼容视频直发，可以开启 `allow_unsafe_video_direct_fallback`，但风险需要自行承担。
- 为避免把整段视频 base64 直接塞进提示词导致请求体和 token 风险暴涨，视频直发现在默认只允许走 Gemini 原生上传；不满足条件时会直接中断并提醒切换方案。
- 如需强制启用官方 Gemini 原生链路，可通过环境变量提供：
  - `GEMINI_API_KEY`
  - `GEMINI_API_BASE`，默认是 `https://generativelanguage.googleapis.com`

## 常用指令

| 指令 | 说明 |
| --- | --- |
| `/kp` | 始终执行一次截图识别，不受全局录屏开关影响 |
| `/kpr` | 始终执行一次录屏识别，不受全局录屏开关影响 |
| `/kps` | 切换自动观察状态 |
| `/kpi start` | 启动自动观察任务 |
| `/kpi stop` | 停止自动观察任务 |
| `/kpi list` | 查看当前自动任务 |
| `/kpi presets` | 查看全部预设 |
| `/kpi webui` | 查看 WebUI 端口信息 |
| `/kpi webui start` | 启动 WebUI |
| `/kpi webui stop` | 停止 WebUI |
| `/kpi ffmpeg` | 查看当前 ffmpeg 状态 |
| `/kpi ffmpeg [路径]` | 设置 ffmpeg 路径并自动复制到插件目录 |

## 推荐关注的配置项

- `screen_recognition_mode`
- `ffmpeg_path`
- `recording_fps`
- `recording_duration_seconds`
- `use_external_vision`
- `allow_unsafe_video_direct_fallback`
- `vision_api_url`
- `vision_api_key`
- `vision_api_model`
- `use_shared_screenshot_dir`
- `shared_screenshot_dir`
- `save_local`
- `enable_natural_language_screen_assist`
- `enable_window_companion`
- `window_companion_targets`
- `check_interval`
- `trigger_probability`
- `active_time_range`
- `rest_time_range`

## 隐私与安全

该插件会读取屏幕内容，并可能把图片、视频或识别文本发送给外部模型服务。使用前请务必确认：

- 不要在未授权环境中使用。
- 不要用于监控他人或侵犯隐私。
- 谨慎配置外部视觉 API 地址和密钥。
- 如果开放 WebUI 外部 API，请务必启用认证。

## 开发建议

建议项目文件统一使用 `UTF-8` 编码。提交前可以运行：

```bash
python scripts/check_text_health.py --strict
```

## 2.6.0 更新摘要

- 识别素材能力完成升级：新增截图 / 录屏开关，录屏模式支持本地 `ffmpeg` 采集最近一段桌面视频，并可通过 `recording_fps` 与 `recording_duration_seconds` 调整帧率和时长，默认值为 `1 fps`、`10 秒`。
- 指令语义更加清晰：`/kp` 固定执行截图识别，`/kpr` 固定执行录屏识别，不再受全局识别素材开关影响；当当前处于截图模式时，`/kpr` 也会先临时录制一段桌面后再继续分析。
- 多模态链路更完整：`use_external_vision` 现在可在“外部视觉 API 两步识别”和“直接发送给 AstrBot 的多模态识别”之间切换；当当前 provider 是官方 Gemini API 时，图片会优先走 `inline_data`，视频会优先走 `Files API`。
- 视频直发安全策略增强：默认会拦截不支持原生视频上传的 provider，避免把整段视频 base64 直接塞进兼容消息导致请求体和 token 风险过大；如确有需要，可通过 `allow_unsafe_video_direct_fallback` 显式放开兼容回退。
- 录屏环境配置更灵活：支持通过 `ffmpeg_path` 指定本地 `ffmpeg.exe`，同时会优先查找插件目录下的 `bin/ffmpeg.exe`，最后再回退到系统 `PATH`。
- WebUI 能力继续扩展：运行状态页新增最新截图 / 最新录屏预览，并补充了识屏模式、识别链路和运行态说明，方便直接确认当前素材来源和多模态工作方式。
- 运行时稳定性得到修复：补充统一的运行时状态兜底初始化，降低插件热更新或旧实例复用时因新字段缺失导致的 `AttributeError` 风险。
