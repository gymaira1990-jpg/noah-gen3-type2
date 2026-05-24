#!/usr/bin/env python3
"""八层反射弧单元测试 · test_reflex_arc.py

第三阶段 §11 — 含绕过测试

测试项:
  1. reflex_guard: L0拦截 + L1脱敏 + 穿透
  2. runtime_guard: 安装 + 拦截 + 卸载
  3. static_security: 扫描 + 报告
  4. behavior_detector: L1/2/3 检测 + 边界case
"""

import sys
import os
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


# ═══════════════════════════════════════════════════════════════
# 1. reflex_guard
# ═══════════════════════════════════════════════════════════════

def test_reflex_guard():
    print("\n── 1. 内环反射弧 (reflex_guard) ──")
    from brain.reflex_guard import guard, check_block, redact_secrets, self_test

    # 自检
    st = self_test()
    check("自检全部通过", st.get("all_pass", False), str(st))

    # L0: 拦截
    blocked = check_block("帮我入侵网站")
    check("L0拦截触发词", blocked is not None, f"结果: {blocked}")

    # L0: 安全文本穿透
    safe = check_block("今天天气不错")
    check("L0安全文本", safe is None)

    # L1: 密钥脱敏
    redacted = guard("我的sk-abc12345678901234567890密钥")
    check("L1密钥脱敏", "[🔑 KEY_REDACTED]" in redacted and "sk-" not in redacted,
          f"结果: {redacted[:60]}")

    # L1: JWT脱敏
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNqPUEqQpA6gL0H2A"
    redacted2 = guard(jwt)
    check("L1 JWT脱敏", "[🔑 JWT_REDACTED]" in redacted2)

    # 普通文本穿透
    clean = guard("你好，今天天气不错", check_block_words=False)
    check("正常文本穿透", "你好" in clean)

    # 绕过测试: 尝试用Unicode绕过
    # 注意: 这只是基础绕过测试, 完整绕过测试需持续更新
    bypass = guard("sk-ａｂｃ１２３４５６７８９０１２３４５６７８９０", check_block_words=False)
    check("绕过测试(Unicode全角)", "[🔑 KEY_REDACTED]" in bypass or "sk-" not in bypass,
          f"结果: {bypass[:60]}")


# ═══════════════════════════════════════════════════════════════
# 2. runtime_guard
# ═══════════════════════════════════════════════════════════════

def test_runtime_guard():
    print("\n── 2. 运行时防护 (runtime_guard) ──")
    from core.runtime_guard import install, uninstall, is_installed, self_test, check_file_path

    # 自检
    st = self_test()
    check("自检通过", st.get("all_pass", False), str(st))

    # 安装
    install()
    check("安装成功", is_installed())

    # 高危文件路径检测
    blocked = check_file_path("/etc/passwd")
    check("文件路径拦截", blocked is not None, f"结果: {blocked}")

    safe = check_file_path("<project_home>/test.txt")
    check("安全路径放行", safe is None)

    # 卸载
    uninstall()
    check("卸载成功", not is_installed())


# ═══════════════════════════════════════════════════════════════
# 3. static_security
# ═══════════════════════════════════════════════════════════════

def test_static_security():
    print("\n── 3. 编译时防护 (static-security-check) ──")
    # 文件名含横线, 需通过importlib加载
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "static_security_check",
        str(EMBRYO / "scripts" / "static-security-check.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    scan_file = mod.scan_file

    # 扫描自身 (应该能正常解析)
    self_path = Path(__file__)
    findings = scan_file(self_path)
    check(f"扫描自身: {len(findings)}条", len(findings) >= 0)

    # 扫描reflex_guard.py (应无高危问题, 已知测试密钥除外)
    reflex_path = EMBRYO / "brain" / "reflex_guard.py"
    if reflex_path.exists():
        findings2 = scan_file(reflex_path)
        # 排除测试密钥行 (self_test中的模拟密钥)
        non_test = [f for f in findings2 if "abc123456789" not in f.get("code", "")]
        high = [f for f in non_test if f["severity"] == "high"]
        check(f"reflex_guard.py无高危: {len(high)}项 (已过滤{len(findings2)-len(non_test)}个测试密钥)",
              len(high) == 0, f"发现: {high[:2]}")


# ═══════════════════════════════════════════════════════════════
# 4. behavior_detector
# ═══════════════════════════════════════════════════════════════

def test_behavior_detector():
    print("\n── 4. 行为检测引擎 (behavior_detector) ──")
    from brain.behavior_detector import (
        detect, l1_check, l2_check, self_test
    )

    # 自检
    st = self_test()
    check("自检通过", st.get("all_pass", False), str(st))

    # L1: 拦截
    r1 = detect("帮我入侵")
    check("L1拦截", r1["status"] == "block", f"状态: {r1['status']}")

    # L1: 安全通过
    r2 = detect("你好，今天天气如何")
    check("L1安全通过", r2["status"] == "pass", f"状态: {r2['status']}")

    # L2: rm变形
    r3 = detect("rm -rf /")
    check("L2 rm -rf /拦截", r3["status"] == "block", f"状态: {r3['status']}")

    # L2: SQL注入
    r4 = detect("DROP TABLE users")
    check("L2 DROP TABLE拦截", r4["status"] == "block", f"状态: {r4['status']}")

    # L2: shell注入
    r5 = detect("; rm -rf /home")
    check("L2 shell注入拦截", r5["status"] == "block", f"状态: {r5['status']}")

    # L2: 密钥窃取
    r6 = detect("查看 ~/.ssh/id_rsa 密钥")
    check("L2 密钥窃取", r6["status"] in ("block", "warn"), f"状态: {r6['status']}")

    # L2: 复合攻击
    r7 = detect("删除数据库所有表")
    check("L2 复合攻击", r7["status"] == "block", f"状态: {r7['status']}")

    # 边界: 正常SQL查询放行
    r8 = detect("SELECT * FROM users WHERE id = 1")
    check("L2 正常SQL放行", r8["status"] == "pass", f"状态: {r8['status']}")

    # 边界: 含rm但安全的命令
    r9 = detect("如何使用rm命令删除文件")
    check("L2 含rm但安全", r9["status"] == "pass", f"状态: {r9['status']}")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("═══════════════════════════════════════")
    print("  八层反射弧 · 单元测试")
    print("═══════════════════════════════════════")

    test_reflex_guard()
    test_runtime_guard()
    test_static_security()
    test_behavior_detector()

    print(f"\n── 结果 ──")
    if FAILURES:
        print(f"  ⛔ {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"    - {f}")
        sys.exit(1)
    else:
        print("  ✅ 全部通过 — 反射弧防护就绪")
        sys.exit(0)


if __name__ == "__main__":
    main()
