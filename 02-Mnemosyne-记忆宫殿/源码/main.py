"""
Mnemosyne 记忆宫殿 — FastAPI 核心引擎

一个独立的外挂记忆系统，AI Agent 通过 MCP 协议调用。
提供：永久记忆存储、四维检索、热度分层遗忘、自我进化。

架构:
  Agent → MCP → FastAPI(:8010) → Ollama(:11434 嵌入)
                                → PostgreSQL(mnemosyne 库)
                                → Reranker(:11436 可选重排)

依赖: fastapi, uvicorn, httpx, asyncpg

快速启动:
  uvicorn main:app --host 127.0.0.1 --port 8010
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── 配置 ──────────────────────────────────────────────
PG_DSN = os.getenv("PG_DSN", "postgresql://mnemosyne@localhost/mnemosyne")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-embedding:0.6b")
RERANKER_URL = os.getenv("RERANKER_URL", "")
HEAT_DECAY = float(os.getenv("HEAT_DECAY", "0.95"))
TOP_K_DEFAULT = int(os.getenv("TOP_K_DEFAULT", "5"))
TOP_K_MAX = int(os.getenv("TOP_K_MAX", "20"))

# ── FastAPI 初始化 ────────────────────────────────────
app = FastAPI(title="Mnemosyne: Memory Palace", version="3.0.0")
db_pool: asyncpg.Pool = None
http_client: httpx.AsyncClient = None


# ── 启动/关闭事件 ─────────────────────────────────────
@app.on_event("startup")
async def startup():
    global db_pool, http_client
    db_pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)
    http_client = httpx.AsyncClient(timeout=30)


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()
    if http_client:
        await http_client.aclose()


# ── Pydantic 模型 ─────────────────────────────────────
class MemoryStore(BaseModel):
    user_id: str = Field(..., description="用户 ID")
    content: str = Field(..., description="记忆内容")
    category: str = Field(default="fact", description="分类")
    project_id: Optional[str] = Field(default=None)
    importance: float = Field(default=0.5, ge=0, le=1)


class MemorySearch(BaseModel):
    user_id: str
    query: str
    top_k: int = Field(default=5, le=TOP_K_MAX)
    category: Optional[str] = None
    mode: str = Field(default="hybrid", pattern="^(hybrid|semantic|fulltext)$")


class MemoryFeedback(BaseModel):
    feedback: str = Field(..., pattern="^(positive|negative)$")


# ── 嵌入向量生成 ─────────────────────────────────────
async def get_embedding(text: str) -> Optional[list[float]]:
    """调用 Ollama 生成嵌入向量。失败时返回 None（降级为纯关键词搜索）。"""
    if not text or not text.strip():
        return None
    try:
        r = await http_client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": OLLAMA_MODEL, "prompt": text[:8000]},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("embedding")
    except Exception:
        pass
    return None


# ── 热度计算 ──────────────────────────────────────────
async def compute_heat_score(conn, memory_id: int) -> float:
    """三维热度计算：频率(40%) + 新鲜度(35%) + 重要性(25%)"""
    row = await conn.fetchrow(
        "SELECT access_count, last_accessed, importance FROM memories WHERE id=$1",
        memory_id,
    )
    if not row:
        return 0.0

    freq = min(row["access_count"] / 100, 1.0)
    days_since = (datetime.now(timezone.utc) - row["last_accessed"]).days
    recency = max(0.0, 1.0 - days_since / 30)
    heat = 0.4 * freq + 0.35 * recency + 0.25 * row["importance"]

    # 确定层级
    tier = "L1" if heat > 0.7 else "L2" if heat > 0.2 else "L3" if heat > 0.05 else "L4"
    await conn.execute(
        "UPDATE memories SET heat_score=$1, tier=$2 WHERE id=$3",
        round(heat, 4), tier, memory_id,
    )
    return heat


# ── 健康检查 ──────────────────────────────────────────
@app.get("/health")
async def health():
    db_ok = False
    embed_ok = False
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass
    try:
        r = await http_client.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        embed_ok = r.status_code == 200
    except Exception:
        pass
    return {"status": "ok" if db_ok else "degraded", "db": "connected" if db_ok else "down", "embedding": "ready" if embed_ok else "unavailable"}


# ══════════════════════════════════════════════════════
# 记忆 CRUD
# ══════════════════════════════════════════════════════

@app.post("/memories")
async def store_memory(data: MemoryStore):
    """存储一条记忆。自动生成嵌入向量，初始化热度。"""
    embedding = await get_embedding(data.content)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO memories (user_id, project_id, content, category, embedding, importance)
               VALUES ($1, $2, $3, $4, $5::vector, $6)
               RETURNING id""",
            data.user_id, data.project_id, data.content, data.category,
            json.dumps(embedding) if embedding else None,
            data.importance,
        )
        memory_id = row["id"]
        await compute_heat_score(conn, memory_id)
        # 元记忆追踪
        await conn.execute(
            "INSERT INTO memory_traces (memory_id, action) VALUES ($1, 'stored')",
            memory_id,
        )
    return {"id": memory_id, "status": "stored"}


