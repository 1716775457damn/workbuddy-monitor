# WorkBuddy Monitor

监控 [WorkBuddy](https://www.workbuddy.ai) 模型用量限流状态，自动管理待办任务队列 —— 限流时排队，额度恢复后自动发送，并提供图形界面管理一切。

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightblue)

## ✨ 功能

- 🔍 **限流消息解析** — 粘贴/剪贴板读取 WorkBuddy 限流提示，自动提取模型名与重置时间
- 📝 **任务队列** — 限流期间把任务加入队列，状态实时可见（等待中 / 已发送）
- ⏰ **自动发送** — 后台监控线程到点自动处理队列，弹窗提醒
- 🖥 **图形界面** — Tkinter GUI，双击编辑、按钮自适应布局、模型下拉记忆
- 💰 **余额查询（可选）** — 配置 API 后可查余额/用量
- 🚀 **一键启动** — VBS 启动器同时拉起 WorkBuddy 与监控，无终端黑窗

## 🚀 快速开始

### 环境要求

- Windows 10/11
- Python 3.8+（含 tkinter，官方安装包默认带）

### 安装

```powershell
git clone https://github.com/1716775457damn/workbuddy-monitor.git
cd workbuddy-monitor
```

### 运行

```powershell
# 图形界面（推荐）
pythonw workbuddy_gui.py

# 命令行模式
python workbuddy_monitor.py --add "写周报" --model "Hy4 preview"
python workbuddy_monitor.py --list
python workbuddy_monitor.py --once   # 单次检查
```

### 随 WorkBuddy 一起启动

编辑 `launch_workbuddy.vbs`，把其中两处路径改成你机器上的实际路径（WorkBuddy 安装路径、本仓库路径），然后双击运行，或为其创建快捷方式。

## 🖼 界面预览

- 限流状态区：显示被限流模型、重置时间、剩余倒计时
- 任务列表：模型 / 内容 / 创建时间 / 状态，双击编辑
- 监控控制：启动 / 停止后台监控、余额查询

## 📖 工作原理

1. 从剪贴板或文件读取限流消息，如：

   > 当前您在Hy4 preview模型的使用量已超出频率限制，可在2026-09-09 19:30:24 重置可用。

2. 正则解析出模型 `Hy4 preview` 和重置时间 `19:30:24`，写入本地状态
3. 后台线程每 30 秒轮询，到点把该模型的 `pending` 任务标记为已发送并提醒
4. 所有数据存在本地 `state.json`，不会上传任何服务器

## ⚙️ 配置（config.json，首次运行自动生成）

```json
{
  "watch_file": "clipboard",
  "send_mode": "notify",
  "send_command": "",
  "api": {
    "url": "",
    "headers": {},
    "balance_field": "balance",
    "usage_field": "usage"
  },
  "poll_interval": 30,
  "notify_title": "WorkBuddy 监控"
}
```

| 字段 | 说明 |
|---|---|
| `watch_file` | 监控源：`clipboard` 或文件路径 |
| `send_mode` | 发送方式：`notify`（弹窗）/ `command`（执行命令）/ `api`（POST） |
| `send_command` | `send_mode=command` 时执行，`{task}` 占位符 |
| `api.url` | 余额查询接口（GET） |
| `poll_interval` | 轮询间隔秒数 |

## 📁 文件结构

```
├── workbuddy_monitor.py   # 核心逻辑（解析/队列/监控/CLI）
├── workbuddy_gui.py       # Tkinter 图形界面
├── launch_workbuddy.vbs   # 一键启动器（WorkBuddy + GUI）
└── README.md
```

运行时自动生成（已 gitignore）：`config.json`、`state.json`、`monitor.log`

## 🤝 贡献

欢迎 PR！无论是 bug 修复、新功能还是文档改进。

## 📄 License

[MIT](LICENSE)
