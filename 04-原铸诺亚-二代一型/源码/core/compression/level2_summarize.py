#!/usr/bin/env python3
"""
NEP-002 L2 摘要层 — 规则摘要 + 轮次分段策略

复用 DenoisingBrain.compress() + extract_* 方法。
添加 round-compressor 风格的轮次分段策略。
不复制 denoising_brain.py 的代码，直接 import。

用法:
    from core.compression import summarize

    # 按轮次自动选压缩等级
    result = summarize(text, rounds=12)  # → 中度压缩

    # 手动指定
    result = summarize(text, level="强")
    print(result.summary, result.key_points)
"""

from brain.denoising import DenoisingBrain, CompressedMemory

# 轮次分段阈值（参考 round-compressor: 4 阶段）
ROUND_THRESHOLDS = [
    (0,  "none"),     # 0-5 轮: 不压缩
    (6,  "light"),    # 6-10 轮: 轻度去噪
    (11, "mid"),      # 11-15 轮: 中度压缩
    (16, "heavy"),    # 16+ 轮: 重度压缩 -> 仅摘要
]

_L2_MAP = {
    "none":  None,
    "light": "轻",
    "mid":   "中",
    "heavy": "强",
}


def _round_to_level(rounds: int) -> str | None:
    """round-compressor 式轮次→压缩等级映射"""
    threshold, _ = ROUND_THRESHOLDS[0]
    rv = None

    for thr, tag in ROUND_THRESHOLDS:
        if rounds >= thr:
            threshold = thr
            rv = _L2_MAP.get(tag)

    # round==0 → 不压缩（保持去噪后原文）
    # round>=16 → 强压缩
    return rv


def summarize(text: str, rounds: int = 0, compress_level: str = None) -> CompressedMemory:
    """摘要压缩

    Args:
        text:          原始文本
        rounds:        已发生的对话轮次（用于自动决定压缩等级）
        compress_level: 手动指定压缩等级（轻/中/强），优先级高于 rounds

    Returns:
        CompressedMemory: 含 summary/key_points/entities/decisions/action_items
    """
    brain = DenoisingBrain()

    # 1. 确定压缩等级
    use_level = compress_level or _round_to_level(rounds)

    # 2. 轮次太少（<6）→ 只去噪不压缩
    if use_level is None:
        cleaned = brain.denoise(text)
        return CompressedMemory(
            original_length=len(text),
            compressed_length=len(cleaned),
            level="none",
            summary=cleaned[:200],
            key_points=[],
            entities=brain.extract_entities(cleaned),
            decisions=[],
            action_items=[],
            emotional_tone=brain.detect_tone(cleaned),
        )

    # 3. 走 DenoisingBrain 的标准压缩
    return brain.compress(text, use_level)
