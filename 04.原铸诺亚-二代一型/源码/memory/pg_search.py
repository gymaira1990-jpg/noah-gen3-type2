#!/usr/bin/env python3
"""PG向量语义检索 · memory/pg_search.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 沉思者阵列 (Cogitator Array)

连接: noah_prime (独立PG, 与noah_local物理隔离)
嵌入: qwen3-embedding:0.6b @ Ollama → 1024维
"""

import httpx
import json
import psycopg2
from typing import List, Optional
from pg_conn import connect, cursor, get_conn

# ─── 连接 ───
OLLAMA_URL = "http://localhost:11435"
EMBED_MODEL = "qwen3-embedding:0.6b"


def embed(text: str) -> List[float]:
    """文本→1024维向量 (Ollama qwen3-embedding)"""
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text[:8000]},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("embedding", [])
    except Exception:
        pass
    return [0.0] * 1024  # 降级零向量


def ingest(content: str, category: str = "general", tags: list = None, source: str = None) -> int:
    """摄入文本→向量化→写入knowledge_entries"""
    vec = embed(content)
    if not vec or all(v == 0 for v in vec):
        return -1

    with cursor() as cur:
        cur.execute(
            """INSERT INTO knowledge_entries (content, embedding, category, tags, source)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (content, vec, category, tags or [], source),
        )
        entry_id = cur.fetchone()[0]
    return entry_id


def search_semantic(query: str, top_k: int = 5, threshold: float = 0.50) -> list:
    """语义向量检索 · 余弦距离"""
    vec = embed(query)
    if not vec or all(v == 0 for v in vec):
        return _fallback_keyword(query, top_k)

    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT id, content, category, tags, freq, source,
           1 - (embedding <=> %s::vector) AS similarity
           FROM knowledge_entries
           WHERE embedding IS NOT NULL
           ORDER BY embedding <=> %s::vector
           LIMIT %s""",
        (vec, vec, top_k),
    )
    results = [
        {
            "id": r["id"],
            "content": r["content"][:500],
            "category": r["category"],
            "tags": r["tags"],
            "similarity": round(r["similarity"], 4),
            "source": r["source"],
        }
        for r in cur.fetchall()
        if r["similarity"] >= threshold
    ]
    cur.close()
    conn.close()

    # 热度回升
    if results:
        _bump_freq([r["id"] for r in results])
        return results

    # 双轨回退: 向量未命中→jsonl原始记录
    try:
        from memory.jsonl_fallback import search_chat_logs
        fallback = search_chat_logs(query, days_back=7, top_k=top_k)
        if fallback:
            return fallback
    except Exception:
        pass

    return results


def _bump_freq(ids: list):
    """命中检索→热度+1"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE knowledge_entries SET freq = freq + 1 WHERE id = ANY(%s)",
            (ids,),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def _fallback_keyword(query: str, top_k: int = 5) -> list:
    """嵌入不可用→关键词降级检索"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """SELECT id, content, category, tags, freq, source
           FROM knowledge_entries
           WHERE content ILIKE %s
           ORDER BY freq DESC
           LIMIT %s""",
        (f"%{query[:50]}%", top_k),
    )
    results = [
        {
            "id": r["id"],
            "content": r["content"][:500],
            "category": r["category"],
            "tags": r["tags"],
            "similarity": 0.0,
            "source": r["source"],
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return results


def stats() -> dict:
    """沉思者阵列状态"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT count(*), count(embedding) FROM knowledge_entries")
    total, with_vec = cur.fetchone()
    cur.execute("SELECT category, count(*) FROM knowledge_entries GROUP BY category ORDER BY 2 DESC")
    cats = dict(cur.fetchall())
    cur.close()
    conn.close()
    return {
        "total_entries": total,
        "with_vectors": with_vec,
        "by_category": cats,
        "embed_model": EMBED_MODEL,
    }


# ─── 测试 ───
if __name__ == "__main__":
    print("沉思者阵列状态:", json.dumps(stats(), ensure_ascii=False, indent=2))

    # 摄入测试
    test_id = ingest("[NOAH-PRIME] 万机之神见证——铸造世界初始化完成。", category="system", tags=["prime", "init"])
    print(f"\n摄入测试: id={test_id}")

    # 语义检索测试
    results = search_semantic("铸造世界初始化", top_k=3)
    print(f"\n语义检索 '铸造世界初始化': {len(results)}条")
    for r in results:
        print(f"  [{r['similarity']}] {r['content'][:80]}...")
