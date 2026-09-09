# -*- coding: utf-8 -*-
"""
WorkBuddy 监控 - 可视化任务管理界面（响应式布局版）
运行: pythonw workbuddy_gui.py
"""
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
import workbuddy_monitor as core


class App:
    DEFAULT_MODELS = ["Hy4 preview", "Hy4", "GPT-5", "Claude Sonnet", "Claude Opus"]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("WorkBuddy 用量/余额监控 - 任务管理")
        self.root.geometry("780x560")
        self.root.minsize(620, 460)

        self.state = core.load_state()
        self.cfg = core.load_config()
        self.monitoring = False
        self._mon_stop = threading.Event()

        self._build_ui()
        self.refresh_all()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(2000, self._auto_sync)

    # ================================================================ UI
    def _build_ui(self):
        # 根容器：网格 3 行，第 2 行可伸缩
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self._build_top()      # row 0: 限流状态
        self._build_task_area()  # row 1: 任务列表（可伸缩）
        self._build_bottom()   # row 2: 监控控制

    def _build_top(self):
        top = ttk.LabelFrame(self.root, text="限流状态")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=0)

        self.lbl_limit = ttk.Label(top, text="（无）", font=("Microsoft YaHei", 10))
        self.lbl_limit.grid(row=0, column=0, sticky="w", padx=8, pady=4)

        # 限流按钮条：右侧折行排列
        btns = ttk.Frame(top)
        btns.grid(row=0, column=1, sticky="e", padx=8)
        ttk.Button(btns, text="📋 解析消息", command=self.on_parse_msg).grid(row=0, column=0, padx=2)
        ttk.Button(btns, text="🕊 剪贴板", command=self.on_clipboard).grid(row=0, column=1, padx=2)
        ttk.Button(btns, text="🗑 清除限流", command=self.on_clear_limit).grid(row=0, column=2, padx=2)

    def _build_task_area(self):
        mid = ttk.LabelFrame(self.root, text="待办任务列表（双击编辑）")
        mid.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        # 任务表格
        tree_frame = ttk.Frame(mid)
        tree_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=6)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        cols = ("model", "content", "created", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("model", text="模型")
        self.tree.heading("content", text="任务内容")
        self.tree.heading("created", text="创建时间")
        self.tree.heading("status", text="状态")
        self.tree.column("model", width=130, anchor="w", stretch=True)
        self.tree.column("content", width=330, anchor="w", stretch=True)
        self.tree.column("created", width=140, anchor="center", stretch=False)
        self.tree.column("status", width=90, anchor="center", stretch=False)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree.tag_configure("sent", foreground="gray")
        self.tree.tag_configure("pending", foreground="black")
        self.tree.bind("<Double-1>", lambda e: self.on_edit())

        # 任务输入行：输入框随窗口伸缩
        inbar = ttk.Frame(mid)
        inbar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        inbar.columnconfigure(1, weight=1)

        ttk.Label(inbar, text="任务:").grid(row=0, column=0, padx=(0, 4))
        self.ent_task = ttk.Entry(inbar)
        self.ent_task.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.ent_task.bind("<Return>", lambda e: self.on_add())

        ttk.Label(inbar, text="模型:").grid(row=0, column=2, padx=(0, 4))
        self.ent_model = ttk.Combobox(inbar, width=14, values=self.model_choices())
        self.ent_model.grid(row=0, column=3, padx=(0, 8))

        # 操作按钮：自动折行（columns 根据宽度变化换行）
        self.act_frame = ttk.Frame(inbar)
        self.act_frame.grid(row=0, column=4, sticky="e")
        self._act_buttons = [
            ("✏ 编辑", self.on_edit),
            ("👁 查看全文", self.on_view),
            ("🔁 重新入队", self.on_requeue),
            ("✕ 删除", self.on_delete),
        ]
        self._layout_act_buttons()
        self.act_frame.bind("<Configure>", lambda e: self._layout_act_buttons())

    def _layout_act_buttons(self):
        """根据输入行宽度决定操作按钮一行放几个（自适应折行）"""
        w = self.act_frame.winfo_width()
        if w < 10:
            return  # 首次布局前跳过
        per_row = 4 if w > 420 else (3 if w > 320 else 2)
        for i, (text, cmd) in enumerate(self._act_buttons):
            btn = getattr(self, f"_btn{i}", None)
            if btn is None:
                btn = ttk.Button(self.act_frame, text=text, command=cmd)
                setattr(self, f"_btn{i}", btn)
            btn.grid(row=i // per_row, column=i % per_row, padx=2, pady=2, sticky="ew")

    def _build_bottom(self):
        bot = ttk.LabelFrame(self.root, text="监控控制")
        bot.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
        bot.columnconfigure(2, weight=1)

        self.btn_toggle = ttk.Button(bot, text="▶ 启动监控", command=self.on_toggle_monitor)
        self.btn_toggle.grid(row=0, column=0, padx=8, pady=6)
        self.lbl_mon = ttk.Label(bot, text="⏸ 未运行", foreground="red")
        self.lbl_mon.grid(row=0, column=1, padx=4)
        ttk.Button(bot, text="💰 查看余额", command=self.on_balance).grid(row=0, column=3, padx=2)
        ttk.Button(bot, text="使用说明", command=self.on_help).grid(row=0, column=4, padx=2)

    # ========================================================= 模型选项
    def model_choices(self):
        got = list(self.DEFAULT_MODELS)
        rl = self.state.get("rate_limits", {})
        if isinstance(rl, dict):
            for v in rl.values():
                m = v.get("model") if isinstance(v, dict) else None
                if m and m not in got:
                    got.append(m)
        for t in self.state.get("tasks", []):
            m = t.get("model")
            if m and m not in got:
                got.append(m)
        return got

    # ========================================================= 刷新显示
    def refresh_all(self):
        self.refresh_limit()
        self.refresh_tasks()

    def refresh_limit(self):
        rl = self.state.get("rate_limits", {})
        if not isinstance(rl, dict) or not rl:
            self.lbl_limit.config(text="当前无限流，所有模型可用", foreground="green")
            return
        lines = []
        for k, v in rl.items():
            reset = v.get("reset", "?")
            left = ""
            try:
                dt = datetime.strptime(reset, "%Y-%m-%d %H:%M:%S")
                sec = (dt - datetime.now()).total_seconds()
                left = f"（约 {int(sec//3600)}小时{int(sec%3600//60)}分后恢复）" if sec > 0 else "（已可恢复）"
            except Exception:
                pass
            lines.append(f"⛔ {v.get('model', k)}  重置于 {reset}  {left}")
        self.lbl_limit.config(text="\n".join(lines), foreground="orange")

    def refresh_tasks(self):
        self.tree.delete(*self.tree.get_children())
        for t in self.state.get("tasks", []):
            tag = "sent" if t["status"] == "sent" else "pending"
            mark = "✅已发送" if t["status"] == "sent" else "⏳等待中"
            self.tree.insert("", "end", iid=str(t["id"]),
                             values=(t.get("model") or "-", t["content"], t.get("created", ""), mark),
                             tags=(tag,))

    def _save(self):
        core.save_state(self.state)

    def _auto_sync(self):
        """UI 主线程定时从磁盘同步状态，界面永远显示最新数据"""
        try:
            self.state = core.load_state()
            self.refresh_all()
        except Exception:
            pass
        self.root.after(2000, self._auto_sync)

    # ============================================================ 操作
    def on_add(self):
        content = self.ent_task.get().strip()
        if not content:
            messagebox.showwarning("提示", "请输入任务内容")
            return
        core.add_task(self.state, content, self.ent_model.get().strip())
        self.ent_task.delete(0, "end")
        self.ent_model["values"] = self.model_choices()
        self.refresh_tasks()

    def _selected_task(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择任务")
            return None
        tid = int(sel[0])
        return next((t for t in self.state.get("tasks", []) if t["id"] == tid), None)

    def on_delete(self):
        task = self._selected_task()
        if not task:
            return
        self.state["tasks"] = [t for t in self.state.get("tasks", []) if t["id"] != task["id"]]
        self._save()
        self.refresh_tasks()

    def on_requeue(self):
        task = self._selected_task()
        if not task:
            return
        task["status"] = "pending"
        self._save()
        self.refresh_tasks()

    def on_edit(self):
        task = self._selected_task()
        if not task:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(f"编辑任务 #{task['id']}")
        dlg.geometry("480x320")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.columnconfigure(0, weight=1)
        dlg.rowconfigure(1, weight=1)

        ttk.Label(dlg, text="任务内容:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 0))
        txt = tk.Text(dlg, font=("Microsoft YaHei", 10))
        txt.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        txt.insert("1.0", task["content"])

        fr = ttk.Frame(dlg)
        fr.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        ttk.Label(fr, text="模型:").pack(side="left")
        cmb = ttk.Combobox(fr, width=18, values=self.model_choices())
        cmb.pack(side="left", padx=4)
        cmb.set(task.get("model") or "")

        btns = ttk.Frame(dlg)
        btns.grid(row=3, column=0, pady=(4, 10))

        def save():
            c = txt.get("1.0", "end").strip()
            if not c:
                messagebox.showwarning("提示", "内容不能为空", parent=dlg)
                return
            task["content"] = c
            task["model"] = cmb.get().strip()
            self._save()
            self.refresh_tasks()
            dlg.destroy()

        ttk.Button(btns, text="💾 保存", command=save).pack(side="left", padx=4)
        ttk.Button(btns, text="取消", command=dlg.destroy).pack(side="left", padx=4)
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def on_view(self):
        task = self._selected_task()
        if not task:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title(f"任务详情 #{task['id']}")
        dlg.geometry("480x340")
        info = (f"编号: {task['id']}\n"
                f"模型: {task.get('model') or '-'}\n"
                f"创建时间: {task.get('created', '')}\n"
                f"状态: {task['status']}\n\n"
                f"────── 任务内容 ──────\n{task['content']}")
        txt = tk.Text(dlg, wrap="word", font=("Microsoft YaHei", 10))
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", info)
        txt.config(state="disabled")

    def on_parse_msg(self):
        msg = simpledialog.askstring("解析限流消息", "粘贴 WorkBuddy 限流消息：", parent=self.root)
        self._apply_limit_text(msg)

    def on_clipboard(self):
        try:
            self._apply_limit_text(self.root.clipboard_get())
        except Exception:
            messagebox.showwarning("提示", "剪贴板为空")

    def _apply_limit_text(self, msg):
        if not msg:
            return
        model, reset, ok = core.parse_rate_limit_message(msg)
        if not ok:
            messagebox.showwarning("解析失败", "未能从消息中识别模型/时间")
            return
        key = model or "default"
        entry = {"model": model or key}
        if reset:
            entry["reset"] = reset.strftime("%Y-%m-%d %H:%M:%S")
        entry["raw"] = msg.strip()[:300]
        self.state.setdefault("rate_limits", {})[key] = entry
        self._save()
        self.refresh_all()
        self.ent_model["values"] = self.model_choices()
        messagebox.showinfo("解析成功", f"模型: {model}\n重置时间: {reset}")

    def on_clear_limit(self):
        self.state["rate_limits"] = {}
        self._save()
        self.refresh_limit()

    def on_balance(self):
        bal, usage = core.balance_check(self.cfg)
        if bal is None:
            messagebox.showinfo("余额查询", "未配置余额 API，请编辑 config.json 填写 api.url")
        else:
            messagebox.showinfo("余额查询", f"余额: {bal}\n用量: {usage}")

    def on_help(self):
        messagebox.showinfo(
            "使用说明",
            "1. 添加任务：底部输入内容 + 选择模型 → 回车或点添加\n"
            "2. 编辑任务：双击行，或选中后点「编辑」\n"
            "3. 启动监控：到限流重置时间自动发送队列任务并提醒\n"
            "4. 限流时：复制 WorkBuddy 的限流消息 → 点「剪贴板」自动解析")

    # ======================================================== 后台监控
    def on_toggle_monitor(self):
        if self.monitoring:
            self._mon_stop.set()
            self.monitoring = False
            self.btn_toggle.config(text="▶ 启动监控")
            self.lbl_mon.config(text="⏸ 已停止", foreground="red")
        else:
            self._mon_stop = threading.Event()
            self.monitoring = True
            threading.Thread(target=self._monitor_loop, daemon=True).start()
            self.btn_toggle.config(text="⏹ 停止监控")
            self.lbl_mon.config(text="🟢 监控中…", foreground="green")

    def _monitor_loop(self):
        interval = max(5, int(self.cfg.get("poll_interval", 30)))
        while not self._mon_stop.is_set():
            try:
                # 每轮从磁盘读最新状态，避免与 UI/CLI 写入冲突
                state = core.load_state()
                core.check_rate_limits(state, self.cfg)
                now = datetime.now()
                rl = state.get("rate_limits", {})
                if isinstance(rl, dict):
                    for key, info in list(rl.items()):
                        reset_str = info.get("reset", "")
                        if not reset_str:
                            continue
                        try:
                            reset_dt = datetime.strptime(reset_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            core.log(f"限流记录 {key} 的时间戳无效: {reset_str}，跳过")
                            continue
                        if now >= reset_dt:
                            model = info.get("model", key)
                            tasks = core.pending_tasks(state, model=model) or core.pending_tasks(state)
                            for t in tasks:
                                core.send_task(t, self.cfg)
                            if tasks:
                                rl.pop(key, None)
                                core.save_state(state)
            except Exception as e:
                core.log(f"监控线程错误: {e}")
            self._mon_stop.wait(interval)

    def _on_close(self):
        self._mon_stop.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
