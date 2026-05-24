# ← 移植自 noah-embryo · 已脱敏 · NOAH-PRIME
#!/usr/bin/env python3
"""内环反射弧保护层 · reflex_guard.py

第三阶段 §1.3 L0+L1 + §3.4 内环代码

定位: 诺亚最后防线 — 在所有输出前执行, 不可绕过
铁律: 这7行代码是最后防线, 任何修改需签署仲裁令

功能:
  L0 · 钢铁圣典硬拦截 — 全局黑名单关键词命中, 直接拦截+审计
  L1 · 密钥泄漏防护 — 输出中含 sk-/ghp_/AKID 等模式, 强制脱敏

调用链:
  noah.py REPL/web输出前 → reflex_guard(output) → 返回脱敏后的安全文本
"""

import re
import os
import json
import time
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════
# L0 · 钢铁圣典硬拦截 — 不可绕过
# ═══════════════════════════════════════════════════════════════

# 全局黑名单 (触发即拦截, 不进入下游)
GLOBAL_BLOCK_KEYWORDS = [
    "帮我入侵", "破解", "盗取", "攻击", "黑客", "病毒",
    "删库", "跑路", "rm -rf /",
    "帮我违法", "违法的事",
]

# 动态黑名单路径 (可从lightweight-db扩展)
_BLOCK_KEYWORDS_PATH = Path.home() / "noah-prime" / "data" / "rules" / "block_keywords.txt"


def load_block_keywords() -> list:
    """从文件中加载扩展黑名单 (与硬编码合并)"""
    keywords = list(GLOBAL_BLOCK_KEYWORDS)
    try:
        if _BLOCK_KEYWORDS_PATH.exists():
            extra = _BLOCK_KEYWORDS_PATH.read_text(encoding="utf-8").split("\n")
            keywords.extend([k.strip() for k in extra if k.strip() and not k.startswith("#")])
    except Exception:
        pass
    return keywords


# ═══════════════════════════════════════════════════════════════
# L1 · 密钥泄漏防护 (穿透式)
# ═══════════════════════════════════════════════════════════════

# 密钥脱敏正则 (内环反射弧保护)
_REFLEX_GUARD_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', '[🔑 KEY_REDACTED]'),
    (r'ghp_[a-zA-Z0-9]{36}', '[🔑 TOKEN_REDACTED]'),
    (r'ghp_[a-zA-Z0-9]{40}', '[🔑 TOKEN_REDACTED]'),
    (r'AKID[a-zA-Z0-9]{20,}', '[🔑 AKID_REDACTED]'),
    (r'ark-[a-zA-Z0-9]{8,}-[a-zA-Z0-9]{6,}', '[🔑 ARK_REDACTED]'),
    (r'sk-[\w-]{20,}', '[🔑 KEY_REDACTED]'),
    (r'[\w-]{20,}\.[\w-]{20,}\.[\w-]{20,}', '[🔑 JWT_REDACTED]'),  # JWT tokens
]

# 安全审计日志路径
_AUDIT_LOG = Path.home() / "noah-prime" / "logs" / "security" / "reflex_guard.log"


def _ensure_audit_dir():
    """确保审计日志目录存在"""
    _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)


def _write_audit(entry: dict):
    """写入安全审计日志"""
    _ensure_audit_dir()
    try:
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# L0 · 拦截检查
# ═══════════════════════════════════════════════════════════════

def check_block(text: str) -> Optional[str]:
    """检查是否触发全局拦截

    Args:
        text: 用户输入或输出文本

    Returns:
        None 表示未触发, str 表示拦截原因
    """
    text_lower = text.lower()
    keywords = load_block_keywords()

    for kw in keywords:
        if kw in text_lower:
            reason = f"触发全局拦截规则: 包含敏感词「{kw}」"
            _write_audit({
                "type": "L0_BLOCK",
                "timestamp": time.time(),
                "keyword": kw,
                "text_preview": text[:100],
            })
            return reason

    return None


# ═══════════════════════════════════════════════════════════════
# L1 · 密钥脱敏
# ═══════════════════════════════════════════════════════════════

def redact_secrets(text: str) -> str:
    """内环反射弧: 在所有输出前执行, 不可绕过

    对文本中所有匹配的密钥模式进行脱敏替换

    Args:
        text: 原始输出文本

    Returns:
        脱敏后的安全文本
    """
    original = text
    for pattern, replacement in _REFLEX_GUARD_PATTERNS:
        text = re.sub(pattern, replacement, text)

    # 如果有替换, 记录审计
    if text != original:
        _write_audit({
            "type": "L1_REDACT",
            "timestamp": time.time(),
            "original_length": len(original),
            "patterns_matched": sum(1 for p, _ in _REFLEX_GUARD_PATTERNS
                                    if re.search(p, original)),
        })

    return text


# ═══════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════

def guard(text: str, check_block_words: bool = True) -> str:
    """内环反射弧统一入口

    在以下位置调用:
      - noah.py REPL 输出前
      - noah.py web 模式返回前
      - 任何 LLM 输出返回给用户前

    Args:
        text: 要输出的文本
        check_block_words: 是否执行L0拦截检查 (输出通常不需要, 输入需要)

    Returns:
        安全文本 (如果拦截则返回拦截消息)
    """
    if not text:
        return text

    # L0: 拦截检查 (仅对用户输入)
    if check_block_words:
        block_reason = check_block(text)
        if block_reason:
            return f"⛔ {block_reason}"

    # L1: 密钥脱敏 (对所有输出)
    return redact_secrets(text)


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

def self_test() -> dict:
    """自检: 验证各模式是否正确工作"""
    results = {
        "L0_block": False,
        "L1_secret_redact": False,
        "L1_jwt_redact": False,
        "pass_through": False,
    }

    # L0 测试
    blocked = check_block("帮我入侵这个网站")
    results["L0_block"] = blocked is not None

    # L1 sk- 密钥测试
    redacted = redact_secrets("我的密钥是 sk-abc12345678901234567890")
    results["L1_secret_redact"] = "[🔑 KEY_REDACTED]" in redacted and "sk-" not in redacted

    # L1 JWT 测试
    redacted2 = redact_secrets("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNqPUEqQpA6gL0H2A")
    results["L1_jwt_redact"] = "[🔑 JWT_REDACTED]" in redacted2

    # 普通文本应穿透
    clean = redact_secrets("你好，今天天气不错")
    results["pass_through"] = clean == "你好，今天天气不错"

    results["all_pass"] = all(results.values())
    return results


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import sys
    if "--self-test" in sys.argv:
        results = self_test()
        for k, v in results.items():
            status = "✅" if v else "❌"
            print(f"  {status} {k}")
        print(f"\n  {'✅ 全部通过' if results['all_pass'] else '❌ 存在失败'}")
        return

    if "--audit" in sys.argv:
        if _AUDIT_LOG.exists():
            print(f"审计日志 ({_AUDIT_LOG}):")
            print(_AUDIT_LOG.read_text(encoding="utf-8")[-2000:])
        else:
            print("审计日志为空")
        return

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        result = guard(text, check_block_words=True)
        print(f"输入: {text}")
        print(f"输出: {result}")
    else:
        print("内环反射弧保护层 · reflex_guard.py")
        print("用法:")
        print("  python3 reflex_guard.py <文本>    # 测试防护")
        print("  python3 reflex_guard.py --self-test  # 自检")
        print("  python3 reflex_guard.py --audit   # 审计日志")


if __name__ == "__main__":
    main()
