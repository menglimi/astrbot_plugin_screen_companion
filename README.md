# 我会一直看着你（`astrbot_plugin_screen_companion`）

面向 AstrBot 的屏幕伴侣插件。它会结合截图分析、环境感知、长期记忆、日记记录和 WebUI，为用户提供更自然、更有价值的陪伴式互动体验。

## 主要功能

- **自动截图观察**：按设定间隔和触发概率分析当前屏幕
- **观察去重和低价值过滤**：减少流水账和噪音记忆
- **自然语言识屏求助**：支持"帮我看看这题/这局/这个页面"等自然语言请求
- **长期记忆和日记系统**：支持持续积累、压缩和按天回顾
- **WebUI 管理面板**：支持查看运行状态、日记、观察记录、长期记忆和配置
- **Docker 共享截图目录适配**：默认关闭，普通桌面环境优先实时截图
- **窗口自动陪伴**：可指定窗口关键字，窗口出现时自动把 Bot 叫来，关闭时自动退出
- **观察模式**：支持"偷看"和"陪伴"两种模式，陪伴模式提供更沉浸式的体验
- **工作/娱乐时间统计**：记录用户工作和娱乐的时间分布
- **活动统计**：WebUI 新增活动统计功能，展示用户的屏幕活动情况

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

## 观察模式

### 偷看模式
- 系统默认模式
- 适用于偶尔观察用户屏幕的场景
- 提供简洁、客观的屏幕分析

### 陪伴模式
- 更注重对话的连续性和陪伴的沉浸感
- 为特定窗口提供专属陪伴
- 提供更贴心的建议和鼓励
- 营造沉浸式的陪伴体验

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
| `/kpi webui` | 查看 WebUI 端口信息 |

## 外部 API 调用

插件提供了外部 API 接口，允许其他应用程序调用屏幕分析功能。

### 前提条件

1. 启用 WebUI
2. 开启"允许外部 API 调用"
3. 设置 WebUI 密码

### API 接口

#### 文件上传接口

```http
POST /api/analyze
```

**请求参数**：
- `file`：要分析的图片文件
- `prompt`：可选，自定义提示词
- `scene`：可选，指定场景类型

**响应**：
- `success`：布尔值，表示请求是否成功
- `result`：分析结果
- `error`：错误信息（如果失败）

#### Base64 接口

```http
POST /api/analyze/base64
```

**请求参数**：
- `image`：Base64 编码的图片数据
- `prompt`：可选，自定义提示词
- `scene`：可选，指定场景类型

**响应**：
- `success`：布尔值，表示请求是否成功
- `result`：分析结果
- `error`：错误信息（如果失败）

#### 活动统计接口

```http
GET /api/activity
```

**响应**：
- `success`：布尔值，表示请求是否成功
- `data`：活动统计数据
  - `work_time`：工作时间（分钟）
  - `play_time`：娱乐时间（分钟）
  - `total_time`：总时间（分钟）
  - `activities`：活动详情列表
- `error`：错误信息（如果失败）

### 认证

所有 API 调用都需要在请求头中包含认证信息：

```http
Authorization: Bearer <token>
```

其中 `<token>` 是通过登录接口获取的认证令牌。

### 登录接口

```http
POST /api/auth/login
```

**请求参数**：
- `username`：用户名（固定为 `admin`）
- `password`：WebUI 密码

**响应**：
- `success`：布尔值，表示登录是否成功
- `token`：认证令牌（如果成功）
- `error`：错误信息（如果失败）

## 2.5.2 更新摘要

- **新增错误纠正和记忆**：实现了错误纠正和持续性记忆功能，使 Bot 能够从用户的纠正中学习
- **新增自我形象识别**：实现了自我形象识别和记忆，使 Bot 能够认出屏幕中的自己
- **新增 webui 命令**：实现了 `webui` 命令来返回端口信息
- **修复 WebUI 错误**：修复了 "TCPSite.__init__() got an unexpected keyword argument 'sock'" 错误
- **修复编码错误**：修复了 "charset must not be in content_type argument" 和 "json_response() got an unexpected keyword argument 'charset'" 错误
- **优化提示词系统**：优化了 `_build_vision_prompt` 方法，按重要性排序组织提示词，以降低 LLM 反应时间
- **更新默认端口**：将默认端口从 8898 更新到 6314
- **优化端口管理**：减少了自动切换端口的次数从 10 到 3

## 2.5.1 更新摘要

- **修复窗口变化检测**：解决 `window_change_cooldown` 属性缺失导致的任务异常
- **优化观察模式**：新增"陪伴"模式，提供更沉浸式的体验
- **改进提示词系统**：优化 LLM 提示词顺序，提高回复速度和对话连贯性
- **删除突兀语气词**：移除影响体验的情感词汇，提升对话流畅度
- **扩展场景识别**：增加对英雄联盟等游戏的识别
- **修复长期记忆**：解决将"未知"当做记忆因素的问题
- **增加活动统计**：WebUI 新增活动统计功能，展示用户屏幕活动情况
- **优化端口管理**：实现端口复用，解决插件重启时的端口占用问题
- **改进自然语言识别**：更好地识别用户的自然语言请求
- **修复中文编码**：解决 WebUI 中的中文乱码问题
- **增加窗口变化检测**：监听用户打开新界面的行为，新窗口持续存在3分钟才记录
- **记录工作/娱乐时间**：根据场景类型统计用户的工作和娱乐时间

## 提示词系统

插件采用两阶段提示词系统：

1. **第一阶段**：视觉分析提示词，用于分析屏幕截图内容
2. **第二阶段**：互动提示词，与识屏结果一起发送给 LLM，生成自然的人格化回复

详细的提示词配置和说明请参考 `llm_prompts.md` 文件。

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
- `bot_appearance`（Bot 外形描述，用于识别屏幕中的自己）
- `companion_prompt`（陪伴模式系统提示词）

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

## 开发者信息

开发者：menglimi（烛雨）
qq：995051631
写点什么：什么什么什么
喜欢的话可以给我点个小星星,有好的建议可以告诉我
