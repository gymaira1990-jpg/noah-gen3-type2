#!/usr/bin/env python3
"""系统健康报告 · 一键生成"""
import json, sys; sys.path.insert(0,'.')
from datetime import datetime

def generate():
    report = {"timestamp": datetime.now().isoformat(), "components": {}}
    try:
        from memory.pg_search import stats
        report["components"]["记忆"] = stats()
    except: report["components"]["记忆"] = "离线"
    try:
        from tools.registry import tools_status
        report["components"]["工具"] = tools_status()
    except: pass
    try:
        from logs.api_logger import api_logger
        report["components"]["API"] = api_logger.today_summary()
    except: pass
    try:
        from init_system import run_all_checks
        report["components"]["自检"] = {"all_pass": run_all_checks().get("all_pass", False)}
    except: pass
    try:
        from bridge import relay; h = relay.health()
        report["components"]["广州"] = h.get("status","?")
    except: report["components"]["广州"] = "未连接"
    try:
        from budget import budget
        report["components"]["预算"] = {"已用": f"¥{budget.data['cost']:.2f}", "剩余": f"¥{budget.remaining:.2f}"}
    except: pass
    return report

if __name__ == "__main__":
    r = generate()
    print(json.dumps(r, ensure_ascii=False, indent=2))
