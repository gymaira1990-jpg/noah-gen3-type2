#!/usr/bin/env python3
"""热度记忆L0层 · memory/l0_hot.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 热度四层记忆 Phase1
L0: SQLite 最近20轮完整原文 → 超出自动溢出到 L1
L1: PG knowledge_entries (现有，充当L1)
L2/L3: 后续Phase实现
"""

import sqlite3
from pathlib import Path
from datetime import datetime

PRIME_ROOT = Path(__file__).parent.parent
DB_PATH = PRIME_ROOT / "data" / "l0_hot.db"
MAX_HOT = 20  # L0热记忆容量


def init():
    """初始化L0热记忆表"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""CREATE TABLE IF NOT EXISTS hot_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_text TEXT NOT NULL,
        noah_text TEXT NOT NULL,
        ticket_id TEXT,
        created_at TEXT NOT NULL,
        protection_markers TEXT DEFAULT ''
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_hm_created ON hot_memory(created_at)")
    conn.commit()
    conn.close()


def settle(user_input: str, noah_reply: str, ticket_id: str = ""):
    """每次对话后调用——写入L0，超20轮自动溢出到L1"""
    init()

    now = datetime.now().isoformat()

    # 提取保护标记哈希
    try:
        from protection import scan
        markers = ",".join(m.hash for m in scan(user_input + noah_reply))
    except Exception:
        markers = ""

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO hot_memory (user_text, noah_text, ticket_id, created_at, protection_markers) VALUES (?,?,?,?,?)",
        (user_input[:1000], noah_reply[:2000], ticket_id, now, markers),
    )
    conn.commit()

    # 超出容量 → 最旧记录溢出到 L1 (PG)
    count = conn.execute("SELECT COUNT(*) FROM hot_memory").fetchone()[0]
    if count > MAX_HOT:
        overflow = conn.execute(
            "SELECT user_text, noah_text, ticket_id, protection_markers FROM hot_memory ORDER BY id LIMIT ?",
            (count - MAX_HOT,),
        ).fetchall()

        for row in overflow:
            try:
                from memory.pg_search import ingest
                summary = f"[L0溢出] 用户:{row[0][:200]} | 诺亚:{row[1][:200]}"
                ingest(summary, category="dialogue",
                       tags=["l1", "auto-spill", "from-L0"])
            except Exception:
                pass

        # 删除已溢出记录
        conn.execute(
            "DELETE FROM hot_memory WHERE id IN (SELECT id FROM hot_memory ORDER BY id LIMIT ?)",
            (count - MAX_HOT,),
        )
        conn.commit()

    conn.close()


def query(query_text: str, top_k: int = 5) -> list:
    """L0热记忆遍历——优先于向量检索"""
    init()

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """SELECT user_text, noah_text, ticket_id, created_at, protection_markers
           FROM hot_memory
           WHERE user_text LIKE ? OR noah_text LIKE ?
           ORDER BY id DESC LIMIT ?""",
        (f"%{query_text[:50]}%", f"%{query_text[:50]}%", top_k),
    ).fetchall()
    conn.close()

    return [
        {
            "layer": "L0",
            "user": r[0][:200],
            "noah": r[1][:200],
            "ticket_id": r[2],
            "created_at": r[3],
            "markers": r[4],
            "similarity": 0.8,  # L0精确匹配权重高
        }
        for r in rows
    ]


def stats() -> dict:
    """L0热记忆统计"""
    init()
    conn = sqlite3.connect(str(DB_PATH))
    count = conn.execute("SELECT COUNT(*) FROM hot_memory").fetchone()[0]
    oldest = conn.execute("SELECT created_at FROM hot_memory ORDER BY id LIMIT 1").fetchone()
    conn.close()
    return {
        "layer": "L0",
        "count": count,
        "capacity": MAX_HOT,
        "oldest": oldest[0] if oldest else None,
        "storage": str(DB_PATH),
    }


# ─── 启动初始化 ───
init()

# ─── 测试 ───
if __name__ == "__main__":
    init()
    print(f"L0状态: {stats()}")
    settle("测试输入", "测试回复", "TEST-L0-001")
    results = query("测试", top_k=3)
    print(f"L0查询 '测试': {len(results)}条")
    for r in results:
        print(f"  [{r['layer']}] user={r['user'][:40]}...")
