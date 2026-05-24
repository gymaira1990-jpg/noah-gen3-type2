#!/usr/bin/env python3
"""自我迭代工具 · tools/self_modify.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · NOA-008 补充3
诺亚可以自己改自己的代码。备份→修改→测试→报告。
"""

import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from tools.registry import register, is_safe_path

PRIME_ROOT = Path(__file__).parent.parent
BACKUP_DIR = PRIME_ROOT / "backups"
CHANGELOG = PRIME_ROOT / "changelog.md"
IMMUTABLE_RULES = ["constitution.yaml", "IDENTITY.md", "roles.yaml"]
MAX_BACKUPS = 20
MAX_CONSECUTIVE_FAILURES = 3

_failure_count = 0


def self_modify(file_path: str, old_snippet: str, new_snippet: str, reason: str) -> dict:
    """诺亚修改自己的代码。安全壳内执行。"""
    path = Path(file_path)
    if not path.is_absolute():
        path = PRIME_ROOT / path

    # 安全检查
    if path.name in IMMUTABLE_RULES:
        return {"status": "blocked", "reason": f"禁止修改不可变文件: {path.name}"}
    if not is_safe_path(str(path)):
        return {"status": "blocked", "reason": f"路径不在白名单: {path}"}
    if not path.exists():
        return {"status": "blocked", "reason": f"文件不存在: {path}"}

    # ① 备份
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"{path.name}.{ts}.bak"
    shutil.copy2(path, backup_path)

    # ② 读取原文件
    original = path.read_text(encoding="utf-8")
    if old_snippet not in original:
        return {"status": "blocked", "reason": "旧代码片段未找到，无法安全替换",
                "backup": str(backup_path)}

    # ③ 执行替换
    modified = original.replace(old_snippet, new_snippet)
    path.write_text(modified, encoding="utf-8")

    # ④ 测试 (如果存在)
    test_result = _run_test(path)

    # ⑤ 变更记录
    _log_change(path.name, reason, backup_path, test_result)

    # ⑥ 失败回滚
    global _failure_count
    if not test_result.get("passed", True):
        _failure_count += 1
        shutil.copy2(backup_path, path)  # 回滚
        if _failure_count >= MAX_CONSECUTIVE_FAILURES:
            _failure_count = 0
            return {"status": "halted", "reason": f"连续失败{MAX_CONSECUTIVE_FAILURES}次，已停止",
                    "backup": str(backup_path)}
        return {"status": "rolled_back", "reason": "测试失败，已回滚",
                "test_error": test_result.get("error", ""), "backup": str(backup_path)}

    _failure_count = 0

    # ⑦ 清理旧备份
    _cleanup_old_backups()

    return {"status": "modified", "file": str(path), "backup": str(backup_path),
            "test": test_result, "note": "变更已记录到 changelog.md"}


def _run_test(path: Path) -> dict:
    """运行关联测试"""
    test_dir = PRIME_ROOT / "tests"
    test_file = test_dir / f"test_{path.stem}.py"
    if not test_file.exists():
        return {"passed": True, "note": "无关联测试"}

    try:
        r = subprocess.run(["python3", str(test_file)], capture_output=True, text=True, timeout=30)
        return {"passed": r.returncode == 0, "stdout": r.stdout[-200:], "error": r.stderr[-200:]}
    except Exception as e:
        return {"passed": False, "error": str(e)}


def _log_change(filename: str, reason: str, backup: Path, test: dict):
    entry = (
        f"| {datetime.now().strftime('%Y-%m-%d %H:%M')} | {filename} | "
        f"{reason[:50]} | {backup.name} | {'✅' if test.get('passed') else '❌'} |\n"
    )
    if not CHANGELOG.exists():
        CHANGELOG.write_text(
            "# 变更日志\n\n| 时间 | 文件 | 原因 | 备份 | 测试 |\n|------|------|------|------|------|\n"
        )
    with open(CHANGELOG, "a") as f:
        f.write(entry)


def _cleanup_old_backups():
    if not BACKUP_DIR.exists():
        return
    backups = sorted(BACKUP_DIR.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[MAX_BACKUPS:]:
        old.unlink()


register("self_modify", self_modify, "hands_right", "安全修改诺亚自身代码（备份+测试+回滚）", requires_review=True)

# ─── 测试 ───
if __name__ == "__main__":
    r = self_modify("protection.py", "# 不存在的内容", "# 新内容", "测试自修改")
    print(f"预期拦截(旧代码不存在): {r['status']}")
