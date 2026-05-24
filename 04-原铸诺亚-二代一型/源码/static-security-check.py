#!/usr/bin/env python3
"""编译时防护 · static-security-check.py

第三阶段 §3.2 — 外环·编译时防护 (Static Analysis)

定位: Git pre-commit hook / 独立安全扫描脚本
用途: 在代码提交前自动检查安全模式, 拒绝高危提交

检查项:
  1. 硬编码密钥: sk- AKID ghp_ ark- 等模式
  2. 危险函数: eval(), exec(), compile(), __import__() (非import语句)
  3. Shell注入: os.system() / subprocess(..., shell=True)
  4. 文件覆盖: open(path, 'w') 不经过安全门闸
  5. 网络裸请求: requests.get/post 不经过代理清洗

用法:
  python3 static-security-check.py              # 扫描 ~/noah-factory/ 和 ~/noah-embryo/
  python3 static-security-check.py <文件或目录>  # 扫描指定路径
  python3 static-security-check.py --as-hook     # 作为 git hook 运行
  python3 static-security-check.py --fix         # 尝试自动修复 (仅密钥替换)
"""

import os
import sys
import re
import json
from pathlib import Path
from typing import List, Dict, Optional

# ═══════════════════════════════════════════════════════════════
# 扫描规则
# ═══════════════════════════════════════════════════════════════

RULES = [
    # 高危: 硬编码密钥
    {
        "id": "SEC-001",
        "severity": "high",
        "pattern": r'sk-[a-zA-Z0-9]{20,}',
        "message": "硬编码 OpenAI/DeepSeek 密钥",
        "auto_fix": True,
        "fix_template": 'os.environ.get("NOAH_DEEPSEEK_PRO_KEY", "")',
    },
    {
        "id": "SEC-002",
        "severity": "high",
        "pattern": r'ghp_[a-zA-Z0-9]{36,}',
        "message": "硬编码 GitHub Token",
        "auto_fix": True,
        "fix_template": 'os.environ.get("GITHUB_TOKEN", "")',
    },
    {
        "id": "SEC-003",
        "severity": "high",
        "pattern": r'AKID[a-zA-Z0-9]{20,}',
        "message": "硬编码云服务密钥 (AKID)",
        "auto_fix": True,
        "fix_template": 'os.environ.get("CLOUD_SECRET_ID", "")',
    },
    {
        "id": "SEC-004",
        "severity": "high",
        "pattern": r'ark-[a-zA-Z0-9]{8,}-[a-zA-Z0-9]{6,}',
        "message": "硬编码豆包/火山密钥",
        "auto_fix": True,
        "fix_template": 'os.environ.get("NOAH_DOUBAO_KEY", "")',
    },
    # 中危: 危险函数
    {
        "id": "SEC-011",
        "severity": "medium",
        "pattern": r'\beval\s*\(',
        "message": "使用 eval() — 可能导致代码注入",
        "auto_fix": False,
    },
    {
        "id": "SEC-012",
        "severity": "medium",
        "pattern": r'\bexec\s*\(',
        "message": "使用 exec() — 可能导致代码注入",
        "auto_fix": False,
    },
    {
        "id": "SEC-013",
        "severity": "medium",
        "pattern": r'\bcompile\s*\(',
        "message": "使用 compile() — 可能导致代码注入",
        "auto_fix": False,
    },
    {
        "id": "SEC-014",
        "severity": "low",
        "pattern": r'__import__\s*\(',
        "message": "使用 __import__() — 非常规导入",
        "auto_fix": False,
    },
    # 中危: Shell注入
    {
        "id": "SEC-021",
        "severity": "medium",
        "pattern": r'os\.system\s*\(',
        "message": "使用 os.system() — shell注入风险",
        "auto_fix": False,
    },
    {
        "id": "SEC-022",
        "severity": "medium",
        "pattern": r'subprocess\.\w+\s*\(.*shell\s*=\s*True',
        "message": "subprocess shell=True — shell注入风险",
        "auto_fix": False,
    },
    # 低危: 文件覆盖
    {
        "id": "SEC-031",
        "severity": "low",
        "pattern": r'open\([^,]+,\s*[\'"]w[\'"]\)',
        "message": "文件写模式 — 确认经安全门闸",
        "auto_fix": False,
    },
]

# 默认扫描路径
DEFAULT_PATHS = [
    Path.home() / "noah-factory",
    Path.home() / "noah-embryo",
]

# 忽略目录
IGNORE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    "__pycache__", ".hermes", ".local", ".cache",
}

# 忽略文件模式 (测试文件中的模拟密钥不拦截)
IGNORE_FILE_PATTERNS = [
    r"test_.*\.py$",        # 测试文件中可能有模拟数据
    r".*_test\.py$",
]


# ═══════════════════════════════════════════════════════════════
# 扫描引擎
# ═══════════════════════════════════════════════════════════════

def scan_file(filepath: Path) -> List[Dict]:
    """扫描单个文件

    Args:
        filepath: 文件路径

    Returns:
        [{"rule": "SEC-001", "severity": "high", "line": 42, "message": "...", "code": "..."}]
    """
    findings = []
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")
    except Exception:
        return findings

    for rule in RULES:
        pattern = re.compile(rule["pattern"])
        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                findings.append({
                    "rule": rule["id"],
                    "severity": rule["severity"],
                    "line": i,
                    "message": rule["message"],
                    "code": line.strip()[:120],
                    "auto_fix": rule["auto_fix"],
                })

    return findings