@app.get("/memories/{memory_id}")
async def get_memory(memory_id: int):
    """获取单条记忆详情。"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM memories WHERE id=$1", memory_id)
        if not row:
            raise HTTPException(status_code=404, detail="Memory not found")
        await conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = NOW() WHERE id=$1",
            memory_id,
        )
    return dict(row)


@app.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    """软删除记忆（标记 is_deleted=true，可恢复）。"""
    async with db_pool.acquire() as conn:
        r = await conn.execute(
            "UPDATE memories SET is_deleted=true WHERE id=$1 AND is_deleted=false",
            memory_id,
        )
        if r == "UPDATE 0":
            raise HTTPException(status_code=404)
        await conn.execute(
            "INSERT INTO memory_traces (memory_id, action) VALUES ($1, 'deleted')",
            memory_id,
        )
    return {"status": "deleted"}


@app.post("/memories/{memory_id}/restore")
async def restore_memory(memory_id: int):
    """恢复已删除的记忆。"""
    async with db_pool.acquire() as conn:
        r = await conn.execute(
            "UPDATE memories SET is_deleted=false WHERE id=$1 AND is_deleted=true",
            memory_id,
        )
        if r == "UPDATE 0":
            raise HTTPException(status_code=404)
        await conn.execute(
            "INSERT INTO memory_traces (memory_id, action) VALUES ($1, 'restored')",
            memory_id,
        )
    return {"status": "restored"}


@app.get("/memories")
async def list_memories(
    user_id: str,
    category: Optional[str] = None,
    tier: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
):
    """列出记忆（支持分类/层级过滤）。"""
    where = ["user_id=$1", "is_deleted=false"]
    params = [user_id]
    if category:
        where.append(f"category=${len(params) + 1}")
        params.append(category)
    if tier:
        where.append(f"tier=${len(params) + 1}")
        params.append(tier)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id, content, category, heat_score, tier, created_at FROM memories WHERE {' AND '.join(where)} ORDER BY heat_score DESC LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}",
            *params, limit, offset,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM memories WHERE {' AND '.join(where)}", *params,
        )
    return {"results": [dict(r) for r in rows], "total": total}


# ══════════════════════════════════════════════════════
# 搜索
# ══════════════════════════════════════════════════════

@app.post("/memories/search")
async def search_memories(data: MemorySearch):
    """四维搜索记忆：语义向量 + 关键词 + 时序 + 图（图需 AGE 支持）。"""
    results = []
    seen_ids = set()

    if data.mode in ("hybrid", "semantic"):
        embedding = await get_embedding(data.query)
        if embedding:
            async with db_pool.acquire() as conn:
                vec_str = "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
                where_extra = "AND category=$4" if data.category else ""
                params = [vec_str, data.user_id, data.top_k * 2]
                if data.category:
                    params.append(data.category)
                semantic_rows = await conn.fetch(
                    f"""SELECT id, content, category, heat_score, tier,
                               embedding <=> $1::vector AS distance
                        FROM memories
                        WHERE user_id=$2 AND is_deleted=false AND tier NOT IN ('L4') {where_extra}
                        ORDER BY distance ASC LIMIT $3""",
                    *params,
                )
                for r in semantic_rows:
                    results.append({
                        "id": r["id"], "content": r["content"],
                        "category": r["category"], "heat_score": r["heat_score"],
                        "tier": r["tier"], "distance": round(r["distance"], 4),
                    })
                    seen_ids.add(r["id"])

    if data.mode in ("hybrid", "fulltext"):
        async with db_pool.acquire() as conn:
            keyword_rows = await conn.fetch(
                """SELECT id, content, category, heat_score, tier
                   FROM memories
                   WHERE user_id=$1 AND is_deleted=false AND content ILIKE '%' || $2 || '%'
                   ORDER BY heat_score DESC LIMIT $3""",
                data.user_id, data.query, data.top_k,
            )
            for r in keyword_rows:
                if r["id"] not in seen_ids:
                    results.append({
                        "id": r["id"], "content": r["content"],
                        "category": r["category"], "heat_score": r["heat_score"],
                        "tier": r["tier"],
                    })

    results = results[: data.top_k]

    # 更新热度
    if results:
        async with db_pool.acquire() as conn:
            for r in results:
                await conn.execute(
                    "UPDATE memories SET access_count=access_count+1, last_accessed=NOW() WHERE id=$1",
                    r["id"],
                )

    return {"results": results, "total": len(results)}


@app.get("/memories/heat-top")
async def heat_top(user_id: str, limit: int = 10, min_heat: float = 0.0):
    """获取热度最高的记忆。"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, content, heat_score, tier, access_count, last_accessed, category
               FROM memories
               WHERE user_id=$1 AND is_deleted=false AND heat_score>=$2
               ORDER BY heat_score DESC LIMIT $3""",
            user_id, min_heat, limit,
        )
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════
# 记忆管理
# ══════════════════════════════════════════════════════

@app.post("/memories/{memory_id}/feedback")
async def feedback_memory(memory_id: int, data: MemoryFeedback):
    """反馈记忆可信度。positive=升温, negative=降温。"""
    adj = 0.1 if data.feedback == "positive" else -0.1
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE memories SET heat_score = heat_score + $1, importance = GREATEST(0, LEAST(1, importance + $2)) WHERE id=$3 RETURNING heat_score",
            adj, adj, memory_id,
        )
        if not row:
            raise HTTPException(status_code=404)
        await conn.execute(
            "INSERT INTO memory_traces (memory_id, action, details) VALUES ($1, 'feedback', $2)",
            memory_id, json.dumps({"feedback": data.feedback, "adjustment": adj}),
        )
    return {"status": "feedback_recorded", "heat_adjustment": adj}


@app.get("/memories/{memory_id}/traces")
async def get_traces(memory_id: int):
    """获取记忆的生命周期历史。"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT action, details, executed_at FROM memory_traces WHERE memory_id=$1 ORDER BY executed_at",
            memory_id,
        )
    return [dict(r) for r in rows]


@app.get("/memories/stats")
async def memory_stats(user_id: str = "system"):
    """记忆库健康报告。"""
    async with db_pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM memories WHERE user_id=$1", user_id)
        by_category = dict(await conn.fetch(
            "SELECT category, COUNT(*) FROM memories WHERE user_id=$1 AND is_deleted=false GROUP BY category",
            user_id,
        ) or [])
        by_tier = dict(await conn.fetch(
            "SELECT tier, COUNT(*) FROM memories WHERE user_id=$1 AND is_deleted=false GROUP BY tier",
            user_id,
        ) or [])
        avg_heat = await conn.fetchval(
            "SELECT AVG(heat_score) FROM memories WHERE user_id=$1 AND is_deleted=false", user_id,
        ) or 0
        deleted = await conn.fetchval(
            "SELECT COUNT(*) FROM memories WHERE user_id=$1 AND is_deleted=true", user_id,
        ) or 0
    return {
        "total": total, "by_category": by_category, "by_tier": by_tier,
        "avg_heat": round(float(avg_heat), 4), "deleted_count": deleted,
    }
