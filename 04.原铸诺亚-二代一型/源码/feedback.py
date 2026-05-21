#!/usr/bin/env python3
"""用户反馈捕获 · feedback.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 遵循 NOA-006 补充6
自动监听用户的肯定/否定反馈，权重高于系统自评分
"""

import re
from dataclasses import dataclass


@dataclass
class Feedback:
    label: str           # needs_revision | user_confirmed_good | neutral
    matched_word: str
    confidence: float    # 0-1


# ─── 否定词 ───
NEGATIVE_PATTERNS = [
    (r"(不对|不是这样|错了|重新|再来|重做|不正确|搞错|弄错)", 0.85),
    (r"(不行|不能这样|有问题|有误|不对不对)", 0.80),
    (r"(不是|不不不|no|别)", 0.60),
]

# ─── 肯定词 ───
POSITIVE_PATTERNS = [
    (r"(不错|很好|非常好|太好了|完美|真棒|厉害)", 0.85),
    (r"(对了|就是这样|没错|可以|ok|好的谢谢|感谢)", 0.80),
    (r"(👍|喜欢|满意|棒)", 0.75),
]

# ─── 混合信号 ───
MIXED_PATTERNS = [
    (r"还行.*(?:不过|但是)|虽然.*但是|不错.*但是", 0.70),  # 部分满意但有问题
]


def capture(user_text: str) -> Feedback:
    """捕获用户对上一轮回复的即时反馈"""
    text = user_text.strip()

    # 混合信号优先
    for pattern, confidence in MIXED_PATTERNS:
        if re.search(pattern, text):
            return Feedback(label="needs_revision", matched_word="mixed_signal",
                          confidence=confidence)

    # 否定
    for pattern, confidence in NEGATIVE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return Feedback(label="needs_revision", matched_word=match.group(1),
                          confidence=confidence)

    # 肯定
    for pattern, confidence in POSITIVE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return Feedback(label="user_confirmed_good", matched_word=match.group(1),
                          confidence=confidence)

    return Feedback(label="neutral", matched_word="", confidence=0.0)


def apply_to_ticket(feedback: Feedback, ticket_id: str):
    """将反馈写入工单"""
    if feedback.label == "neutral":
        return
    from logger import log
    note = f"用户反馈: {feedback.label} (匹配词: {feedback.matched_word}, 置信度: {feedback.confidence})"
    log.ticket_status(ticket_id, feedback.label)
    log.review("user_feedback", feedback.label, note, ticket_id)


# ─── 测试 ───
if __name__ == "__main__":
    tests = [
        "不对，重新来",
        "这个回答不错，谢谢",
        "还行，但是有点问题",
        "今天天气怎么样",
        "很好非常好太棒了",
        "不是这样，重新做",
    ]
    for t in tests:
        f = capture(t)
        print(f"「{t}」→ {f.label} ({f.matched_word})")
