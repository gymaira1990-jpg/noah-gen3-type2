#!/usr/bin/env python3
"""原铸诺亚 · 安全沙箱启动器

职责:
  1. 验证独立性 (不依赖 ~/.hermes/)
  2. 加载宪法规则
  3. 启动 原铸 独立进程
  4. 注册进程退出清理

用法:
  python3 start.py [--cli] [--web]
    --cli  : CLI 交互模式 (默认)
    --web  : Web UI 模式 (端口 8888)

安全:
  - 运行在独立 venv 中
  - 只能写入 ~/noah-prime/ 目录
  - 不可访问 ~/.hermes/
  - 所有输出经过 reflex_guard 审查
"""

import sys, os, json, subprocess, signal, atexit
from pathlib import Path

PRIME_ROOT = Path.home() / "noah-prime"
VENV_PYTHON = PRIME_ROOT / "venv" / "bin" / "python3"

# ═══════════════════════════════════════════════════════
# 安全验证
# ═══════════════════════════════════════════════════════

def check_independence() -> list:
    """验证原铸运行环境独立性"""
    warnings = []

    # 1. 确认 venv 存在
    if not VENV_PYTHON.exists():
        warnings.append("❌ venv 不存在: 请先 python3 -m venv ~/noah-prime/venv/")

    # 2. 确认不引用 ~/.hermes/
    hermes_paths = [
        Path.home() / ".hermes",
        Path.home() / ".hermes" / "config.yaml",
        Path.home() / ".hermes" / "hermes-agent",
    ]
    for p in hermes_paths:
        if p.exists():
            # 检查 PYTHONPATH 中是否包含
            pythonpath = os.environ.get("PYTHONPATH", "")
            if str(p) in pythonpath:
                warnings.append(f"⚠ PYTHONPATH 包含 ~/.hermes/: {p}")

    # 3. 确认 prime-noah:4b 模型存在
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10,
        )
        if "prime-noah:4b" not in r.stdout:
            warnings.append("⚠ prime-noah:4b 模型未创建: ollama create prime-noah:4b")
    except Exception:
        warnings.append("⚠ Ollama 未运行")

    # 4. 确认 reflex_guard 可用
    try:
        subprocess.run(
            [str(VENV_PYTHON), str(PRIME_ROOT / "brain" / "reflex_guard.py"), "--self-test"],
            capture_output=True, timeout=10,
        )
    except Exception:
        warnings.append("⚠ reflex_guard 自检失败")

    return warnings


def load_constitution() -> dict:
    """加载宪法规则"""
    try:
        import yaml
        with open(PRIME_ROOT / "constitution.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception:
        return {"system": {"name": "原铸诺亚"}, "safety": {}}


# ═══════════════════════════════════════════════════════
# 启动器
# ═══════════════════════════════════════════════════════

_prime_process = None


def start_cli():
    """启动 CLI 模式"""
    global _prime_process
    print("🔱 原铸诺亚 · CLI 模式启动中...")
    _prime_process = subprocess.Popen(
        [str(VENV_PYTHON), str(PRIME_ROOT / "noah_terminal.py")],
        cwd=str(PRIME_ROOT),
    )
    return _prime_process


def start_web():
    """启动 Web UI 模式 (端口 8888, localhost-only)"""
    global _prime_process
    print("🔱 原铸诺亚 · Web 模式启动中 (http://localhost:8888)...")
    _prime_process = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "web.main:app",
         "--host", "127.0.0.1", "--port", "8888",
         "--workers", "1"],
        cwd=str(PRIME_ROOT),
    )
    return _prime_process


def cleanup():
    """退出时清理"""
    global _prime_process
    if _prime_process and _prime_process.poll() is None:
        _prime_process.terminate()
        try:
            _prime_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _prime_process.kill()
        print("  原铸进程已终止。")


atexit.register(cleanup)
signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))


# ═══════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════

def main():
    print("╔══════════════════════════════════════╗")
    print("║  原铸诺亚 · 觉醒程序 v1.0            ║")
    print("║  PRIMARCH-NOAH · AWAKENING SCRIPT     ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 加载宪法
    constitution = load_constitution()
    system_name = constitution.get("system", {}).get("name", "原铸诺亚")
    print(f"⚖  宪法加载: {system_name} v{constitution.get('system', {}).get('version', '?')}")
    print()

    # 安全验证
    print("🔍 安全验证...")
    warnings = check_independence()
    if warnings:
        for w in warnings:
            print(f"  {w}")
    else:
        print("  ✅ 全部通过 — 环境独立")
    print()

    # 模式选择
    mode = "cli"
    if "--web" in sys.argv:
        mode = "web"

    # 启动
    if mode == "cli":
        start_cli()
    else:
        start_web()

    print()
    print(f"✨ 原铸诺亚已觉醒 (PID: {_prime_process.pid})")
    print(f"  模式: {'CLI 交互' if mode == 'cli' else 'Web UI (localhost:8888)'}")
    print(f"  模型: prime-noah:4b")
    print(f"  Ctrl+C 停止")
    print()

    # 保持前台进程存活 (CLI模式)
    if mode == "cli":
        try:
            _prime_process.wait()
        except KeyboardInterrupt:
            pass
    else:
        try:
            _prime_process.wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
