"""
Mnemosyne Reflector — 记忆反思引擎

职责: 热度衰减、冗余检测、实体提取、冲突检测
light: 每小时执行（轻量维护）
deep: 每天凌晨执行（深度学习）

调用方式:
  from reflect import light_reflect, deep_reflect
  light_reflect()  # 每小时
  deep_reflect()   # 每天
"""

import json
import os
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

PG_DSN = os.getenv("PG_DSN", "postgresql://mnemosyne@localhost/mnemosyne")
HEAT_DECAY = float(os.getenv("HEAT_DECAY", "0.95"))


def get_conn():
    """获取数据库连接。"""
    return psycopg2.connect(PG_DSN)


# ══════════════════════════════════════════════════════
# Light 反思（每小时）
# ══════════════════════════════════════════════════════

def light_reflect():
    """轻量维护：热度衰减 + 层级更新 + 软删除清理。"""
    conn = get_conn()
    cur = conn.cursor()
    start = time.time()

    # 1. 热度衰减（保护标记的条目不衰减）
    cur.execute("""
        UPDATE memories
        SET heat_score = heat_score * %s,
            tier = CASE
                WHEN heat_score * %s > 0.7 THEN 'L1'
                WHEN heat_score * %s > 0.2 THEN 'L2'
                WHEN heat_score * %s > 0.05 THEN 'L3'
                ELSE 'L4'
            END
        WHERE is_deleted = false
          AND (metadata->>'protected')::boolean IS NOT TRUE
    """, (HEAT_DECAY,) * 4)
    decayed = cur.rowcount

    # 2. 物理清理：删除超过 30 天的已删记忆
    cur.execute("""
        DELETE FROM memories
        WHERE is_deleted = true
          AND updated_at < NOW() - INTERVAL '30 days'
    """)
    purged = cur.rowcount

    conn.commit()
    elapsed = time.time() - start
    print(f"[reflector:light] decayed={decayed}, purged={purged}, took={elapsed:.2f}s")
    cur.close()
    conn.close()
    return {"mode": "light", "decayed": decayed, "purged": purged, "took_ms": int(elapsed * 1000)}


# ══════════════════════════════════════════════════════
# Deep 反思（每天凌晨）
# ══════════════════════════════════════════════════════

def deep_reflect():
    """深度学习：冗余检测 + 实体提取 + 热度重归一化。"""
    conn = get_conn()
    cur = conn.cursor()
    start = time.time()
    actions = []

    # 1. 冗余检测：余弦相似度 > 0.92 的合并
    cur.execute("""
        SELECT a.id AS id_a, b.id AS id_b, a.content AS content_a, b.content AS content_b,
               a.embedding <=> b.embedding AS sim
        FROM memories a
        JOIN memories b ON a.user_id = b.user_id AND a.category = b.category
        WHERE a.id < b.id
          AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
          AND a.is_deleted = false AND b.is_deleted = false
          AND a.embedding <=> b.embedding < 0.08
        ORDER BY sim
        LIMIT 50
    """)
    duplicates = cur.fetchall()
    merged = 0
    for id_a, id_b, content_a, content_b, sim in duplicates:
        # 保留热度的，合并内容
        cur.execute("SELECT heat_score FROM memories WHERE id=$1", (id_a,))
        heat_a = cur.fetchone()[0]
        cur.execute("SELECT heat_score FROM memories WHERE id=$1", (id_b,))
        heat_b = cur.fetchone()[0]

        keeper, dropper = (id_a, id_b) if heat_a >= heat_b else (id_b, id_a)
        cur.execute(
            "UPDATE memories SET content = content || E'\\n---\\n' || (SELECT content FROM memories WHERE id=%s) WHERE id=%s",
            (dropper, keeper),
        )
        cur.execute("UPDATE memories SET is_deleted=true WHERE id=%s", (dropper,))
        cur.execute(
            "INSERT INTO memory_traces (memory_id, action, details) VALUES (%s, 'merged', %s)",
            (keeper, json.dumps({"merged_id": dropper, "similarity": round(sim, 4)})),
        )
        merged += 1
    actions.append({"action": "dedup", "merged": merged})

    # 2. 热度全局重归一化（防止热度膨胀）
    cur.execute("""
        WITH stats AS (
            SELECT MAX(heat_score) AS max_h, MIN(heat_score) AS min_h
            FROM memories WHERE is_deleted = false
        )
        UPDATE memories
        SET heat_score = CASE
            WHEN stats.max_h = stats.min_h THEN 0.5
            ELSE (heat_score - stats.min_h) / (stats.max_h - stats.min_h)
        END
        FROM stats
        WHERE is_deleted = false
    """)
    normalized = cur.rowcount
    actions.append({"action": "renormalize", "count": normalized})

    conn.commit()
    elapsed = time.time() - start
    print(f"[reflector:deep] actions={json.dumps(actions)}, took={elapsed:.2f}s")
    cur.close()
    conn.close()
    return {"mode": "deep", "actions": actions, "took_ms": int(elapsed * 1000)}


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "light"
    if mode == "deep":
        deep_reflect()
    else:
        light_reflect()
