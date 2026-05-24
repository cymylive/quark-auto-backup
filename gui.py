#!/usr/bin/env python3
"""
夸克自动备份 - GUI 界面
"""

import os
import sys
import json
import time
import threading
import subprocess
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image
import qrcode

from src.auth import get_quark_client, ensure_remote_dirs
from src.backup import QuarkBackup
from src.config import AppConfig
from src.scheduler import parse_schedule
from src.utils import setup_logging

os.environ["PYTHONIOENCODING"] = "utf-8"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

CONFIG_PATH = Path.cwd() / "config.yaml"
CACHE_DIR = Path.cwd() / "cache"


class BackupThread(threading.Thread):
    def __init__(self, app, client, config):
        super().__init__(daemon=True)
        self.app = app
        self.client = client
        self.config = config
        self.backup = None

    def run(self):
        try:
            self.backup = QuarkBackup(self.client, self.config)
            self.backup.run_all(progress_callback=self.app._on_backup_progress)
            self.app.after(0, self.app._on_backup_done)
        except Exception as e:
            self.app.after(0, lambda: self.app.backup_status.configure(text=f"错误: {e}"))
            self.app.after(0, lambda: self.app.backup_btn.configure(state="normal", text="▶ 开始备份"))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("夸克自动备份")
        self.geometry("900x650")
        self.minsize(800, 550)

        self.config = self._load_config()
        self.client: Optional["QuarkClient"] = None
        self.backup_thread: Optional[BackupThread] = None
        self.backup_results: list = []
        self.schedule_active = False

        self._build_ui()
        self._login_notified = False

        self.after(500, self._try_auto_login)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_config(self) -> Optional[AppConfig]:
        try:
            return AppConfig.load(str(CONFIG_PATH))
        except Exception as e:
            return None

    def _save_yaml(self):
        import yaml
        data = {
            "sources": [s.model_dump() for s in self.config.sources] if self.config else [],
            "schedule": self.config.schedule if self.config else "每天 02:00",
            "schedule_enabled": self.config.schedule_enabled if self.config else True,
            "remote_root": self.config.remote_root if self.config else "/自动备份",
            "retry": {"max_retries": 3, "retry_delay": 10},
            "concurrency": {"max_upload_workers": 3},
            "log_level": "INFO",
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, indent=2, sort_keys=False)

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self, anchor="nw")
        self.tabview.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")

        self.tab_dash = self.tabview.add("仪表盘")
        self.tab_sources = self.tabview.add("备份源")
        self.tab_backup = self.tabview.add("备份执行")
        self.tab_settings = self.tabview.add("设置")
        self.tab_log = self.tabview.add("日志")

        self._build_dashboard()
        self._build_sources()
        self._build_backup()
        self._build_settings()
        self._build_log()

    # ── Dashboard ───────────────────────────────────────────

    def _build_dashboard(self):
        self.tab_dash.grid_columnconfigure(0, weight=1)

        self.dash_frame = ctk.CTkFrame(self.tab_dash)
        self.dash_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.dash_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.dash_frame, text="夸克网盘状态", font=("", 18, "bold")).grid(row=0, column=0, pady=(10, 5))
        self.dash_status = ctk.CTkLabel(self.dash_frame, text="未登录", font=("", 14))
        self.dash_status.grid(row=1, column=0, pady=5)
        self.dash_storage = ctk.CTkLabel(self.dash_frame, text="", font=("", 13))
        self.dash_storage.grid(row=2, column=0, pady=5)
        self.dash_progress = ctk.CTkProgressBar(self.dash_frame, width=400)
        self.dash_progress.grid(row=3, column=0, pady=10)
        self.dash_progress.set(0)

        ctk.CTkLabel(self.dash_frame, text="最近备份", font=("", 18, "bold")).grid(row=4, column=0, pady=(20, 5))
        self.dash_last = ctk.CTkLabel(self.dash_frame, text="暂无备份记录", font=("", 13))
        self.dash_last.grid(row=5, column=0, pady=5)

        self.dash_btn = ctk.CTkButton(self.dash_frame, text="立即登录", command=self._login)
        self.dash_btn.grid(row=6, column=0, pady=15)

        ctk.CTkLabel(self.dash_frame, text="定时备份", font=("", 18, "bold")).grid(row=7, column=0, pady=(20, 5))
        sched_text = self.config.schedule if self.config else "未设置"
        if self.config and not self.config.schedule_enabled:
            sched_text += " (已禁用)"
        self.dash_schedule_info = ctk.CTkLabel(
            self.dash_frame,
            text=sched_text,
            font=("", 13),
        )
        self.dash_schedule_info.grid(row=8, column=0, pady=5)

    # ── Sources ─────────────────────────────────────────────

    def _build_sources(self):
        self.tab_sources.grid_columnconfigure(0, weight=1)
        self.tab_sources.grid_rowconfigure(0, weight=1)

        self.src_scroll = ctk.CTkScrollableFrame(self.tab_sources)
        self.src_scroll.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.src_scroll.grid_columnconfigure(1, weight=1)

        self.src_btn_frame = ctk.CTkFrame(self.tab_sources, fg_color="transparent")
        self.src_btn_frame.grid(row=1, column=0, pady=(0, 10))
        ctk.CTkButton(self.src_btn_frame, text="+ 添加备份源", command=self._add_source_dialog).pack(side="left", padx=5)
        ctk.CTkButton(self.src_btn_frame, text="刷新列表", command=self._render_sources).pack(side="left", padx=5)

        self._render_sources()

    def _render_sources(self):
        for w in self.src_scroll.winfo_children():
            w.destroy()

        if not self.config or not self.config.sources:
            ctk.CTkLabel(self.src_scroll, text="暂无备份源，点击上方按钮添加", font=("", 13)).grid(row=0, column=0, pady=40)
            return

        for i, src in enumerate(self.config.sources):
            frame = ctk.CTkFrame(self.src_scroll)
            frame.grid(row=i, column=0, padx=5, pady=5, sticky="ew")
            frame.grid_columnconfigure(1, weight=1)

            name = Path(src.local).name if Path(src.local).exists() else src.local
            ctk.CTkLabel(frame, text="\U0001F4C1 " + name, font=("", 13, "bold")).grid(row=0, column=0, padx=10, pady=5, sticky="w")
            info = ctk.CTkLabel(frame, text=f"本地: {src.local}\n远程: {src.remote}", font=("", 11), justify="left")
            info.grid(row=0, column=1, padx=10, pady=5, sticky="w")
            info.bind("<Double-1>", lambda e, idx=i: self._edit_source_dialog(idx))

            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.grid(row=0, column=2, padx=5)
            ctk.CTkButton(btn_frame, text="编辑", width=50, command=lambda idx=i: self._edit_source_dialog(idx)).pack(side="left", padx=2)
            ctk.CTkButton(btn_frame, text="\u2715", width=30, fg_color="red", hover_color="darkred",
                          command=lambda idx=i: self._delete_source(idx)).pack(side="left", padx=2)

    def _add_source_dialog(self):
        dialog = SourceDialog(self, "添加备份源")
        self.wait_window(dialog)
        if dialog.result:
            if self.config is None:
                from src.config import SourceConfig
                self.config = AppConfig(sources=[dialog.result], remote_root="/自动备份")
            else:
                self.config.sources.append(dialog.result)
            self._save_yaml()
            self._render_sources()

    def _edit_source_dialog(self, idx: int):
        src = self.config.sources[idx]
        dialog = SourceDialog(self, "编辑备份源", source=src)
        self.wait_window(dialog)
        if dialog.result:
            self.config.sources[idx] = dialog.result
            self._save_yaml()
            self._render_sources()

    def _delete_source(self, idx: int):
        if messagebox.askyesno("确认删除", "确定删除备份源吗？"):
            self.config.sources.pop(idx)
            self._save_yaml()
            self._render_sources()

    # ── Backup ──────────────────────────────────────────────

    def _build_backup(self):
        self.tab_backup.grid_columnconfigure(0, weight=1)
        self.tab_backup.grid_rowconfigure(1, weight=1)

        ctrl = ctk.CTkFrame(self.tab_backup)
        ctrl.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ctrl.grid_columnconfigure(0, weight=1)

        self.backup_btn = ctk.CTkButton(ctrl, text="▶ 开始备份", height=40, font=("", 14, "bold"),
                                         command=self._start_backup)
        self.backup_btn.pack(side="left", padx=5)
        self.cancel_btn = ctk.CTkButton(ctrl, text="\u25a0 取消", height=40, fg_color="gray",
                                         command=self._cancel_backup)
        self.cancel_btn.pack(side="left", padx=5)

        self.backup_status = ctk.CTkLabel(ctrl, text="就绪", font=("", 13))
        self.backup_status.pack(side="right", padx=10)

        self.backup_scroll = ctk.CTkScrollableFrame(self.tab_backup)
        self.backup_scroll.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.backup_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.backup_scroll, text="点击「开始备份」执行备份任务", font=("", 13)).grid(row=0, column=0, pady=40)

    def _start_backup(self):
        if not self.client:
            messagebox.showwarning("未登录", "请先在仪表盘页面登录夸克网盘")
            return
        if self.backup_thread and self.backup_thread.is_alive():
            messagebox.showinfo("提示", "备份正在进行中")
            return
        if self.config is None or not self.config.sources:
            messagebox.showwarning("无备份源", "请在备份源页面添加至少一个备份源")
            return

        self.backup_btn.configure(state="disabled", text="\u23f3 备份中...")
        self.backup_status.configure(text="正在备份...")
        for w in self.backup_scroll.winfo_children():
            w.destroy()

        self.backup_thread = BackupThread(self, self.client, self.config)
        self.backup_thread.start()

    def _cancel_backup(self):
        if self.backup_thread and self.backup_thread.backup:
            self.backup_thread.backup.cancel()
            self.backup_status.configure(text="正在取消...")

    def _on_backup_progress(self, event: str, data1, data2):
        if event == "begin":
            def add():
                f = ctk.CTkFrame(self.backup_scroll)
                f.grid(row=self.backup_scroll.grid_size()[1], column=0, padx=5, pady=3, sticky="ew")
                f.grid_columnconfigure(1, weight=1)
                name = Path(data1).name if data1 else "?"
                lbl = ctk.CTkLabel(f, text="\U0001F4C1 " + name, font=("", 13, "bold"))
                lbl.grid(row=0, column=0, padx=10, pady=2, sticky="w")
                pbar = ctk.CTkProgressBar(f, width=300)
                pbar.grid(row=0, column=1, padx=10, pady=2)
                pbar.set(0)
                total = data2["total"] if isinstance(data2, dict) else 0
                info = ctk.CTkLabel(f, text=f"0/{total}", font=("", 11))
                info.grid(row=0, column=2, padx=5)
                setattr(f, "_pbar", pbar)
                setattr(f, "_info", info)
                setattr(f, "_total", total)
            self.after(0, add)

        elif event == "file_done":
            def update():
                for f in self.backup_scroll.winfo_children():
                    pbar = getattr(f, "_pbar", None)
                    info = getattr(f, "_info", None)
                    total = getattr(f, "_total", 1)
                    if pbar and info and isinstance(data2, dict):
                        done = data2.get("uploaded", 0) + data2.get("failed", 0)
                        pbar.set(min(done / total, 1.0))
                        info.configure(text=f"{done}/{total}")
            self.after(0, update)

        elif event == "status":
            self.after(0, lambda t=str(data1): self.backup_status.configure(text=t))

    def _on_backup_done(self):
        self.backup_btn.configure(state="normal", text="▶ 开始备份")
        self.backup_status.configure(text="备份完成")

    # ── Settings ────────────────────────────────────────────

    def _apply_schedule_preset(self, preset):
        self.setting_schedule.delete(0, "end")
        self.setting_schedule.insert(0, preset)

    def _build_settings(self):
        self.tab_settings.grid_columnconfigure(0, weight=1)

        f = ctk.CTkFrame(self.tab_settings)
        f.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(f, text="定时备份", font=("", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(5, 15))

        self.schedule_enabled_var = ctk.BooleanVar(value=self.config.schedule_enabled if self.config else True)
        self.schedule_switch = ctk.CTkSwitch(f, text="启用定时备份", variable=self.schedule_enabled_var,
                                              command=self._on_schedule_toggle)
        self.schedule_switch.grid(row=1, column=0, columnspan=2, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(f, text="调度计划:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.setting_schedule = ctk.CTkEntry(f, width=250)
        self.setting_schedule.insert(0, self.config.schedule if self.config else "每天 02:00")
        self.setting_schedule.grid(row=2, column=1, padx=10, pady=5, sticky="w")

        preset_frame = ctk.CTkFrame(f, fg_color="transparent")
        preset_frame.grid(row=3, column=1, padx=10, pady=(0, 5), sticky="w")
        presets = ["每天 02:00", "每天 08:00", "每小时", "每 30 分钟", "每周一 03:00"]
        for p in presets:
            ctk.CTkButton(preset_frame, text=p, width=90, height=24, font=("", 10),
                          command=lambda s=p: self._apply_schedule_preset(s)).pack(side="left", padx=2)

        ctk.CTkLabel(f, text="远程根目录:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.setting_root = ctk.CTkEntry(f, width=250)
        self.setting_root.insert(0, self.config.remote_root if self.config else "/自动备份")
        self.setting_root.grid(row=4, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkLabel(f, text="并发上传数:").grid(row=5, column=0, padx=10, pady=5, sticky="w")
        self.setting_concurrency = ctk.CTkEntry(f, width=100)
        self.setting_concurrency.insert(0, str(self.config.concurrency.max_upload_workers) if self.config else "3")
        self.setting_concurrency.grid(row=5, column=1, padx=10, pady=5, sticky="w")

        ctk.CTkButton(f, text="保存设置", command=self._save_settings).grid(row=6, column=1, padx=10, pady=15, sticky="w")

        g = ctk.CTkFrame(self.tab_settings)
        g.grid(row=1, column=0, padx=20, pady=20, sticky="ew")
        g.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g, text="缓存管理", font=("", 16, "bold")).grid(row=0, column=0, columnspan=2, pady=(5, 15))
        ctk.CTkButton(g, text="清除缓存（重置增量备份）", command=self._clear_cache).grid(row=1, column=1, padx=10, pady=5, sticky="w")

    def _on_schedule_toggle(self):
        state = "normal" if self.schedule_enabled_var.get() else "disabled"
        self.setting_schedule.configure(state=state)
        for child in self.setting_schedule.master.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for btn in child.winfo_children():
                    if isinstance(btn, ctk.CTkButton):
                        btn.configure(state=state)

    def _save_settings(self):
        if not self.config:
            return
        self.config.schedule = self.setting_schedule.get()
        self.config.schedule_enabled = self.schedule_enabled_var.get()
        self.config.remote_root = self.setting_root.get()
        try:
            self.config.concurrency.max_upload_workers = int(self.setting_concurrency.get())
        except ValueError:
            pass
        self._save_yaml()
        status = self.config.schedule if self.config.schedule_enabled else "已禁用"
        self.dash_schedule_info.configure(text=status)
        messagebox.showinfo("已保存", "设置已保存")

    def _clear_cache(self):
        if messagebox.askyesno("确认", "清除缓存后，下次备份将重新上传所有文件。确定继续？"):
            for f in CACHE_DIR.glob("*.json"):
                f.unlink()
            messagebox.showinfo("完成", "缓存已清除")

    # ── Log ─────────────────────────────────────────────────

    def _build_log(self):
        self.tab_log.grid_columnconfigure(0, weight=1)
        self.tab_log.grid_rowconfigure(1, weight=1)

        btn_frame = ctk.CTkFrame(self.tab_log, fg_color="transparent")
        btn_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        ctk.CTkButton(btn_frame, text="刷新日志", command=self._refresh_log).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="打开日志文件", command=self._open_log).pack(side="left", padx=5)

        self.log_text = ctk.CTkTextbox(self.tab_log, wrap="word", font=("Consolas", 11))
        self.log_text.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")

    def _refresh_log(self):
        self.log_text.delete("1.0", "end")
        log_file = Path.cwd() / "backup.log"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-200:]:
                    self.log_text.insert("end", line)
        self.log_text.see("end")

    def _open_log(self):
        log_file = Path.cwd() / "backup.log"
        if log_file.exists():
            os.startfile(str(log_file))

    # ── Login ───────────────────────────────────────────────

    def _try_auto_login(self):
        if self.client is not None:
            return
        self.dash_btn.configure(state="disabled", text="检测登录状态...")
        threading.Thread(target=self._do_try_login, daemon=True).start()

    def _do_try_login(self):
        try:
            from quark_client.auth.login import QuarkAuth
            auth = QuarkAuth()
            saved = auth._load_cookies()
            if saved:
                cookie_string = auth._cookies_to_string(saved['cookies'])
                required = ['__pus', '__kps', '__uid']
                if all(r in cookie_string for r in required):
                    from quark_client import QuarkClient
                    self.client = QuarkClient(cookies=cookie_string, auto_login=False)
                    self.after(0, self._update_dashboard)
                    return
                # Cookie 格式不完整，尝试刷新
                if self._try_refresh_cookies(auth):
                    return
        except Exception:
            pass
        # Cookie 过期，尝试用 service_ticket 刷新
        try:
            if self._try_refresh_cookies():
                return
        except Exception:
            pass
        self.after(0, lambda: self.dash_btn.configure(state="normal", text="立即登录"))

    def _try_refresh_cookies(self, auth=None):
        import json, httpx
        from quark_client.config import get_config_dir
        from quark_client.auth.login import QuarkAuth
        lf = get_config_dir() / 'login_result.json'
        if not lf.exists():
            return False
        with open(lf, 'r', encoding='utf-8') as f:
            result = json.load(f)
        st = result.get('data', {}).get('members', {}).get('service_ticket')
        if not st:
            return False
        try:
            client = httpx.Client(timeout=30.0, follow_redirects=True)
            resp = client.get('https://pan.quark.cn/account/info', params={'st': st, 'lw': 'scan'})
            if resp.status_code == 200:
                cookie_dicts = []
                for c in client.cookies.jar:
                    if c.domain and 'quark.cn' in c.domain:
                        cookie_dicts.append({
                            'name': c.name, 'value': c.value,
                            'domain': c.domain, 'path': c.path or '/',
                            'expires': int(c.expires) if c.expires else 0,
                        })
                if cookie_dicts:
                    qa = auth or QuarkAuth()
                    qa._save_cookies(cookie_dicts)
                    from quark_client import QuarkClient
                    cs = qa._cookies_to_string(cookie_dicts)
                    self.client = QuarkClient(cookies=cs, auto_login=False)
                    self.after(0, self._update_dashboard)
                    return True
        except Exception:
            pass
        return False

    def _login(self):
        if self.client is not None:
            self._update_dashboard()
            return
        dialog = QrLoginDialog(self)
        self.wait_window(dialog)
        if dialog.cookie_string:
            from quark_client import QuarkClient
            self.client = QuarkClient(cookies=dialog.cookie_string, auto_login=False)
            self._update_dashboard()
        self.dash_btn.configure(state="normal", text="立即登录")

    def _update_dashboard(self):
        self.dash_btn.configure(state="normal", text="重新登录")
        self.dash_status.configure(text="已登录", text_color="green")
        try:
            info = self.client.get_storage_info()
            if "data" in info:
                d = info["data"]
                total = d.get("total_size", 0) / (1024**3)
                used = d.get("used_size", 0) / (1024**3)
                ratio = used / total if total > 0 else 0
                self.dash_storage.configure(
                    text=f"总空间: {total:.1f} GB  |  已用: {used:.1f} GB  |  剩余: {(total - used):.1f} GB"
                )
                self.dash_progress.set(ratio)
        except Exception:
            pass
        rc = CACHE_DIR / "backup_results.json"
        if rc.exists():
            try:
                with open(rc, "r", encoding="utf-8") as f:
                    rst = json.load(f)
                self.dash_last.configure(text=f"最近: {rst.get('time', '未知')}")
            except Exception:
                pass

    # ── Misc ────────────────────────────────────────────────

    def _on_close(self):
        if self.backup_thread and self.backup_thread.is_alive():
            if not messagebox.askokcancel("确认退出", "备份正在进行，确定退出？"):
                return
        self.destroy()


class QrLoginDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)

        self.cookie_string: Optional[str] = None
        self.title("扫码登录夸克网盘")
        self.geometry("400x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="请使用夸克 APP 扫码登录", font=("", 16, "bold")).grid(row=0, column=0, pady=(10, 5))
        ctk.CTkLabel(frame, text="打开夸克 APP → 扫一扫", font=("", 12)).grid(row=1, column=0, pady=(0, 15))

        self.qr_label = ctk.CTkLabel(frame, text="正在生成二维码...", font=("", 13))
        self.qr_label.grid(row=2, column=0, pady=10)

        self.status_label = ctk.CTkLabel(frame, text="", font=("", 12))
        self.status_label.grid(row=3, column=0, pady=5)

        self.progress = ctk.CTkProgressBar(frame, width=300)
        self.progress.grid(row=4, column=0, pady=10)
        self.progress.set(0)

        self.time_label = ctk.CTkLabel(frame, text="", font=("", 11))
        self.time_label.grid(row=5, column=0, pady=(0, 5))

        self.manual_btn = ctk.CTkButton(frame, text="浏览器打开", command=self._open_browser)
        self.manual_btn.grid(row=6, column=0, pady=5)
        self.cancel_btn = ctk.CTkButton(frame, text="取消", fg_color="gray", command=self.destroy)
        self.cancel_btn.grid(row=7, column=0, pady=5)

        self._stop = False
        self._api_login = None
        threading.Thread(target=self._do_qr_login, daemon=True).start()

    def _do_qr_login(self):
        from quark_client.auth.api_login import APILogin
        try:
            self.after(0, lambda: self.status_label.configure(text="获取二维码..."))
            api = APILogin(timeout=180)
            self._api_login = api
            qr_token, qr_url = api.get_qr_code()

            qr_img = qrcode.make(qr_url)
            qr_img = qr_img.resize((280, 280), Image.NEAREST)
            ctk_img = ctk.CTkImage(light_image=qr_img, dark_image=qr_img, size=(280, 280))
            self.after(0, lambda: self.qr_label.configure(image=ctk_img, text=""))
            self.after(0, lambda: self.status_label.configure(text="等待扫码..."))
            self.after(0, lambda: self.progress.configure(indeterminate=False))
            self.after(0, lambda: self.progress.set(0))

            start = time.time()
            timeout = 180
            while time.time() - start < timeout and not self._stop:
                elapsed = int(time.time() - start)
                remaining = timeout - elapsed
                self.after(0, lambda r=remaining: self.time_label.configure(
                    text=f"剩余 {r//60}:{r%60:02d} 秒"
                ))

                result = api.check_login_status(qr_token)
                if result is not None and api._is_login_success(result):
                    self.after(0, lambda: self.status_label.configure(text="登录成功！", text_color="green"))
                    api._save_login_result(result)
                    cookies = []
                    for cookie in api.client.cookies.jar:
                        if cookie.domain and 'quark.cn' in cookie.domain:
                            cookies.append(f"{cookie.name}={cookie.value}")
                    self.cookie_string = "; ".join(cookies)
                    self._save_cookies_persistent(api)
                    self.after(500, self.destroy)
                    return

                progress_val = min(elapsed / timeout, 0.95)
                self.after(0, lambda v=progress_val: self.progress.set(v))
                time.sleep(2)

            if not self._stop:
                self.after(0, lambda: self.status_label.configure(text="二维码已过期，请重新登录", text_color="red"))
                self.after(0, lambda: self.qr_label.configure(image="", text="已过期"))

        except Exception as e:
            self.after(0, lambda: self.status_label.configure(text=f"错误: {e}", text_color="red"))
            self.after(0, lambda: self.qr_label.configure(image="", text="加载失败"))

    def _open_browser(self):
        import webbrowser
        if self._api_login:
            _, qr_url = self._api_login.get_qr_code()
            webbrowser.open(qr_url)

    def destroy(self):
        self._stop = True
        super().destroy()

    def _save_cookies_persistent(self, api):
        try:
            from quark_client.auth.login import QuarkAuth
            auth = QuarkAuth()
            cookie_dicts = []
            for c in api.client.cookies.jar:
                if c.domain and 'quark.cn' in c.domain:
                    cookie_dicts.append({
                        'name': c.name,
                        'value': c.value,
                        'domain': c.domain,
                        'path': c.path or '/',
                        'expires': int(c.expires) if c.expires else 0,
                    })
            if cookie_dicts:
                auth._save_cookies(cookie_dicts)
        except Exception:
            pass


class SourceDialog(ctk.CTkToplevel):
    def __init__(self, parent, title, source=None):
        super().__init__(parent)

        self.result = None
        self.title(title)
        self.geometry("550x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="本地路径:").grid(row=0, column=0, padx=15, pady=(20, 5), sticky="w")
        self.local_entry = ctk.CTkEntry(self, width=350)
        self.local_entry.grid(row=0, column=1, padx=15, pady=(20, 5))
        if source:
            self.local_entry.insert(0, source.local)
        ctk.CTkButton(self, text="浏览...", width=60, command=self._browse_local).grid(row=0, column=2, padx=(0, 15), pady=(20, 5))

        ctk.CTkLabel(self, text="远程目录:").grid(row=1, column=0, padx=15, pady=5, sticky="w")
        self.remote_entry = ctk.CTkEntry(self, width=350)
        self.remote_entry.grid(row=1, column=1, padx=15, pady=5)
        if source:
            self.remote_entry.insert(0, source.remote)

        self.recursive_var = ctk.BooleanVar(value=source.recursive if source else True)
        ctk.CTkCheckBox(self, text="递归子目录", variable=self.recursive_var).grid(row=2, column=1, padx=15, pady=5, sticky="w")

        self.delete_var = ctk.BooleanVar(value=source.delete_after_backup if source else False)
        ctk.CTkCheckBox(self, text="备份后删除原文件", variable=self.delete_var).grid(row=3, column=1, padx=15, pady=5, sticky="w")

        ctk.CTkLabel(self, text="排除模式 (每行一个, glob):").grid(row=4, column=0, padx=15, pady=(10, 5), sticky="nw")
        self.exclude_text = ctk.CTkTextbox(self, width=350, height=80)
        self.exclude_text.grid(row=4, column=1, padx=15, pady=(10, 5))
        if source:
            self.exclude_text.insert("1.0", "\n".join(source.exclude))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=1, pady=15)
        ctk.CTkButton(btn_frame, text="确定", command=self._confirm).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", command=self.destroy).pack(side="left", padx=5)

    def _browse_local(self):
        path = filedialog.askdirectory(title="选择要备份的文件夹")
        if path:
            self.local_entry.delete(0, "end")
            self.local_entry.insert(0, path)

    def _confirm(self):
        local = self.local_entry.get().strip()
        remote = self.remote_entry.get().strip()
        if not local:
            messagebox.showwarning("提示", "请选择本地路径", parent=self)
            return
        if not remote:
            messagebox.showwarning("提示", "请输入远程目录", parent=self)
            return

        exclude = [l.strip() for l in self.exclude_text.get("1.0", "end").strip().split("\n") if l.strip()]

        from src.config import SourceConfig
        self.result = SourceConfig(
            local=local,
            remote=remote,
            exclude=exclude,
            recursive=self.recursive_var.get(),
            delete_after_backup=self.delete_var.get(),
        )
        self.destroy()


def run_gui():
    try:
        setup_logging()
        app = App()
        app.mainloop()
    except Exception:
        error_file = Path.cwd() / "gui_error.log"
        with open(error_file, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"GUI 启动失败，详情请查看 {error_file}", file=sys.stderr)
        raise


if __name__ == "__main__":
    run_gui()
