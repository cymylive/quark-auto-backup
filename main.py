#!/usr/bin/env python3
"""
夸克自动备份 - Quark Auto Backup
定时将本地文件夹自动备份到夸克网盘
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

from src.auth import get_quark_client
from src.backup import QuarkBackup
from src.config import AppConfig
from src.scheduler import setup_schedule, run_loop
from src.utils import setup_logging, ensure_config

console = Console()

BANNER = """
[cyan]╔══════════════════════════════════════╗
║       夸克自动备份  v1.0               ║
║    Quark Auto Backup Tool              ║
╚══════════════════════════════════════╝[/]"""


def cmd_login():
    rprint(BANNER)
    console.print("\n[bold]登录到夸克网盘...[/]")
    console.print("[yellow]将打开二维码登录，请使用夸克 APP 扫码[/]\n")
    try:
        client = get_quark_client(auto_login=True)
        info = client.get_storage_info()
        console.print(f"[green]登录成功！[/]")
        if "data" in info:
            d = info["data"]
            total_gb = d.get("total_size", 0) / (1024**3)
            used_gb = d.get("used_size", 0) / (1024**3)
            console.print(f"  总空间: [cyan]{total_gb:.1f} GB[/]")
            console.print(f"  已用: [yellow]{used_gb:.1f} GB[/]")
            console.print(f"  剩余: [green]{(total_gb - used_gb):.1f} GB[/]")
        return client
    except Exception as e:
        console.print(f"[red]登录失败: {e}[/]")
        sys.exit(1)


def cmd_backup(client=None, config: AppConfig = None, run_once: bool = True):
    if client is None:
        client = get_quark_client()
    if config is None:
        config = AppConfig.load(ensure_config())

    backup = QuarkBackup(client, config)

    if run_once:
        console.rule("[bold cyan]开始备份[/]")
        results = backup.run_all()
        console.rule("[bold cyan]备份完成[/]")
        for r in results:
            status_icon = "[green]✓[/]" if r.get("status") == "completed" else "[yellow]~[/]" if r.get(
                "status"
            ) in ("up_to_date", "skipped") else "[red]✗[/]"
            console.print(
                f"  {status_icon} {r['source']}: "
                f"上传 [cyan]{r.get('uploaded', 0)}[/], "
                f"跳过 [dim]{r.get('skipped', 0)}[/], "
                f"失败 [red]{r.get('failed', 0)}[/]"
            )
        return results
    else:
        setup_schedule(config.schedule, lambda: backup.run_all())
        run_loop()


def cmd_status(client=None, config: AppConfig = None):
    if client is None:
        client = get_quark_client()
    if config is None:
        config = AppConfig.load(ensure_config())

    info = client.get_storage_info()
    rprint(BANNER)
    console.print("\n[bold]存储状态[/]")
    if "data" in info:
        d = info["data"]
        total_gb = d.get("total_size", 0) / (1024**3)
        used_gb = d.get("used_size", 0) / (1024**3)
        file_count = d.get("file_count", 0)
        console.print(f"  总空间: [cyan]{total_gb:.1f} GB[/]")
        console.print(f"  已用: [yellow]{used_gb:.1f} GB[/]")
        console.print(f"  空间使用率: [bold]{used_gb/total_gb*100:.1f}%[/]" if total_gb > 0 else "  N/A")
        console.print(f"  文件数: [cyan]{file_count}[/]")

    console.print("\n[bold]备份配置[/]")
    for src in config.sources:
        console.print(f"  [cyan]{src.local}[/] → [green]{src.remote}[/]")
    console.print(f"\n[bold]定时计划[/]: [yellow]{config.schedule}[/]")


def main():
    args = [a.lower() for a in sys.argv[1:]]

    setup_logging()

    if args and args[0] == "gui":
        from gui import run_gui
        run_gui()
        return

    config_path = ensure_config()
    config = AppConfig.load(config_path)

    if not args or args[0] == "backup":
        cmd_backup(config=config)
    elif args[0] == "login":
        cmd_login()
    elif args[0] == "status":
        cmd_status(config=config)
    elif args[0] == "watch":
        cmd_backup(config=config, run_once=False)
    elif args[0] in ("-h", "--help", "help"):
        print("""用法: python main.py [命令]

命令:
  gui           启动图形界面
  backup        执行一次备份（默认）
  login         登录夸克网盘
  status        查看存储状态和配置
  watch         启动定时监控备份
  help          显示此帮助
        """)
    else:
        console.print(f"[red]未知命令: {args[0]}[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
