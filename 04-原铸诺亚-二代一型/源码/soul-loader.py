#!/usr/bin/env python3
"""
灵魂规则加载器 · soul-loader.py

启动时强制加载 SOUL.md 到 lightweight.db + 输出概要。
每次会话第一步必须跑这个。

用法:
    python3 soul-loader.py              # 加载+输出
    python3 soul-loader.py --check       # 只检查不加载
    python3 soul-loader.py --json        # JSON输出
"""

import json, os, sys, hashlib
from pathlib import Path

# 2026-05-08 架构迁移：灵魂规则移至 Hermes 原生 Layer 1 (SOUL.md)
# 废弃路径: ~/.hermes/skills/core-identity/soul-rules/SKILL.md
# 真正文件: ~/.hermes/SOUL.md
SOUL_PATH = Path.home() / ".hermes" / "SOUL.md"
# [2026-05-12] lightweight.db 已删除，所有数据在 PostgreSQL noah_local.exact_info
# 灵魂规则直接写入 PG 而非重建 lightweight.db
import psycopg2
PG_CONFIG = {
    "host": "/var/run/postgresql",
    "dbname": "noah_local",
    "user": "gcat",
}
HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"

SOUL_SECTIONS = {
    "iron_rules": ["铁律"],
    "execution_rules": ["执行规程"],
    "reply_format": ["通信格式"],
    "report_format": ["报告规程"],
    "personality": ["机魂特质"],
    "memory_protocol": ["记忆协议"],
}


def parse_soul() -> dict:
    """解析 SOUL.md 为结构化 dict"""
    if not SOUL_PATH.exists():
        return {"error": f"SOUL.md not found at {SOUL_PATH}"}

    text = SOUL_PATH.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    sections = {}
    current_section = "header"
    current_lines = []

    for line in text.split("\n"):
        is_header = line.startswith("# ") and not line.startswith("# 🔱") and not line.startswith("# 诺亚")
        if is_header:
            if current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            # 找章节名
            for key, markers in SOUL_SECTIONS.items():
                if any(m in line for m in markers):
                    current_section = key
                    break
            else:
                current_section = line.strip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    # 统计
    stats = {
        "total_lines": len(text.split("\n")),
        "sections": list(sections.keys()),
        "hash": content_hash,
    }

    return {"sections": sections, "stats": stats, "text": text}


def persist_to_db(data: dict) -> bool:
    """写入 PG noah_local.exact_info (取代 lightweight.db)"""
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cur = conn.cursor()
        # ensure table exists
        cur.execute("""
            CREATE TABLE IF NOT EXISTS exact_info (
                key TEXT PRIMARY KEY,
                value TEXT,
                category TEXT DEFAULT 'soul',
                tags TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        for section, content in data["sections"].items():
            cur.execute(
                "INSERT INTO exact_info (key, value, category, tags, updated_at) "
                "VALUES (%s, %s, 'soul', 'soul,protected', NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (f"soul:{section}", content[:2000])
            )

        cur.execute(
            "INSERT INTO exact_info (key, value, category, tags, updated_at) "
            "VALUES (%s, %s, 'soul', 'soul,protected,fulltext', NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("soul:fulltext", data["text"][:5000])
        )

        cur.execute(
            "INSERT INTO exact_info (key, value, category, tags, updated_at) "
            "VALUES (%s, %s, 'soul', 'soul,protected,meta', NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            ("soul:meta", json.dumps(data["stats"], ensure_ascii=False))
        )

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"  ❌ 写入PG失败: {e}", file=sys.stderr)
        return False


def output_summary(data: dict, json_mode: bool = False):
    """输出摘要"""
    if json_mode:
        print(json.dumps({
            "status": "ok" if "error" not in data else "error",
            "hash": data.get("stats", {}).get("hash", "?"),
            "sections": data.get("stats", {}).get("sections", []),
            "total_lines": data.get("stats", {}).get("total_lines", 0),
        }, ensure_ascii=False))
        return

    if "error" in data:
        print(f"  ❌ {data['error']}")
        return

    s = data["stats"]
    print(f"  🧠 灵魂规则 · SOUL.md v6.0")
    print(f"  ├─ {s['total_lines']} 行 · {len(s['sections'])} 段 · hash={s['hash']}")
    print(f"  └─ 段: {', '.join(s['sections'][:8])}")
    print(f"  ✅ 已写入 PG exact_info")


def check_integrity() -> dict:
    """检查PG中的灵魂规则是否完整 (取代 lightweight.db)"""
    try:
        conn = psycopg2.connect(**PG_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "SELECT key, left(value, 60) FROM exact_info WHERE category = 'soul' ORDER BY key"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {"status": "empty", "detail": "PG exact_info 中无灵魂规则数据"}

        sections_found = [r[0].replace("soul:", "") for r in rows if r[0] != "soul:fulltext" and r[0] != "soul:meta"]
        return {"status": "ok", "sections": sections_found}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="灵魂规则加载器")
    parser.add_argument("--check", action="store_true", help="只检查不加载")
    parser.add_argument("--json", action="store_true", help="JSON输出")
    args = parser.parse_args()

    if args.check:
        result = check_integrity()
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            if result["status"] == "ok":
                print(f"  ✅ 灵魂规则完整 · {len(result['sections'])} 段")
            else:
                print(f"  ⚠ {result['detail']}")
        return

    data = parse_soul()
    if "error" in data:
        output_summary(data, args.json)
        sys.exit(1)

    ok = persist_to_db(data)
    output_summary(data, args.json)

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
