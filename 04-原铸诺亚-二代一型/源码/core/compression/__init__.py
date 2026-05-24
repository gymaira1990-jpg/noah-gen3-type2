"""
NEP-002: 上下文压缩管线 — 统一入口

压缩等级:
    1 = L1 去噪层      — 规则引擎级降噪（去填充/重复/系统标记）
    2 = L2 摘要层      — 规则摘要 + 轮次分段策略
    3 = L3 结构化压缩  — CtxBeGone HDR / essence-log 五段式 / 任务卡
    4 = L4 向量化层    — ✅ Phase 4 (嵌入 + 本地PG pgvector)
    5 = L5 轨迹压缩    — ⏳ Phase 4 (agent 轨迹)

用法:
    from core.compression import compress

    # 去噪
    cleaned = compress(text, level=1)

    # 按轮次自动摘要
    result = compress(text, level=2, rounds=12)

    # 结构化压缩 (L3)
    card = compress(text, level=3, format='essence_log')
    order = compress(text, level=3, format='work_order')
    task = compress(text, level=3, format='task_card')
"""

from .level1_denoise import denoise, NOISE_PATTERNS
from .level2_summarize import summarize, CompressedMemory
from .level3_struct import compress as _l3_compress
from .level3_struct import estimate_token_count
from .level4_vectorize import vectorize, vectorize_pending


def compress(text: str, level: int = 1, **kwargs):
    """统一压缩入口

    Args:
        text:  原始文本
        level: 1-5 压缩等级
        **kwargs: 传给各层的参数

    Returns:
        level=1 -> str（去噪后的文本）
        level=2 -> CompressedMemory（含 summary/key_points/...）
        level=3 -> dict（结构化卡片, 格式由 format 参数指定）
        level=4 -> dict（向量化结果, 含 chunks/ok 字段）

    支持的 kwargs (level=3):
        format:  'essence_log' | 'work_order' | 'task_card' | 'auto'
        rounds:  对话轮次
        tags:    标签列表
        task_type: 任务类型

    支持的 kwargs (level=4):
        key:        条目标识 (必填)
        title_hint: 可选标题提示
        action:     'ingest' 或 'pending' (默认 'ingest')
        limit:      批量处理上限 (action='pending' 时生效)

    Raises:
        ValueError: level 未实现
    """
    if level == 1:
        return denoise(text, **kwargs)

    if level == 2:
        return summarize(text, rounds=kwargs.get('rounds', 0),
                         compress_level=kwargs.get('compress_level'))

    if level == 3:
        return _l3_compress(
            text,
            format=kwargs.get('format', 'auto'),
            rounds=kwargs.get('rounds', 0),
            tags=kwargs.get('tags'),
            task_type=kwargs.get('task_type', 'general'),
            router_result=kwargs.get('router_result'),
            **{k: v for k, v in kwargs.items()
               if k not in ('format', 'rounds', 'tags',
                            'task_type', 'router_result',
                            'compress_level')},
        )

    if level == 4:
        action = kwargs.get('action', 'ingest')
        if action == 'pending':
            return vectorize_pending(limit=kwargs.get('limit', 5))
        key = kwargs.get('key')
        if not key:
            raise ValueError("level=4 需要 key 参数")
        return vectorize(key, text, kwargs.get('title_hint', ''))

    raise ValueError(f"压缩等级 {level} 尚未实现（计划 Phase 4+）")
