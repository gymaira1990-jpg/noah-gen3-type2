"""
context-assembler — 抽屉级联压缩引擎 Tier 3: 上下文组装器

职责:
  - 从 Tier1(抽屉) + Tier2(记忆管家) 读取输出
  - 向量搜索相关历史条目(knowledge_entries)
  - 组装为精炼上下文(< 13K tok/次)

位置: compress() 返回前, 替换原始 context_str
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ≈ tok 数估算(中英文混合: 1.5 char/tok)
_CHAR_PER_TOK = 1.5

# ── 默认配置 ──
ASSEMBLER_CONFIG = {
    "max_tokens": 13000,          # 上限 13K tok
    "reserve_tokens": 2000,       # 预留空间(给后续 session context)
    "vec_search_top_k": 5,        # 向量搜索返回条数
    "pg_conn": "psql -U <user> -d noah_local -t -A",
}


def _char_to_tok(text: str) -> int:
    return int(len(text) / _CHAR_PER_TOK)


def _pg_exec(sql: str) -> List[Dict[str, Any]]:
    """执行 SQL 查询, 返回 dict 列表。"""
    cmd = f"{ASSEMBLER_CONFIG['pg_conn']} -c \"\"\"{sql}\"\"\""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            logger.error("[assembler] pg error: %s", result.stderr[:200])
            return []
        rows = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    rows.append({"raw": line})
        return rows
    except Exception as e:
        logger.error("[assembler] pg exception: %s", e)
        return []


def _vec_search(query: str, top_k: int = 5) -> List[Dict]:
    """向量搜索 knowledge_entries, 找最相关条目。

    使用 PG pgvector (1024d, cosine) 的相似度搜索。
    先通过 Ollama qwen3-embedding:0.6b 生成查询向量,
    再 PG 内 ANN 搜索。
    """
    # 清理查询: 摘 key tokens 提升匹配率
    clean_query = query.strip()[:500]
    if not clean_query:
        return []

    # 1. 生成查询向量 (调用 qwen3-embedding:0.6b via Ollama)
    vec = _get_embedding(clean_query)
    if not vec or len(vec) < 100:
        # 退化为全文搜索
        return _ft_search(clean_query, top_k)

    # 2. 向量搜索 (cosine distance, pgvector <=>)
    vec_str = "[" + ",".join(f"{v:.8f}" for v in vec) + "]"
    sql = f"""
    SELECT id, title, left(content, 500) as snippet, category,
           tags, embedding <=> '{vec_str}'::vector as dist
    FROM knowledge_entries
    WHERE embedding IS NOT NULL
    ORDER BY dist ASC
    LIMIT {top_k * 2};
    """
    vec_rows = _pg_exec(sql)
    entries = []
    seen_ids = set()
    for r in vec_rows:
        eid = r.get("id")
        if eid and eid not in seen_ids:
            seen_ids.add(eid)
            entries.append(r)

    # 3. 填充不足结果 (全文备份)
    if len(entries) < top_k:
        ft_entries = _ft_search(clean_query, top_k - len(entries) + 1)
        for r in ft_entries:
            eid = r.get("id")
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                entries.append(r)

    return entries[:top_k]


def _get_embedding(text: str) -> Optional[List[float]]:
    """调用 Ollama qwen3-embedding:0.6b 生成向量 (1024d)。"""
    url = os.getenv("OLLAMA_EMBED_URL", "http://127.0.0.1:13634/api/embed")
    try:
        import httpx
        r = httpx.post(
            url,
            json={"model": "qwen3-embedding:0.6b", "prompt": text[:8000]},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            emb = data.get("embedding", [])
            if emb:
                return emb
        logger.warning("[assembler] embed failed: %s %s", r.status_code, r.text[:100])
    except Exception as e:
        logger.warning("[assembler] embed exception: %s", e)
    return None


def _ft_search(query: str, limit: int = 5) -> List[Dict]:
    """纯全文搜索 (ILIKE) — 向量退化的降级路径。"""
    clean = query.replace("'", "''")
    sql = f"""
    SELECT id, title, left(content, 500) as snippet, category, tags
    FROM knowledge_entries
    WHERE content ILIKE '%{clean}%'
       OR title ILIKE '%{clean}%'
    ORDER BY updated_at DESC
    LIMIT {limit * 2};
    """
    return _pg_exec(sql)


def _fetch_active_summaries(limit: int = 10) -> List[Dict]:
    """获取最新的渐进摘要条目。"""
    sql = f"""
    SELECT id, title, left(content, 800) as content, category, tags
    FROM knowledge_entries
    WHERE tags @> ARRAY['incremental_summary']
       OR category = 'project_progress'
    ORDER BY updated_at DESC
    LIMIT {limit};
    """
    return _pg_exec(sql)


def _fetch_recent_exec_logs(limit: int = 5) -> List[Dict]:
    """获取最近的执行日志。"""
    sql = f"""
    SELECT id, title, left(content, 500) as content, category, tags
    FROM knowledge_entries
    WHERE tags @> ARRAY['execution_log']
    ORDER BY updated_at DESC
    LIMIT {limit};
    """
    return _pg_exec(sql)


# ==============================================================
# 组装核心
# ==============================================================

# 全局性能指标
_ASSEMBLER_PERF = {
    "calls": 0,
    "total_duration_ms": 0,
    "avg_duration_ms": 0.0,
    "last_duration_ms": 0,
    "vec_searches": 0,
    "vec_search_fail": 0,
    "total_tokens_produced": 0,
    "avg_tokens": 0.0,
    "sections_avg": 0.0,
}


def get_assembler_stats() -> Dict:
    """返回组装器性能指标快照。"""
    return dict(_ASSEMBLER_PERF)


def reset_assembler_stats() -> None:
    """重置性能指标。"""
    _ASSEMBLER_PERF.update({
        "calls": 0,
        "total_duration_ms": 0,
        "avg_duration_ms": 0.0,
        "last_duration_ms": 0,
        "vec_searches": 0,
        "vec_search_fail": 0,
        "total_tokens_produced": 0,
        "avg_tokens": 0.0,
        "sections_avg": 0.0,
    })

def assemble_context(
    drawer_items: List[Dict],
    user_message: str = "",
    project_refs: Optional[List[str]] = None,
) -> str:
    """组装精炼上下文。

    Args:
        drawer_items: Tier1 抽屉条目
        user_message: 当前用户消息
        project_refs: 关联项目引用(TFC/NCP/PRJ 编号)

    Returns:
        精炼上下文字符串 (< max_tokens tok)
    """
    _t0 = time.monotonic()
    max_tok = ASSEMBLER_CONFIG["max_tokens"] - ASSEMBLER_CONFIG["reserve_tokens"]
    sections = []
    tok_budget = max_tok

    # 顶层: 目标声明
    goal_text = "目标: 保持对话连续性 + 项目进展追踪 + 关联历史知识。\n"
    sections.append(goal_text)
    tok_budget -= _char_to_tok(goal_text)

    # Section A: 抽屉关键内容(Tier1)
    if drawer_items and tok_budget > 0:
        a_parts = []
        for item in drawer_items:
            content = str(item.get("content", ""))
            level = item.get("level", 0)
            # 只取高层次(重要)条目
            if level >= 1 and content:
                snippet = content[:400]
                a_parts.append(f"[L{level}] {snippet}")
        if a_parts:
            a_text = "── Tier1 抽屉 ──\n" + "\n".join(a_parts[:8])
            if _char_to_tok(a_text) <= tok_budget:
                sections.append(a_text)
                tok_budget -= _char_to_tok(a_text)

    # Section B: 活跃摘要(Tier2)
    if tok_budget > 0:
        summaries = _fetch_active_summaries(limit=8)
        if summaries:
            b_parts = []
            for s in summaries:
                title = s.get("title", "")
                snippet = s.get("content", "")[:300]
                if snippet:
                    b_parts.append(f"[{title}] {snippet}")
            if b_parts:
                b_text = "── Tier2 记忆: 项目摘要 ──\n" + "\n".join(b_parts[:5])
                if _char_to_tok(b_text) <= tok_budget:
                    sections.append(b_text)
                    tok_budget -= _char_to_tok(b_text)

    # Section C: 向量搜索(相关历史)
    if tok_budget > 0 and user_message:
        query = user_message[:300]
        if project_refs:
            query = f"{query} {' '.join(project_refs)}"
        vec_results = _vec_search(query)
        if vec_results:
            _ASSEMBLER_PERF["vec_searches"] += 1
        else:
            _ASSEMBLER_PERF["vec_search_fail"] += 1
        if vec_results:
            c_parts = []
            for r in vec_results:
                title = r.get("title", "")
                snippet = r.get("snippet", "")[:250]
                if snippet:
                    c_parts.append(f"[{title}] {snippet}")
            if c_parts:
                c_text = "── 相关历史知识 ──\n" + "\n".join(c_parts[:3])
                if _char_to_tok(c_text) <= tok_budget:
                    sections.append(c_text)
                    tok_budget -= _char_to_tok(c_text)

    # Section D: 近期执行日志
    if tok_budget > 0:
        exec_logs = _fetch_recent_exec_logs(limit=3)
        if exec_logs:
            d_parts = []
            for e in exec_logs:
                snippet = e.get("content", "")[:200]
                if snippet:
                    d_parts.append(f"[{e.get('title','')}] {snippet}")
            if d_parts:
                d_text = "── 执行日志 ──\n" + "\n".join(d_parts[:2])
                if _char_to_tok(d_text) <= tok_budget:
                    sections.append(d_text)
                    tok_budget -= _char_to_tok(d_text)

    result = "\n\n".join(sections)
    actual_tok = _char_to_tok(result)
    logger.info(
        "[assembler] assembled %d tok (%d sections, budget=%d)",
        actual_tok, len(sections), max_tok,
    )

    _dur_total = (time.monotonic() - _t0) * 1000
    _ASSEMBLER_PERF["calls"] += 1
    _ASSEMBLER_PERF["total_duration_ms"] += int(_dur_total)
    _ASSEMBLER_PERF["last_duration_ms"] = int(_dur_total)
    _ASSEMBLER_PERF["avg_duration_ms"] = (
        _ASSEMBLER_PERF["total_duration_ms"] / _ASSEMBLER_PERF["calls"]
    )
    _ASSEMBLER_PERF["total_tokens_produced"] += actual_tok
    _ASSEMBLER_PERF["avg_tokens"] = (
        _ASSEMBLER_PERF["total_tokens_produced"] / _ASSEMBLER_PERF["calls"]
    )
    _ASSEMBLER_PERF["sections_avg"] = (
        (_ASSEMBLER_PERF.get("sections_avg", 0) * (_ASSEMBLER_PERF["calls"] - 1) + len(sections))
        / _ASSEMBLER_PERF["calls"]
    )

    logger.debug(
        "[assembler] perf: %dms, %d tok, %d sections",
        int(_dur_total), actual_tok, len(sections),
    )

    return result


def reload_config() -> None:
    """从 config.yaml 重载配置。"""
    try:
        import yaml
        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            sc = cfg.get("assembler", {})
            if sc:
                for k in ASSEMBLER_CONFIG:
                    if k in sc:
                        ASSEMBLER_CONFIG[k] = sc[k]
    except Exception as e:
        logger.warning("[assembler] reload_config failed: %s", e)