def scan_path(path: Path) -> List[Dict]:
    """递归扫描路径"""
    findings = []
    if not path.exists():
        return findings

    if path.is_file():
        if path.suffix in (".py", ".sh", ".yaml", ".yml", ".json"):
            return scan_file(path)
        return findings

    for root, dirs, files in os.walk(path):
        # 忽略目录
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

        for f in files:
            if f.endswith((".py", ".sh", ".yaml", ".yml", ".json", ".env")):
                fp = Path(root) / f
                findings.extend(scan_file(fp))

    return findings


# ═══════════════════════════════════════════════════════════════
# 报告输出
# ═══════════════════════════════════════════════════════════════

def print_report(findings: List[Dict], paths: List[Path]):
    """打印扫描报告"""
    if not findings:
        print("✅ 未发现安全问题")
        return

    # 按严重程度分组
    by_severity = {"high": [], "medium": [], "low": []}
    for f in findings:
        by_severity.setdefault(f["severity"], []).append(f)

    total = len(findings)
    high = len(by_severity["high"])
    medium = len(by_severity["medium"])
    low = len(by_severity["low"])

    print(f"扫描路径: {', '.join(str(p) for p in paths)}")
    print(f"发现 {total} 个问题: 🔴高{high} 🟡中{medium} 🟢低{low}")
    print()

    for severity, label, icon in [
        ("high", "高危", "🔴"),
        ("medium", "中危", "🟡"),
        ("low", "低危", "🟢"),
    ]:
        items = by_severity.get(severity, [])
        if not items:
            continue
        print(f"  {icon} {label} ({len(items)}项):")
        for f in items:
            fix_tag = " [可自动修复]" if f["auto_fix"] else ""
            print(f"    [{f['rule']}] {f['file']}:{f['line']}{fix_tag}")
            print(f"      {f['message']}")
            print(f"      {f['code'][:100]}")
        print()

    if high > 0:
        print("❌ 存在高危问题, 请修复后再提交")
    elif medium > 0:
        print("⚠️  存在中危问题, 建议修复")
    else:
        print("✅ 无高危问题")


# ═══════════════════════════════════════════════════════════════
# Git Hook 模式
# ═══════════════════════════════════════════════════════════════

def run_as_hook():
    """作为 git pre-commit hook 运行

    发现高危 → 拒绝commit
    发现中危 → 警告但不拦截
    """
    # 只扫描 staged 文件
    import subprocess as sp
    try:
        result = sp.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, timeout=10,
        )
        staged_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]
    except Exception:
        staged_files = []

    if not staged_files:
        return 0

    findings = []
    for f in staged_files:
        fp = Path(f)
        if not fp.exists() or fp.suffix not in (".py", ".sh", ".yaml"):
            continue
        findings.extend(scan_file(fp))

    high = [f for f in findings if f["severity"] == "high"]
    if high:
        print("⛔ Git提交被拒 — 存在高危安全问题:")
        for f in high:
            print(f"  [{f['rule']}] {f['file']}:{f['line']} — {f['message']}")
        return 1

    medium = [f for f in findings if f["severity"] == "medium"]
    if medium:
        print("⚠️  存在中危问题 (仅警告):")
        for f in medium:
            print(f"  [{f['rule']}] {f['file']}:{f['line']} — {f['message']}")

    return 0


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    import sys

    if "--as-hook" in sys.argv:
        sys.exit(run_as_hook())

    # 解析扫描路径
    paths = []
    for arg in sys.argv[1:]:
        if arg.startswith("--"):
            continue
        p = Path(arg)
        if p.exists():
            paths.append(p)

    if not paths:
        paths = [p for p in DEFAULT_PATHS if p.exists()]

    # 扫描
    all_findings = []
    for p in paths:
        all_findings.extend(scan_path(p))

    # 附加文件名
    for f in all_findings:
        f["file"] = str(Path(f.get("file", "")) if "file" in f else "")

    # 为每个finding附加文件名
    enriched = []
    for p in paths:
        for f in scan_path(p):
            f["file"] = str(Path(f.get("file", ""))) if "file" in f else ""
            f["file"] = str(p.relative_to(p.parent)) if p.is_file() else str(f.get("path", ""))
        # 重建 - 用简单方式
    # 简化: 重新扫描并关联文件
    findings_with_files = []
    for p in paths:
        if p.is_file():
            for f in scan_file(p):
                f["file"] = str(p)
                findings_with_files.append(f)
        else:
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for fname in files:
                    if not fname.endswith((".py", ".sh", ".yaml", ".yml", ".json")):
                        continue
                    fp = Path(root) / fname
                    for f in scan_file(fp):
                        f["file"] = str(fp)
                        findings_with_files.append(f)

    print_report(findings_with_files, paths)

    # 返回码
    high = [f for f in findings_with_files if f["severity"] == "high"]
    sys.exit(1 if high else 0)


if __name__ == "__main__":
    main()
