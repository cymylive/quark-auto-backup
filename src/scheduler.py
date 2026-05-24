import re
import schedule
import time
from typing import Callable
from rich.console import Console

console = Console()

_week_map = {
    "一": "monday", "二": "tuesday", "三": "wednesday",
    "四": "thursday", "五": "friday", "六": "saturday", "日": "sunday",
}


def _parse_weekly(m):
    weekday = _week_map.get(m.group(1), "monday")
    time_str = f"{m.group(2)}:{m.group(3)}"
    return (weekday, time_str)


_time_patterns = [
    (re.compile(r"每\s*(\d+)\s*秒"), lambda m: ("seconds", int(m.group(1)))),
    (re.compile(r"每\s*(\d+)\s*分钟?"), lambda m: ("minutes", int(m.group(1)))),
    (re.compile(r"每\s*(\d+)\s*小时?"), lambda m: ("hours", int(m.group(1)))),
    (re.compile(r"每小时?"), lambda _: ("hours", 1)),
    (re.compile(r"每分钟?"), lambda _: ("minutes", 1)),
    (re.compile(r"每天\s*(\d{1,2}):(\d{2})"), lambda m: ("daily", f"{m.group(1)}:{m.group(2)}")),
    (re.compile(r"每周([一二三四五六日])\s*(\d{1,2}):(\d{2})"), _parse_weekly),
    (re.compile(r"每天"), lambda _: ("daily", "00:00")),
]


def parse_schedule(desc: str):
    for pattern, handler in _time_patterns:
        m = pattern.match(desc)
        if m:
            return handler(m)
    raise ValueError(f"无法解析调度表达式: {desc}")


def setup_schedule(desc: str, job_func: Callable):
    kind, value = parse_schedule(desc)

    if kind == "seconds":
        schedule.every(value).seconds.do(job_func)
    elif kind == "minutes":
        schedule.every(value).minutes.do(job_func)
    elif kind == "hours":
        schedule.every(value).hours.do(job_func)
    elif kind == "daily":
        schedule.every().day.at(value).do(job_func)
    elif kind in _week_map.values():
        getattr(schedule.every(), kind).at(value).do(job_func)
    else:
        raise ValueError(f"不支持的调度类型: {kind}")

    console.print(f"[green]定时备份已设置: {desc}[/]")


def run_loop():
    console.print("[dim]等待定时任务触发... (按 Ctrl+C 停止)[/]")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]定时备份已停止[/]")
