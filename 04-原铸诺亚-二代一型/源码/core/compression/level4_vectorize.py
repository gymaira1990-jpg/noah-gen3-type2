#!/usr/bin/env python3
"""
NEP-002 L4 向量化层 — 去噪→切片→嵌入→写入本地 PG pgvector

复用 DenoisingBrain.ingest_to_l2() 和 ingest_pending()。
不复制代码，直接 import。

用法:
    from core.compression.level4_vectorize import vectorize
    result = vectorize("key", "text", "title")
    result = vectorize_pending(limit=5)
"""

from brain.denoising import DenoisingBrain


def vectorize(key: str, text: str, title_hint: str = "") -> dict:
    """向量化入口 — 去噪→切片→嵌入→写入本地 PG knowledge_entries

    Args:
        key:        条目标识，如 "chat-1746615000"
        text:       原始文本内容
        title_hint: 可选标题提示

    Returns:
        dict: {"chunks": int, "ok": bool, "error": str?}
    """
    brain = DenoisingBrain()
    return brain.ingest_to_l2(key, text, title_hint)


def vectorize_pending(limit: int = 5) -> dict:
    """批量处理待向量化条目（扫描 L1 lightweight.db 标记 pending_vectorize）

    Args:
        limit: 最大处理条数

    Returns:
        dict: {"status": str, "processed": int, "total_chunks": int, "results": [...]}
    """
    brain = DenoisingBrain()
    return brain.ingest_pending(limit)
