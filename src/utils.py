import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
import logging


console = Console()


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            RichHandler(console=console, show_time=True, show_path=False, markup=True),
            logging.FileHandler(Path.cwd() / "backup.log", encoding="utf-8"),
        ],
    )


def ensure_config() -> Path:
    config_path = Path.cwd() / "config.yaml"
    if not config_path.exists():
        console.print("[red]config.yaml 不存在！请先创建配置文件。[/]")
        console.print("[yellow]您可以复制 config.yaml 并根据需要修改。[/]")
        sys.exit(1)
    return config_path
