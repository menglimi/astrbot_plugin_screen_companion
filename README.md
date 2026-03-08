# 我会一直看着你（`astrbot_plugin_screen_companion`）

一个面向 AstrBot 的屏幕伴侣插件。它会结合截图分析、环境感知、日记记录、长期记忆与主动互动，形成一种“陪伴式观察”的使用体验。

当前仓库已包含一版增强后的 WebUI：

- 更完整的仪表盘式界面
- 今日日记、观察记录、长期记忆的可视化浏览
- 运行状态面板
- 关键运行参数的 Web 端快速调整
- 自动任务停止控制
- 外部图片分析 API

## 功能概览

- 自动截图观察：按设定的时间间隔与触发概率分析当前屏幕
- 观察去重与低价值过滤：自动跳过过短、过泛、重复度很高的观察结果
- 视觉理解与互动：结合视觉模型识别屏幕内容并生成回复
- 拟人化互动优化：提示词会优先关注具体细节、延续上下文、减少机械播报感
- 场景化互动：会根据编程、设计、办公、阅读、视频、游戏等场景调整说话方式
- 主动陪伴：支持自动观察、手动触发、自定义任务
- 长期记忆：记录高频应用、场景、用户偏好与关联关系
- 长期记忆压缩：自动清理噪音标签，并对低价值尾部记忆做限量保留
- 日记系统：按固定时间生成每日总结，也支持查看与补写
- 日记格式清洗：自动去除模型误带的重复标题、日期与分节标题
- 环境感知：可结合天气、系统状态、节假日等信息
- 麦克风监听：当环境音量超过阈值时触发观察
- 外部 API：允许其他系统直接调用图片分析接口
- WebUI：查看数据、查看运行状态、调整部分运行参数

## 运行环境

推荐在本地桌面环境使用：

- Windows
- macOS
- 带图形界面的 Linux

需要具备以下前提：

- 可访问屏幕截图
- 如启用麦克风监听，需要麦克风权限
- 已正确配置视觉模型相关参数

## 安装方法

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

## 依赖说明

常见依赖包括：

- `pyautogui`
- `Pillow`
- `aiohttp`
- `psutil`
- `numpy`
- `pyaudio`（启用麦克风监听时）
- `pygetwindow`（Windows 活动窗口支持）

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

## WebUI 说明

启动方式：

```text
/kpi webui start
```

默认访问地址：

```text
http://127.0.0.1:8898
```

新版 WebUI 提供以下区域：

- 运行状态：查看当前是否启用、是否运行、自动任务数、当前预设和核心参数
- 配置中心：按分组编辑人格提示词、识屏参数、日记设置、外部视觉接口和 WebUI 配置
- 快速设置：调整启用状态、手动间隔、触发概率、互动频率、日记开关、学习开关、调试开关
- 今日日记：查看今天或历史日期的日记，并将“今日感想”与“今日观察”拆开展示
- 今日观察时间轴：如果日记里的观察段落采用 `### 时间 - 窗口` 结构，WebUI 会自动渲染成时间轴卡片
- 观察记录：按时间顺序浏览最近观察结果，支持场景筛选、分页、单条删除和批量删除
- 长期记忆：查看高频应用、场景、偏好和记忆关联

## 2.4.0 更新摘要

- 互动提示词全面调整，减少“播报式”说话方式，提升自然感、真实感和上下文连续性
- 新增按场景调整语气的能力，面对编程、阅读、视频、办公等场景时会给出更贴场的回应
- `今日感想` 生成逻辑改为优先提炼代表性观察，而不是简单重复当日记录
- WebUI 中的 `今日观察` 支持时间轴卡片化展示，长内容更容易浏览
- 版本信息已统一更新为 `2.4.0`

### WebUI 当前支持的运行控制

- 修改 `enabled`
- 修改 `check_interval`
- 修改 `trigger_probability`
- 修改 `interaction_frequency`
- 修改 `enable_diary`
- 修改 `enable_learning`
- 修改 `enable_mic_monitor`
- 修改 `debug`
- 切换 `current_preset_index`
- 停止当前自动观察任务

说明：

- WebUI 当前更适合做“运行态调整”和“状态可视化”
- 自动任务的“启动”仍建议通过聊天指令触发，因为任务本身依赖消息事件上下文

## 外部图片分析 API

在启用 WebUI 后，可开放外部图片分析接口。

前提：

1. 在配置中启用 WebUI
2. 开启“允许外部 API 调用”
3. 设置 WebUI 密码

### 文件上传接口

```http
POST /api/analyze
```

表单字段：

- `image`: 图片文件，必填
- `prompt`: 自定义提示词，可选
- `webhook`: 回调地址，可选

示例：

```bash
curl -X POST "http://localhost:8898/api/analyze" \
  -F "image=@screenshot.jpg" \
  -H "X-API-Key: your_password"
```

### Base64 接口

```http
POST /api/analyze/base64
```

示例请求体：

```json
{
  "image": "data:image/jpeg;base64,...",
  "prompt": "请分析这张图",
  "webhook": "https://example.com/callback"
}
```

示例：

```bash
curl -X POST "http://localhost:8898/api/analyze/base64" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_password" \
  -d "{\"image\":\"data:image/jpeg;base64,...\"}"
```

## 配置建议

建议重点关注以下配置项：

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
- `webui.enabled`
- `webui.port`
- `webui.auth_enabled`
- `webui.allow_external_api`

## 隐私与安全

这个插件会读取屏幕内容，并可能将图像与文本发送给外部模型服务。请务必注意：

- 不要在未经授权的环境中使用
- 不要用于监控他人或侵犯隐私
- 谨慎配置外部 API 地址与密钥
- 如果开放外部 API，请务必启用认证
- 建议为敏感工作环境设置合理的活跃时间段与休息时间段

## 当前已知优化方向

- 增加观察记录删除与批量管理
- 增加日记 Markdown 渲染和导出
- 增强运行状态面板的信息密度
- 进一步拆分 `main.py`，降低维护成本
- 清理更多历史文本编码问题

## 开发说明

如果你准备继续迭代这个插件，建议优先从下面三项开始：

1. 补充运行状态与控制接口
2. 优化观察记录与日记阅读体验
3. 拆分大文件并补基础测试

## 许可证与使用提醒

请仅在合法、合规、明确知情的前提下使用本插件。
