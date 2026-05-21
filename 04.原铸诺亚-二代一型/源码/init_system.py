#!/usr/bin/env python3
"""系统初始化 + 环境检测 · init_system.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
遵循 NOA-006 设计 · 补充1+2
"""

import sys
import subprocess
import json
from pathlib import Path
from pg_conn import cursor

PRIME_ROOT = Path(__file__).parent
REQUIRED_PYTHON = (3, 10)
REQUIRED_MODELS = ["deepseek-v4-flash", "qwen2.5:0.5b", "qwen3-embedding:0.6b"]


def check_python() -> dict:
    ok = sys.version_info >= REQUIRED_PYTHON
    return {"passed": ok, "current": sys.version.split()[0],
            "required": f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}+"}


def check_ollama() -> dict:
    try:
        import httpx
        r = httpx.get("http://localhost:11435/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            missing = [m for m in REQUIRED_MODELS if not any(m in n for n in models)]
            return {"passed": True, "models_found": len(models),
                    "missing": missing, "hint": f"ollama pull {' '.join(missing)}" if missing else ""}
    except Exception:
        return {"passed": False, "error": "Ollama未运行", "hint": "请先启动Ollama: ollama serve"}


def check_pg() -> dict:
    try:
        with cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            n = cur.fetchone()[0]
        return {"passed": True, "tables": n}
    except Exception as e:
        return {"passed": False, "error": str(e)[:100]}


def check_dirs() -> dict:
    required = ["logs", "data", "brain", "tools", "memory", "web"]
    missing = [d for d in required if not (PRIME_ROOT / d).exists()]
    return {"passed": len(missing) == 0, "missing": missing}


def check_integrity() -> dict:
    """完整性自检——所有核心文件是否存在"""
    required_files = [
        "constitution.yaml", "noah_pipeline.py", "protection.py",
        "reviewer.py", "ticket.py", "logger.py", "persona.py",
        "bridge.py", "ssmp.py", "server.py", "vault/loader.py",
        "tools/registry.py", "memory/pg_search.py",
    ]
    missing = [f for f in required_files if not (PRIME_ROOT / f).exists()]
    return {"passed": len(missing) == 0, "missing": missing}


def run_all_checks() -> dict:
    """运行全部检查"""
    results = {
        "python": check_python(),
        "ollama": check_ollama(),
        "postgresql": check_pg(),
        "directories": check_dirs(),
        "integrity": check_integrity(),
    }
    all_pass = all(r.get("passed", False) for r in results.values())
    results["all_pass"] = all_pass
    return results


def print_report(results: dict):
    """打印人类可读报告"""
    print("\n" + "=" * 50)
    print("  ⚙ NOAH-PRIME · 铸造世界启动检查")
    print("=" * 50)
    for name, r in results.items():
        if name == "all_pass":
            continue
        status = "✅" if r.get("passed") else "❌"
        print(f"  {status} {name}: ", end="")
        if r.get("passed"):
            if "tables" in r:
                print(f"{r['tables']}张表")
            elif "models_found" in r:
                print(f"{r['models_found']}个模型就绪")
            else:
                print("通过")
        else:
            print(r.get("error") or r.get("hint") or "未知错误")

    print("-" * 50)
    if results["all_pass"]:
        print("  ✅ 一切就绪 · 万机之神见证")
    else:
        print("  ⚠ 存在问题 · 请根据以上提示修复")
    print("=" * 50 + "\n")

    # 中断恢复
    try:
        from logger import log
        pending = log.pending_tickets()
        if pending:
            print(f"  📋 发现 {len(pending)} 个未完成的工单:")
            for t in pending[:3]:
                print(f"     [{t['status']}] {t['ticket_id']}: {t.get('summary','')[:50]}")
            print("     启动后将自动提示恢复")
    except Exception:
        pass


if __name__ == "__main__":
    results = run_all_checks()
    print_report(results)
    sys.exit(0 if results["all_pass"] else 1)
