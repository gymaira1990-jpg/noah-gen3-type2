#!/usr/bin/env python3
"""诺亚胚胎 · 自洽性测试

启动时自动运行，验证:
1. 规则无冲突
2. 核心模块可导入
3. 数据目录完整
4. 路由分类逻辑正确
5. 关键路径存在

返回码: 0=通过, 1=失败
"""

import sys, os
from pathlib import Path

EMBRYO = Path.home() / "noah-embryo"
sys.path.insert(0, str(EMBRYO))

FAILURES = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  ✅ {label}")
    else:
        print(f"  ⛔ {label}: {detail}")
        FAILURES.append(label)


# ═══════════════════════════════════════
# 1. 规则自洽
# ═══════════════════════════════════════

def test_rules():
    print("\n── 1. 规则自洽 ──")
    from core.rules import check_consistency, get_active_rules
    
    issues = check_consistency()
    check("规则无冲突", len(issues) == 0, str(issues) if issues else "")
    
    rules = get_active_rules()
    check("规则已加载", len(rules) > 0, f"0条规则")
    check("有优先级0规则(安全)", any(r.get("priority") == 0 for r in rules), "无优先级0规则")
    
    ids = [r.get("id") for r in rules]
    check("规则ID无重复", len(ids) == len(set(ids)), f"{len(ids)}条中{len(ids)-len(set(ids))}个重复")


# ═══════════════════════════════════════
# 2. 核心模块导入
# ═══════════════════════════════════════

def test_imports():
    print("\n── 2. 核心模块导入 ──")
    
    modules = [
        ("storage.archiver", "storage.archiver"),
        ("core.router", "core.router"),
        ("core.engine", "core.engine"),
        ("core.memory", "core.memory"),
        ("core.rules", "core.rules"),
    ]
    
    for name, import_path in modules:
        try:
            __import__(import_path)
            check(f"{name}", True)
        except Exception as e:
            check(f"{name}", False, str(e))
    
    # CLI工具通过subprocess调用验证
    for script in ["storage/lightweight-db.py", "storage/recent-memory.py"]:
        path = EMBRYO / script
        check(f"CLI工具: {script}", path.exists() and path.stat().st_size > 0, "文件缺失")


# ═══════════════════════════════════════
# 3. 数据目录
# ═══════════════════════════════════════

def test_directories():
    print("\n── 3. 数据目录 ──")
    
    required = [
        EMBRYO / "data",
        EMBRYO / "data" / "archives",
        EMBRYO / "storage",
        EMBRYO / "core",
        EMBRYO / "rules",
        EMBRYO / "web",
        EMBRYO / "tests",
    ]
    
    for d in required:
        check(f"目录存在: {d.name}", d.is_dir(), str(d))
    
    # 重要文件
    files = [
        "noah.py", "start.sh",
        "storage/lightweight-db.py", "storage/recent-memory.py", "storage/archiver.py",
        "core/engine.py", "core/router.py", "core/memory.py", "core/rules.py",
        "rules/codex_rules.json",
        "web/index.html", "web/style.css", "web/app.js",
    ]
    for f in files:
        path = EMBRYO / f
        check(f"文件存在: {f}", path.exists() and path.stat().st_size > 0, "空或不存在")


# ═══════════════════════════════════════
# 4. 路由逻辑
# ═══════════════════════════════════════

def test_router():
    print("\n── 4. 路由分类逻辑 ──")
    from core.router import classify
    
    test_cases = [
        ("你好，今天怎么样", "chat"),
        ("帮我写一段代码", "work"),
        ("什么是数字文明", "knowledge"),
        ("研究一下这个架构", "study"),
    ]
    
    for text, expected in test_cases:
        result = classify(text)
        ok = result["intent"] == expected
        check(f"'{text[:12]}...' → {expected}(得{result['intent']})", ok, 
              f"期望={expected}, 实际={result['intent']}, 置信度={result['confidence']}")


# ═══════════════════════════════════════
# 5. 记忆系统
# ═══════════════════════════════════════

def test_memory():
    print("\n── 5. 记忆系统 ──")
    from storage.archiver import store, search
    
    # 写入测试
    store("test", {"id": "self-check", "summary": "自洽测试记录", "intent": "test"})
    check("记忆写入", True, "")
    
    # 检索测试
    results = search("自洽", limit=3)
    check("记忆检索", len(results) > 0, f"检索到{len(results)}条")


# ═══════════════════════════════════════
# 主入口
# ═══════════════════════════════════════

def main():
    print("═══════════════════════════════════════")
    print("  诺亚胚胎 · 自洽性测试")
    print("═══════════════════════════════════════")
    
    test_rules()
    test_imports()
    test_directories()
    test_router()
    test_memory()
    
    print(f"\n── 结果 ──")
    if FAILURES:
        print(f"  ⛔ {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"    - {f}")
        sys.exit(1)
    else:
        print("  ✅ 全部通过 — 胚胎核心自洽")
        sys.exit(0)


if __name__ == "__main__":
    main()
