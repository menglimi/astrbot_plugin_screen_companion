# 我会一直看着你

astrbot_plugin_screen_companion 是面向 AstrBot 的屏幕伙伴插件。它能让bot随机地监视你的屏幕，并根据场景与用户进行互动。插件能监控音量、电脑状态以及你打开的窗口并进行合适的互动，且会根据每天的观察记录完成日记。此外，插件还拥有一个完善的webUI界面。灵感来源于妹居物语，适配live2D桌宠。

基本功能已经完善，现已转入维护阶段，如果喜欢的话请给个 star 吧。

## 搭配推荐

强烈推荐搭配使用 [`我会永远陪着你`](https://github.com/menglimi/astrbot_plugin_private_companion) 插件。它定位为“最强拟人化插件”，负责人格连续性、关系记忆、主动行为与长期陪伴编排；屏幕伙伴负责观察电脑状态、识屏、录屏和沉淀日记，两者一起用会更接近完整的桌面陪伴体验。

## 版本

当前版本：`3.1.1`
`3.1.1` 修复 AstrBot 插件拓展页内最新截图与录屏预览显示问题，并在文档中补充“我会永远陪着你”搭配推荐。

### 3.0.0 更新重点

`3.0.0` 主要整理了陪伴模式配置与连续性体验：将“陪伴 / 偷看”收敛为单一互动风格选项，补上短期对话记忆，弱化客观播报式开场，并重写了配置说明与选填提示。

### 2.9.0 更新重点

- 安装与运行更稳：麦克风依赖拆成可选安装项，避免 `pyaudio / portaudio.h` 阻塞基础功能；同时修复了 Windows 初装后 WebUI 运行状态接口的已知异常。
- 收尾语更贴场景：开启 `use_llm_for_start_end` 后，结束自动观察会参考最近识屏结果和插件回复，让收尾更像接着刚才的场景自然说话。
- 活动页重做为工作回顾视图：新增总览、工作回顾、工作脉搏、今日工作轨迹、近 7 天节奏和最近活动等结构，日内复盘路径更完整。
- 新增本地输入统计：支持记录键盘、点击、滚轮和鼠标移动，并在活动页显示输入在场感、活跃分钟和输入状态。
- 支持有效工作时长：启用本地输入统计后，长时间无键鼠输入的空闲会尽量从工作段、趋势和回顾里扣除，减少挂机时长误导。
- 新增离开自动挂起：非观影场景下，用户离开电脑一段时间后可自动暂时结束任务；回来继续操作时自动恢复，离开更久还可补一次轻量 LLM 回复。
- 新增应用 / 网站 / 页面级轨迹：活动历史会拆成应用名、站点名和页面标题，最近活动和工作段能更直接看出自己在什么工具、什么页面上花了时间。
- 新增自定义活动识别规则：支持按行配置应用 / 站点别名，把内网站点、公司文档、常用工具映射成更符合个人工作流的名称。
- 新增隐私友好的轨迹展示：活动页支持窗口标题统一脱敏，更适合长期挂着 WebUI 使用。
- WebUI 保存体验更稳：运行设置和配置中心会在保存时自动给出更明确的网络错误提示，并在 WebUI 短暂重连后主动尝试恢复状态。
- 轨迹回顾更好筛：活动页新增关键词、类型、来源筛选与统计说明，能更快聚焦某段工作轨迹，也更容易理解“有效工作”和“轨迹来源”的口径。
- 服务自检更具体：WebUI 会额外展示静态资源、目录、输入统计、独立轨迹采集、识别规则和窗口读取能力等详细检查项，排障路径更直接。
- 日记生成更可靠：待写日记条目会落盘保存，到点后即使错过设定分钟也会补写；观察偏少时也能生成简版日记。
- 日记支持窗口轨迹补料：素材不足时，会自动从当天窗口 / 应用 / 站点轨迹里抽几段代表性活动补进观察文本，自动日记和手动补写都适用。

## 主要功能

- 自动识屏：按间隔和概率观察当前屏幕，并在合适的时候主动回复。
- 即时识屏：`/kp` 固定截图识别，`/kpr` 固定录屏识别。
- 监控任务：监控音量/内存占用/电池电量，触发阈值可配置。
- 拟人化行为：根据用户互动和环境变化，调整回复内容和频率。
- 外部视觉链路：支持优先使用 AstrBot 模型提供商进行屏幕识别，也兼容旧版独立视觉 API。
- 录屏轻量采样：录屏模式会先抽取关键帧，必要时再回退到完整视频分析。
- 主动陪伴：支持变化感知、相似回复冷却、同窗口频率限制、手动发言后暂缓打断，以及敏感界面沉默、情绪短缓存和只观察不发言。
- 模式感知：看片时更偏陪伴，编程/办公时更偏助手，深度专注时进一步降低主动打断。
- 学习与纠偏：支持手动纠正、自然反馈学习、共同体验追问、误学回滚和学习开关矩阵。
- 任务收尾感：在工作场景明显告一段落时，更容易顺势补一句下一步引导。
- 开始/结束文案：支持固定文案或 LLM 生成；结束自动观察时会参考最近识屏上下文，让收尾更自然。
- 长期记忆：保留窗口、场景、情节记忆和重复关注点，后续回复会优先召回相关记忆。
- 今日日记：自动生成更自然的日记正文，并同步生成结构化摘要与观察时间线。
- WebUI：查看运行状态、观察记录、活动统计、记忆，以及按“正文 - 概览 - 观察”拆开展示的日记信息。
- 本地输入统计：可选记录全局键盘与鼠标输入，给活动统计页补上更像 KeyStats 的轻量数据。
- 工作轨迹回顾：把零散活动聚合成连续工作段，并结合输入在场感生成更像 Work_Review 的工作脉搏视图。
- 独立活动轨迹采集：可单独开启轻量窗口采样，即使不开自动观察，也能持续沉淀应用 / 网站 / 页面级轨迹。
- 轨迹识别规则：支持自定义应用 / 站点识别别名，让活动页更贴合自己的软件、内网站点和工作流命名。
- 应用 / 网站轨迹：在活动页按应用层和网页层聚合日内活动，更方便做工作回顾。
- 有效工作扣减：启用本地输入统计后，长时间空闲会尽量不计入有效工作段。
- 离开自动挂起：非观影场景下，如果较长时间没有键鼠输入，可自动暂停任务；检测到你回来继续操作后再自动恢复。
- 插件api：提供插件之间的通信接口，支持自定义插件功能。

## 运行环境

远程识屏易产生隐私问题，仅推荐在本地部署的情况下使用，推荐在带图形桌面的环境中运行：

- Windows
- macOS
- Linux 图形桌面

额外要求：

- 截图模式需要系统截图权限。
- 录屏模式需要可用的 `ffmpeg`。
- 如果启用麦克风监听，需要系统麦克风权限，并额外安装可选麦克风依赖。
- 如果启用本地输入统计，需要系统允许全局键盘 / 鼠标监听，并授予对应权限。
- 如果启用外部视觉链路，建议先选择支持多模态的 AstrBot 模型提供商。

## 安装

1. 将插件目录放入 AstrBot 插件目录，例如：

```text
C:\Users\你的用户名\.astrbot\data\plugins\astrbot_plugin_screen_companion
```

2. 安装基础依赖：

```bash
pip install -r requirements.txt
```

如果你是通过 AstrBot 面板上传 zip 安装插件，这一步通常会自动执行。

3. 如果你需要启用麦克风监听，再额外安装可选依赖：

```bash
pip install -r requirements-optional-mic.txt
```

Linux 上如果 `PyAudio` 安装失败，通常还需要先安装 `PortAudio` 开发包，例如：

```bash
# Ubuntu / Debian
sudo apt install portaudio19-dev

# CentOS / RHEL
sudo yum install portaudio-devel
```

4. 本地输入统计依赖已并入基础安装；如果你准备启用它，请确认系统已授予全局键盘 / 鼠标监听、辅助功能或无障碍权限。

5. 重启 AstrBot。

注意：插件目录名必须是 `astrbot_plugin_screen_companion`，不要带版本号后缀。

## Docker 部署适配

这个插件的核心能力依赖图形桌面环境，因此不建议指望容器直接截取宿主机桌面。对于 Docker 用户，推荐使用“宿主机截图 + 容器读取共享目录”的方式。

仓库内已经提供了一个独立的小工具：

```text
scripts/docker_screenshot_bridge.py
```

它需要运行在宿主机上，负责定时截图并写入共享目录；容器内的插件再从这个目录读取最新截图。

### 适用场景

- AstrBot 运行在 Docker 容器中
- 宿主机有图形桌面，可以正常截图
- 你只需要截图识别，不需要录屏模式

### 1. 宿主机运行截图桥接工具

先在宿主机安装依赖：

```bash
pip install Pillow pyautogui
```

然后运行：

```bash
python scripts/docker_screenshot_bridge.py --output-dir /path/to/screenshots --interval 5 --verbose
```

常用参数：

- `--output-dir`：共享截图目录，必填
- `--interval`：截图间隔秒数，默认 5
- `--quality`：JPEG 质量，默认 85
- `--history-limit`：最多保留多少张历史截图，默认 120
- `--once`：只截一张就退出，适合排查环境

工具会持续生成这两类文件：

- `screenshot_latest.jpg`
- `screenshot_时间戳.jpg`

如果你不想每次手敲命令，也可以直接用仓库内的启动脚本：

- Windows：`scripts/start_docker_screenshot_bridge_windows.bat`
- Linux：`scripts/start_docker_screenshot_bridge_linux.sh`

如果你想进一步做成自动启动，也可以直接使用安装脚本：

- Windows 计划任务：`deploy/docker/install_windows_task_scheduler.ps1`
- Linux 用户级 systemd：`deploy/docker/install_linux_systemd_user.sh`

### 2. 挂载共享目录到容器

例如 `docker-compose.yml`：

```yaml
services:
  astrbot:
    volumes:
      - ./screenshots:/data/screenshots
    ports:
      - "6314:6314"
```

仓库里也附带了示例文件，可直接改后使用：

- `deploy/docker/docker-compose.shared-screenshot.example.yml`

### 3. 插件内开启共享截图目录模式

请确认以下配置：

```json
{
  "enabled": true,
  "screen_recognition_mode": false,
  "use_shared_screenshot_dir": true,
  "shared_screenshot_dir": "/data/screenshots",
  "webui": {
    "enabled": true,
    "host": "0.0.0.0",
    "port": 6314,
    "auth_enabled": true,
    "password": "请改成你自己的密码"
  }
}
```

注意：

- `screen_recognition_mode` 必须为 `false`，也就是截图模式
- `use_shared_screenshot_dir` 必须为 `true`
- `shared_screenshot_dir` 填容器内路径，不是宿主机路径
- 如果开启 WebUI 并需要浏览器访问，请映射对应端口

### Linux 开机自启示例

如果你想让宿主机在 Linux 桌面环境下自动启动截图桥接工具，可以参考：

```text
deploy/docker/astrbot-screen-bridge.service
```

使用前需要至少修改两处：

- 把 `ExecStart` 改成你本机插件目录的绝对路径
- 把 `SCREENSHOT_OUTPUT_DIR` 改成你的共享截图目录

如果你的桌面会话不是 `DISPLAY=:0`，也要同步调整。

如果你更希望自动生成并启用用户级服务，也可以直接运行：

```bash
sh deploy/docker/install_linux_systemd_user.sh --output-dir /srv/astrbot/screenshots
```

启用后常用排查命令：

```bash
systemctl --user status astrbot-screen-bridge.service
journalctl --user -u astrbot-screen-bridge.service -f
```

### Windows 自动启动示例

在 Windows 宿主机上，可以用计划任务让桥接工具在登录后自动运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\docker\install_windows_task_scheduler.ps1 -OutputDir C:\astrbot\screenshots
```

安装完成后：

- 打开“任务计划程序”可以看到 `AstrBot Screen Bridge`
- 注销并重新登录后会自动启动
- 也可以在任务计划程序里手动点一次“运行”做测试

### 4. 启动后建议这样检查

1. 先在宿主机执行桥接工具，确认共享目录里已经持续生成截图
2. 再启动 AstrBot 容器
3. 使用 `/kp` 测试一次即时识屏
4. 使用 `/kpi status` 查看环境检查结果
5. 使用 `/kpi start` 启动自动观察

### Docker 场景限制

- 共享截图目录模式仅适用于截图模式，不适用于录屏模式
- 宿主机必须保持图形桌面会话可用
- Linux 宿主机通常需要在有 `DISPLAY` 或 `WAYLAND_DISPLAY` 的桌面会话中运行该工具
- 如果截图长期不更新，插件会认为截图已过期并尝试回退到实时截图

## ffmpeg 安装

录屏模式必须安装 `ffmpeg`用于后台录制屏幕处理视频。如果没有 `ffmpeg`，插件仍可使用截图模式，但无法使用 `/kpr` 和录屏识屏。

### Windows 快速配置

0. 尝试直接从插件的release页面下载Windows版本的 `ffmpeg.exe`。
1. 或者从 [Gyan FFmpeg Builds](https://www.gyan.dev/ffmpeg/builds/) 下载 `ffmpeg-release-essentials.zip`。
2. 解压后找到 `ffmpeg.exe`，通常位于 `bin\ffmpeg.exe`。
3. 在 AstrBot 中执行：

```text
/kpi ffmpeg C:\你的路径\ffmpeg\bin\ffmpeg.exe
```

插件会自动把 `ffmpeg.exe` 复制到插件数据目录的 `bin` 文件夹。
Windows 默认路径通常是 `C:\Users\你的用户名\.astrbot\data\plugin_data\astrbot_plugin_screen_companion\bin\ffmpeg.exe`。
注：为避免插件更新导致需要重新安装 `ffmpeg`，现已于2.7.1版本已将 `ffmpeg.exe` 从插件本体文件夹移动到插件数据目录的 `bin` 文件夹中，原位置依旧兼容。


### 手动配置

你也可以选择下面任意一种方式：

- 把 `ffmpeg.exe` 放到 `C:\Users\你的用户名\.astrbot\data\plugin_data\astrbot_plugin_screen_companion\bin\ffmpeg.exe`
- 在配置中填写完整的 `ffmpeg_path`
- 把 `ffmpeg` 加入系统 `PATH`

### macOS

```bash
brew install ffmpeg
```

### Linux

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# CentOS / RHEL
sudo yum install ffmpeg
```

## API 与识别链路

插件支持两种视觉识别方式。

### 外部视觉链路

默认建议优先配置 AstrBot 模型提供商：

- `vision_provider_id`
- `vision_provider_id_backup`（可选）

开启后，插件会优先把截图或采样后的录屏素材发送到选定的 AstrBot 视觉 provider；当返回结果不稳定或信息不足时，会按当前策略决定是否继续走完整视频复判。

兼容说明：

- 旧版 `vision_api_url` / `vision_api_key` / `vision_api_model` 配置仍可作为最终兜底。
- 新配置推荐优先使用 AstrBot provider，统一由 AstrBot 管理模型和鉴权。

### 直接使用 AstrBot 当前 Provider 的多模态能力

当 `use_external_vision = false` 时，插件会把素材直接发送给 AstrBot 当前对话使用的多模态模型。

补充说明：

- 如果当前 Provider 是官方 Gemini API，图片会优先走 `inline_data`，视频会优先走 `Files API`。
- 如果 Provider 不适合直接吃完整视频，插件会优先使用轻量采样结果，减少超时与失败概率。
- 建议根据模型能力和网络情况，在“视觉 provider 两段链路”与“直连多模态”之间选择更稳定的一条链路。

## 快速开始

1. 在配置里确认主动目标、识屏模式、模型和是否启用外部视觉链路。
2. 如需录屏模式，先执行 `/kpi ffmpeg` 或配置 `ffmpeg_path`。
3. 用 `/kp` 或 `/kpr` 做一次即时识屏，确认链路可用。
4. 用 `/kpi status` 查看当前运行状态与环境检查结果。
5. 用 `/kpi start` 启动自动观察。
6. 用 `/kpi learning` 查看学习开关和最近学习动态。
7. 打开 WebUI 查看观察、日记、活动统计和记忆是否正常积累。

## 指令总览

相同功能的旧别名已经不再作为主要入口保留，下面只列推荐使用的简化版指令。

**注意**：为保证您不会被自己的bot开盒，所有指令仅管理员可使用：

### 即时识屏

- `/kp`：立即截图识别（仅管理员）。
- `/kpr`：立即录屏识别（仅管理员）。
- `/kps`：切换自动观察运行状态（仅管理员）。

### 自动观察与状态

- `/kpi start`：启动自动观察（仅管理员）。
- `/kpi stop`：停止自动观察（仅管理员）。
- `/kpi status`：查看自检、运行状态、主动目标、识屏链路和环境检查（仅管理员）。
- `/kpi help`：查看常用命令和最短上手路径（仅管理员）。
- `/kpi list`：查看当前任务列表（仅管理员）。
- `/kpi webui`：查看 WebUI 状态和访问地址（仅管理员）。
- `/kpi webui start`：启动 WebUI（仅管理员）。
- `/kpi webui stop`：停止 WebUI（仅管理员）。

### 预设与日记

- `/kpi p`：查看预设列表（仅管理员）。
- `/kpi ys [序号]`：使用指定预设；不带参数时显示预设列表（仅管理员）。
- `/kpi y [内容]`：记录一条观察（仅管理员）。
- `/kpi add [名称] [间隔秒] [概率]`：新增预设（仅管理员）。
- `/kpi d [日期]`：查看指定日期日记；凌晨两点前默认查看前一天（仅管理员）。
- `/kpi cd [日期]`：补写指定日期日记；凌晨两点前默认补写前一天（仅管理员）。

### 配置与调试

- `/kpi ffmpeg`：查看当前 `ffmpeg` 状态（仅管理员）。
- `/kpi ffmpeg [路径]`：设置 `ffmpeg` 路径并复制到插件数据目录（仅管理员）。
- `/kpi recent`：查看最近观察（仅管理员）。
- `/kpi correct [内容]`：补充纠正信息（仅管理员）。
- `/kpi preference [类别] [内容]`：记录偏好（仅管理员）。
- `/kpi learning`：查看或调整学习开关，并查看最近学习原因（仅管理员）。
- `/kpi learning [manual|feedback|followup|preference] [on|off]`：单独开关某类学习（仅管理员）。
- `/kpi learned`：查看最近自动学习记录（仅管理员）。
- `/kpi unlearn [序号|all]`：删除指定误学记录或清空自动学习记录（仅管理员）。
- `/kpi debug [on|off]`：切换调试模式（仅管理员）。

## WebUI 能看什么

WebUI 当前适合做日常查看和排障：

- 运行状态：当前模式、任务、自检信息、最近主动消息和活动状态。
- 观察记录：识屏结果、触发原因、素材类型、识别摘要、最终回复。
- 今日日记：自然语言正文加结构化摘要。
- 活动统计：窗口活动时长、当前活动和持久化历史。
- 记忆：长期记忆、情节记忆、重复关注点。

默认地址通常是：

```text
http://127.0.0.1:6314
```

## 推荐关注的配置项

- `check_interval`
- `trigger_probability`
- `screen_recognition_mode`
- `ffmpeg_path`
- `recording_fps`
- `recording_duration_seconds`
- `use_external_vision`
- `vision_provider_id`
- `vision_provider_id_backup`
- `allow_unsafe_video_direct_fallback`
- `enable_mic_monitor`
- `use_llm_for_start_end`
- `end_llm_prompt`
- `webui.enabled`
- `webui.host`
- `webui.port`
- `webui.auth_enabled`
- `enable_manual_correction_learning`
- `enable_natural_feedback_learning`
- `enable_shared_activity_followup`
- `enable_shared_activity_preference_learning`

## 常见问题

### `/kpr` 提示找不到 `ffmpeg`

参考上述如何安装 ffmpeg。

### 上传安装插件时报 `pyaudio` 或 `portaudio.h`

这通常出现在 Linux / Docker 环境中，旧版本会因为麦克风依赖构建失败而导致整个插件安装失败。

- 如果你不需要麦克风监听，直接升级到 `2.9.1` 后重新上传插件即可。
- 如果你需要麦克风监听，请在基础安装完成后再额外执行：`pip install -r requirements-optional-mic.txt`
- Linux 上如果 `PyAudio` 继续报错，通常还需要先安装 `PortAudio` 开发包，例如 `sudo apt install portaudio19-dev`

### 识屏分析失败

请检查您的模型是否属于多模态模型且是否支持视频或多模态图片输入。注意，deepseek不是多模态模型，无法使用视觉分析功能。

### 录屏模式容易超时

建议优先：

- 降低 `recording_duration_seconds`
- 降低 `recording_fps`
- 关闭不必要的外部视觉链路
- 使用支持视频或多模态图片输入的模型

当前版本已经加入轻量采样，会优先抽关键帧降低超时概率。

### WebUI 刷新时报 `name 'shutil' is not defined`

这是旧版本运行状态接口里的已知问题，`2.9.1` 已包含这项修复。

- 请确认插件实际更新到了 `2.9.1`
- 更新后重启 AstrBot，再重新打开 WebUI
- 如果日志里仍然是同样的旧报错，通常说明插件目录没有被新版本完全覆盖

### 结束自动观察的回复不够贴场景

如果你希望结束语像“下次也一起看电影哦”或“代码出问题再叫我”这种更贴当前场景的收尾：

- 开启 `use_llm_for_start_end`
- 根据角色风格调整 `end_llm_prompt`
- 先让插件产生几条有效识屏记录；当前版本里的 LLM 结束文案会参考最近几条识屏结果与插件回复来收尾

## 隐私与安全

- 截图、录屏、观察和记忆都可能包含你的屏幕内容，请只在信任的环境中使用。
- 如果仍在使用旧版独立视觉 API 配置，请妥善保管密钥。
- 如果 WebUI 对外开放，请务必启用认证。
- 确保 WebUI 访问密码安全，避免被他人获取。
- 不要在公共网络上开启 WebUI，避免被他人访问。
- 请合法使用，不要用于任何违法或不道德的目的。任何由于使用插件而导致的问题，插件作者不承担任何责任。

## 许可证

本项目采用 `GNU Affero General Public License v3.0`，即 `AGPL-3.0-or-later`。

- 完整许可证文本见仓库根目录的 `LICENSE`
- 简要版权声明见 `NOTICE`
- 如果你修改后通过网络服务方式向其他用户提供本项目，也需要按 AGPL 的要求向这些用户提供对应源码

## 外部系统调用 API

允许外部系统通过 API 调用来分析图片。

### 启用方式

1. 开启 WebUI
2. 在 WebUI 设置中启用"允许外部 API 访问"
3. 配置 WebUI 访问密码（用于 API 认证）

### API 端点

#### 1. 文件上传方式

```
POST {webui_url}/api/analyze
```

参数（multipart/form-data）：
- `image`：图片文件（必填）
- `prompt`：自定义提示词（可选）
- `webhook`：回调地址，分析完成后异步推送结果（可选）

#### 2. Base64 方式

```
POST {webui_url}/api/analyze/base64
```

请求体（JSON）：
```json
{
  "image": "data:image/jpeg;base64,xxxxx",
  "prompt": "自定义提示词",
  "webhook": "https://your-callback-url.com"
}
```

### 认证方式

在请求头中添加 `X-API-Key`：
```
X-API-Key: 你的WebUI密码
```

### 示例

```bash
# 使用 curl 调用
curl -X POST http://localhost:6314/api/analyze/base64 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_password" \
  -d '{"image": "data:image/jpeg;base64,..."}'

# 或者使用文件上传
curl -X POST http://localhost:6314/api/analyze \
  -H "X-API-Key: your_password" \
  -F "image=@screenshot.jpg"
```

### 注意事项

- 调用此 API 需要先配置 `vision_provider_id`，或保留旧版 `vision_api_url` 兼容配置，因为图片分析依赖视觉识别链路
- 如果未设置 WebUI 密码，则无需认证（不推荐）
- deepseek不是多模态模型，无法使用视觉分析功能。

### 开发信息

- 开发者：menglimi（烛雨）
- qq：995051631    纯代码小白，出问题建议先问问豆包或deepseek，欢迎提交 issue 或 pull request，有好的建议或改进可以分享。
- 看到这里了，就祝您拉史顺畅，永不便秘，永不报错。
- 给个star吧，谢谢。
