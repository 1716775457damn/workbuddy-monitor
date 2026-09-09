#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 用量/余额监控 + 任务队列自动发送程序
================================================
功能：
1. 监测 WorkBuddy 限流消息，自动解析模型名称和重置时间
   （示例："当前您在Hy4 preview模型的使用量已超出频率限制，可在2026-09-09 19:30:24 重置可用。
            您可切换其他模型或消耗积分继续使用该模型"）
2. 任务列表：限流期间提交的任务进入队列，等待余额/额度恢复
3. 到达重置时间后自动执行（发送）队列中的任务
4. 可选：通过 HTTP API 查询余额/用量（在 config.json 中配置）

用法：
    python workbuddy_monitor.py            # 前台运行
    python workbuddy_monitor.py --once     # 单次检查后退出（供计划任务调用）
    python workbuddy_monitor.py --add "任务内容" --model "Hy4 preview"
    python workbuddy_monitor.py --list     # 查看任务队列
    python workbuddy_monitor.py --status   # 查看限流状态
"""

import argparse
import sys as _sys
if _sys.stdout and hasattr(_sys.stdout, 'reconfigure'):
    _sys.stdout.reconfigure(encoding='utf-8')
    _sys.stderr.reconfigure(encoding='utf-8')
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "monitor.log"

DEFAULT_CONFIG = {
    # 限流检测：要监控的消息来源（文件路径或 "clipboard"）
    "watch_file": "",
    # 自动发送方式: "notify"  = Windows 通知提醒
    #              "command" = 执行 config.send_command（占位符 {task}）
    #              "api"     = POST 到 config.api.url
    "send_mode": "notify",
    "send_command": "",
    # 可选的余额/用量查询 API
    "api": {
        "url": "",
        "headers": {},
        "balance_field": "balance",   # JSON 响应中表示余额的字段
        "usage_field": "usage",       # JSON 响应中表示用量的字段
    },
    # 轮询间隔（秒）
    "poll_interval": 30,
    # Windows 通知标题
    "notify_title": "WorkBuddy 监控",
    # 到点自动发送到 WorkBuddy 窗口（复制到剪贴板 + 粘贴 + 回车）
    "auto_send": {
        "enabled": True,
        "window_title": "WorkBuddy",
        "free_only": True,  # 只在限流重置后(免费额度)自动发送，绝不走积分通道
    },
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = DEFAULT_CONFIG.copy()
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    # 补齐缺失键
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"tasks": [], "rate_limits": {}}


def save_state(state: dict):
    """原子写入：先写临时文件再替换，防止写到一半崩溃损坏 state.json"""
    import os
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 限流消息解析
# ---------------------------------------------------------------------------
# 匹配 "Hy4 preview模型" / "Hy4 preview 模型"
MODEL_RE = re.compile(r"您在\s*(.+?)\s*模型的使用量已超出频率限制")
# 匹配 "可在2026-09-09 19:30:24 重置可用" 或 "可在2026-09-09 19:30:24 重置"
TIME_RE = re.compile(r"可在\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*重置")
# 备用：只要时间
TIME_RE2 = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")


def parse_rate_limit_message(text: str):
    """解析限流消息，返回 (model, reset_time: datetime|None, ok)"""
    model = None
    reset = None
    m = MODEL_RE.search(text)
    if m:
        model = m.group(1).strip()
    t = TIME_RE.search(text)
    if t:
        reset = datetime.strptime(t.group(1), "%Y-%m-%d %H:%M:%S")
    else:
        t2 = TIME_RE2.search(text)
        if t2:
            reset = datetime.strptime(t2.group(1), "%Y-%m-%d %H:%M:%S")
    return model, reset, (model is not None or reset is not None)

# ---------------------------------------------------------------------------
# 任务队列
# ---------------------------------------------------------------------------
def add_task(state: dict, content: str, model: str = ""):
    task = {
        "id": int(time.time() * 1000),
        "content": content,
        "model": model,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",  # pending / sent
    }
    state["tasks"].append(task)
    save_state(state)
    log(f"已添加任务 #{task['id']}: {content[:50]}")
    return task


def pending_tasks(state: dict, model: str = ""):
    return [t for t in state["tasks"]
            if t["status"] == "pending" and (not model or t.get("model") == model)]

# ---------------------------------------------------------------------------
# 发送
# ---------------------------------------------------------------------------
def send_windows_notification(title: str, body: str):
    try:
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$n = New-Object System.Windows.Forms.NotifyIcon; "
            "$n.Icon = [System.Drawing.SystemIcons]::Information; "
            "$n.Visible = $true; "
            f"$n.ShowBalloonTip(5000, '{title}', '{body}', "
            "[System.Windows.Forms.ToolTipIcon]::Info)"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=15,
        )
    except Exception as e:
        log(f"通知发送失败: {e}")


# ---------------------------------------------------------------------------
# 自动发送：剪贴板 + 激活 WorkBuddy 窗口 + Ctrl+V + Enter（纯 ctypes，无第三方依赖）
# ---------------------------------------------------------------------------
import ctypes
import ctypes.wintypes as _wt

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
# 64 位下必须声明正确的返回/参数类型，否则句柄被截断导致写入违规
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
user32.SetClipboardData.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)


def set_clipboard_text(text: str) -> bool:
    """把文本写入系统剪贴板（CF_UNICODETEXT）"""
    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = kernel32.GlobalAlloc(0x2000, len(data))  # GMEM_MOVEABLE
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(13, h):  # CF_UNICODETEXT
            return False
        return True
    finally:
        user32.CloseClipboard()


def _find_window_by_title(substr: str):
    """枚举顶层窗口，返回标题包含 substr 的第一个可见窗口句柄"""
    result = []
    @ctypes.WINFUNCTYPE(_wt.BOOL, _wt.HWND, _wt.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if substr.lower() in buf.value.lower():
                result.append(hwnd)
        return True
    user32.EnumWindows(cb, 0)
    return result[0] if result else None


def _activate_window(hwnd) -> bool:
    """还原并前置窗口"""
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return bool(user32.GetForegroundWindow() == hwnd)


def _key(vk, up=False):
    user32.keybd_event(vk, 0, 2 if up else 0, 0)


def _ctrl_v():
    _key(0x11); _key(0x56)
    _key(0x56, True); _key(0x11, True)


def _enter():
    _key(0x0D)
    _key(0x0D, True)


def _get_clipboard_text() -> str:
    """读取当前剪贴板文本（用于发送后还原）"""
    if not user32.OpenClipboard(0):
        return ""
    try:
        h = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not h:
            return ""
        return ctypes.c_wchar_p(h).value or ""
    finally:
        user32.CloseClipboard()


def auto_send_to_workbuddy(content: str, window_title: str = "WorkBuddy") -> tuple:
    """复制到剪贴板 → 激活 WorkBuddy → 粘贴 → 回车发送。
    返回 (ok, message)。免费额度保护：本函数只在限流重置后被调用，
    且绝不会点击 WorkBuddy 中任何「消耗积分」确认弹窗。"""
    prev_clip = _get_clipboard_text()
    if not set_clipboard_text(content):
        return False, "写入剪贴板失败"
    hwnd = _find_window_by_title(window_title)
    if not hwnd:
        return False, f"未找到标题含「{window_title}」的窗口"
    if not _activate_window(hwnd):
        return False, "无法激活 WorkBuddy 窗口"
    time.sleep(0.5)
    # 发送前二次确认前台就是目标窗口，防止把内容打进无关应用
    if user32.GetForegroundWindow() != hwnd:
        return False, "前台窗口校验失败，取消发送"
    _ctrl_v()
    time.sleep(1.0)  # 等输入框渲染完粘贴内容
    _enter()
    time.sleep(0.3)
    # 还原用户剪贴板
    if prev_clip:
        set_clipboard_text(prev_clip)
    return True, "已自动粘贴并发送到 WorkBuddy"


def send_task(task: dict, cfg: dict):
    mode = cfg.get("send_mode", "notify")
    log(f"发送任务 #{task['id']}: {task['content'][:50]} (mode={mode})")
    if mode == "command":
        cmd = cfg.get("send_command", "")
        if cmd:
            cmd = cmd.replace("{task}", task["content"])
            subprocess.run(cmd, shell=True, capture_output=True, timeout=60)
    elif mode == "api":
        import urllib.request
        api = cfg.get("api", {})
        if api.get("url"):
            data = json.dumps({"task": task["content"], "model": task.get("model", "")}).encode("utf-8")
            req = urllib.request.Request(api["url"], data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            for k, v in api.get("headers", {}).items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=30) as resp:
                log(f"API 响应: {resp.status}")
    else:
        auto = cfg.get("auto_send", {})
        if auto.get("enabled") and auto.get("free_only", True):
            ok, msg = auto_send_to_workbuddy(task["content"],
                                             auto.get("window_title", "WorkBuddy"))
            log(f"自动发送结果: {msg}")
            if not ok:
                # 发送失败：保持 pending 状态，下轮重试；通知用户手动兜底
                send_windows_notification(cfg.get("notify_title", "WorkBuddy 监控"),
                                          f"自动发送失败({msg})，内容已在剪贴板，请手动粘贴。任务保留在队列中将重试: {task['content'][:50]}")
                return
        else:
            send_windows_notification(cfg.get("notify_title", "WorkBuddy 监控"),
                                      f"任务已恢复可发送：{task['content'][:80]}")
    task["status"] = "sent"
    # 重新读盘合并写回，减少与 UI/其他进程的丢更新窗口
    state = load_state()
    for t in state.get("tasks", []):
        if t["id"] == task["id"]:
            t["status"] = "sent"
            break
    save_state(state)
    log(f"任务 #{task['id']} 已发送")

# ---------------------------------------------------------------------------
# 监控主循环
# ---------------------------------------------------------------------------
def check_rate_limits(state: dict, cfg: dict):
    """从监控源读取新消息，更新 state['rate_limits']"""
    src = cfg.get("watch_file", "")
    text = ""
    if src == "clipboard":
        try:
            ps = "Get-Clipboard -Raw"
            r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               capture_output=True, text=True, timeout=10,
                               encoding="utf-8")
            text = r.stdout or ""
        except Exception:
            return
    elif src and Path(src).exists():
        text = Path(src).read_text(encoding="utf-8", errors="ignore")
    else:
        return

    model, reset, ok = parse_rate_limit_message(text)
    if ok:
        # 陈旧记录防护：重置时间已过去超过 24 小时的消息是历史残留，
        # 不写入限流记录，避免旧剪贴板内容触发"立即自动发送"
        if reset and (datetime.now() - reset).total_seconds() > 86400:
            log(f"忽略陈旧限流消息（重置时间 {reset} 已超过 24 小时）")
            return
        key = model or "default"
        entry = state["rate_limits"].setdefault(key, {})
        entry["model"] = model or key
        if reset:
            entry["reset"] = reset.strftime("%Y-%m-%d %H:%M:%S")
        entry["raw"] = text.strip()[:300]
        save_state(state)
        log(f"检测到限流: model={model} reset={reset}")


def balance_check(cfg: dict):
    """查询可选的余额 API，返回 (balance, usage) 或 (None, None)"""
    api = cfg.get("api", {})
    if not api.get("url"):
        return None, None
    try:
        import urllib.request
        req = urllib.request.Request(api["url"], method="GET")
        for k, v in api.get("headers", {}).items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        bal = data.get(api.get("balance_field", "balance"))
        usage = data.get(api.get("usage_field", "usage"))
        return bal, usage
    except Exception as e:
        log(f"余额查询失败: {e}")
        return None, None


def run_loop(cfg: dict, once: bool = False):
    state = load_state()
    interval = max(5, int(cfg.get("poll_interval", 30)))
    log(f"开始监控 (interval={interval}s, mode={cfg.get('send_mode')})")
    while True:
        check_rate_limits(state, cfg)

        now = datetime.now()
        # 检查限流模型的重置时间，到点则发送该模型的待发任务
        rl = state.get("rate_limits", {})
        if not isinstance(rl, dict):
            rl = {}
            state["rate_limits"] = {}
        for key, info in list(rl.items()):
            reset_str = info.get("reset", "")
            if not reset_str:
                continue
            reset = datetime.strptime(reset_str, "%Y-%m-%d %H:%M:%S")
            if now >= reset:
                model = info.get("model", key)
                tasks = pending_tasks(state, model=model)
                if not tasks:
                    tasks = pending_tasks(state)  # 无指定模型则发全部
                for t in tasks:
                    send_task(t, cfg)
                if tasks:
                    # 发完即清除限流记录
                    state["rate_limits"].pop(key, None)
                    save_state(state)

        # 查询余额（可选）
        bal, usage = balance_check(cfg)
        if bal is not None:
            log(f"余额={bal} 用量={usage}")

        if once:
            break
        time.sleep(interval)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="WorkBuddy 用量/余额监控")
    p.add_argument("--add", metavar="TEXT", help="添加任务")
    p.add_argument("--model", default="", help="任务关联的模型（可选）")
    p.add_argument("--list", action="store_true", help="列出任务")
    p.add_argument("--status", action="store_true", help="查看限流状态")
    p.add_argument("--clear", action="store_true", help="清空已发送任务")
    p.add_argument("--parse", metavar="TEXT", help="解析一条限流消息（测试）")
    p.add_argument("--once", action="store_true", help="单次检查后退出")
    args = p.parse_args()

    cfg = load_config()

    if args.parse is not None:
        model, reset, ok = parse_rate_limit_message(args.parse)
        print(f"解析成功: {ok}\n模型: {model}\n重置时间: {reset}")
        return

    if args.add:
        state = load_state()
        add_task(state, args.add, args.model)
        return

    if args.list:
        state = load_state()
        tasks = state.get("tasks", [])
        if not tasks:
            print("(队列为空)")
        for t in tasks:
            mark = "[done]" if t["status"] == "sent" else "[wait]"
            print(f"{mark} #{t['id']} [{t['status']}] model={t.get('model','-')} {t['content']}")
        return

    if args.status:
        state = load_state()
        rl = state.get("rate_limits", {})
        if not rl:
            print("(无限流记录)")
        if not isinstance(rl, dict):
            rl = {}
        for k, v in rl.items():
            print(f"{k}: model={v.get('model')} reset={v.get('reset')}")
        return

    if args.clear:
        state = load_state()
        state["tasks"] = [t for t in state.get("tasks", []) if t["status"] != "sent"]
        save_state(state)
        print("已清理已发送任务")
        return

    run_loop(cfg, once=args.once)


if __name__ == "__main__":
    main()