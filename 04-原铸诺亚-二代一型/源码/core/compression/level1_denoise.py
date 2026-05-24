#!/usr/bin/env python3
"""
NEP-002 L1 去噪层 — 规则引擎级降噪

复用 DenoisingBrain._denoise() 的 NOISE_PATTERNS 规则。
不复制代码，直接 import。添加 round-compressor 风格的轮次分段策略。

用法:
    from core.compression import denoise
    cleaned = denoise(text)          # 轻度去噪
    cleaned = denoise(text, aggress)  # 重度去噪
"""

import re
from brain.denoising import NOISE_PATTERNS

# 额外激进去噪规则（aggressive=True 时生效）
AGGRESSIVE_PATTERNS = [
    (r' {3,}', '多处空格'),
    (r'[!！]{2,}', '重复感叹'),
    (r'[?？]{2,}', '重复问号'),
]


def denoise(text: str, aggressive: bool = False) -> str:
    """规则降噪 — 默认轻度

    Args:
        text: 原始文本
        aggressive: True=额外去除系统标记/重复空格/重复标点

    Returns:
        str: 去噪后的纯净文本
    """
    if not text or not text.strip():
        return text.strip() if text else ""

    cleaned = text.strip()

    # 去填充词 / 重复确认 / 系统标记（复用 DenoisingBrain 规则）
    for pattern, _ in NOISE_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned)

    # 去多余换行（>=3 → 2）
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

    if aggressive:
        for pattern, _ in AGGRESSIVE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned)

    return cleaned.strip()
