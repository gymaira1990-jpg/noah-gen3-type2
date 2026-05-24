#!/usr/bin/env python3
"""密钥加载器 · vault/loader.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 纯洁印记 (Purity Seal)

配置类密钥: 从保险柜文件读取，注入环境变量
调用类密钥: 返回指针，使用时手动解析
"""

import os
import re
from pathlib import Path

# ─── 保险柜路径 ───
VAULT_BASE = Path("<vault_path>")

# ─── 密钥映射 ───
KEY_MAP = {
    "DEEPSEEK_API_KEY": {
        "class": "config",
        "vault_file": VAULT_BASE / "DEEPSEEK" / "相关信息.txt",
        "pattern": r"(sk-[a-zA-Z0-9]+)",
    },
    "DEEPSEEK_PRO_API_KEY": {
        "class": "config",
        "vault_file": VAULT_BASE / "DEEPSEEK" / "相关信息.txt",
        "pattern": None,  # 手动指定
        "line_index": 4,  # 第4行是pro key (0-indexed)
    },
    "NOAH_DOUBAO_KEY": {
        "class": "call",
        "vault_file": VAULT_BASE / "火山大模型" / "APII密钥",
        "pattern": r"(ark-[a-zA-Z0-9\-]+)",
    },
}


def load_all() -> dict:
    """加载所有密钥→环境变量，返回加载状态"""
    results = {}
    for env_var, cfg in KEY_MAP.items():
        try:
            if not cfg["vault_file"].exists():
                results[env_var] = f"❌ 保险柜文件不存在: {cfg['vault_file']}"
                continue

            content = cfg["vault_file"].read_text(encoding="utf-8")

            if cfg.get("pattern"):
                matches = re.findall(cfg["pattern"], content)
                if matches:
                    key = matches[0]
                    os.environ[env_var] = key
                    results[env_var] = f"✅ {cfg['class']}类 · 已加载 ({key[:12]}...)"
                else:
                    results[env_var] = f"❌ 模式未匹配"
            elif cfg.get("line_index") is not None:
                lines = content.strip().split("\n")
                idx = cfg["line_index"]
                if idx < len(lines):
                    key = lines[idx].strip()
                    os.environ[env_var] = key
                    results[env_var] = f"✅ {cfg['class']}类 · 已加载 ({key[:12]}...)"
                else:
                    results[env_var] = f"❌ 行索引超出范围"
        except Exception as e:
            results[env_var] = f"❌ {e}"

    return results


def get_pointer(name: str) -> str:
    """返回调用类密钥的指针路径（不加载铭文）"""
    cfg = KEY_MAP.get(name, {})
    return str(cfg.get("vault_file", "unknown"))


if __name__ == "__main__":
    status = load_all()
    for k, v in status.items():
        print(f"  {k}: {v}")
