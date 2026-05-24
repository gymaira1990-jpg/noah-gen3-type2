#!/usr/bin/env python3
"""远征工具箱 · tools/toolbox.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
扩展工具: 定时任务、通知、系统状态
"""

import json
import time as time_module
import threading
from pathlib import Path
from tools.registry import register, is_safe_path

PRIME_ROOT = Path(__file__).parent.parent

# ─── 定时任务调度 ───

_scheduled_tasks = {}
_scheduler_running = False


def schedule_task(task_id: str, interval_minutes: int, func_name: str, func_args: dict = None) -> dict:
    """注册定时任务 (简易版，无外部依赖)"""
    _scheduled_tasks[task_id] = {
        "interval_minutes": interval_minutes,
        "func_name": func_name,
        "func_args": func_args or {},
        "last_run": 0,
        "enabled": True,
    }
    return {"status": "ok", "task_id": task_id, "interval_minutes": interval_minutes}


def _run_scheduler():
    """后台调度线程"""
    global _scheduler_running
    _scheduler_running = True
    while _scheduler_running:
        now = time_module.time()
        for task_id, cfg in list(_scheduled_tasks.items()):
            if not cfg["enabled"]:
                continue
            if now - cfg["last_run"] >= cfg["interval_minutes"] * 60:
                cfg["last_run"] = now
                # 安全: 仅调用已注册工具
                from tools.registry import TOOL_REGISTRY
                if cfg["func_name"] in TOOL_REGISTRY:
                    try:
                        func = TOOL_REGISTRY[cfg["func_name"]]["func"]
                        func(**cfg["func_args"])
                    except Exception:
                        pass
        time_module.sleep(30)


def start_scheduler() -> dict:
    """启动后台调度器"""
    if not _scheduler_running:
        t = threading.Thread(target=_run_scheduler, daemon=True)
        t.start()
        return {"status": "ok", "message": "调度器已启动"}
    return {"status": "ok", "message": "调度器已在运行"}


def list_scheduled() -> list:
    return [
        {"id": k, "interval": v["interval_minutes"], "func": v["func_name"], "enabled": v["enabled"]}
        for k, v in _scheduled_tasks.items()
    ]


register("schedule_task", schedule_task, "toolbox", "注册定时任务", requires_review=False)
register("start_scheduler", start_scheduler, "toolbox", "启动后台调度器", requires_review=False)
register("list_scheduled", list_scheduled, "toolbox", "列出定时任务", requires_review=False)

# ─── 系统状态 ───

def get_system_info() -> dict:
    """获取系统资源信息"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "status": "ok",
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory": {
                "total_gb": round(mem.total / 1e9, 1),
                "used_gb": round(mem.used / 1e9, 1),
                "percent": mem.percent,
            },
            "disk": {
                p.mountpoint: {
                    "total_gb": round(psutil.disk_usage(p.mountpoint).total / 1e9, 1),
                    "used_percent": psutil.disk_usage(p.mountpoint).percent,
                }
                for p in psutil.disk_partitions() if p.fstype and p.mountpoint.startswith("/")
            },
        }
    except ImportError:
        return {"status": "ok", "note": "psutil未安装 — 安装后可获取详细系统信息"}


register("get_system_info", get_system_info, "toolbox", "获取系统资源信息", requires_review=False)

# ─── 测试 ───
if __name__ == "__main__":
    print("定时任务:", list_scheduled())
    print("系统信息:", json.dumps(get_system_info(), ensure_ascii=False, indent=2))
