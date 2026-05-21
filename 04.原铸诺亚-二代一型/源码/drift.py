#!/usr/bin/env python3
"""话题漂移检测 · drift.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 遵循 NOA-006 补充5
每5轮对话检测话题是否漂移
"""

import httpx
from dataclasses import dataclass, field

OLLAMA_URL = "http://localhost:11435"
EMBED_MODEL = "qwen3-embedding:0.6b"


@dataclass
class TopicAnchor:
    topic: str = ""
    vector: list = field(default_factory=list)
    set_at_round: int = 0


class DriftDetector:
    """话题漂移检测器"""

    def __init__(self, check_every: int = 5, threshold: float = 0.4):
        self.check_every = check_every
        self.threshold = threshold
        self.anchor: TopicAnchor = TopicAnchor()
        self.current_round: int = 0
        self.drifted: bool = False

    def set_anchor(self, topic: str):
        """对话开始时设锚点"""
        vec = self._embed(topic)
        self.anchor = TopicAnchor(topic=topic, vector=vec, set_at_round=self.current_round)

    def check(self, current_text: str) -> dict:
        """检查当前轮是否漂移"""
        self.current_round += 1

        if self.current_round % self.check_every != 0:
            return {"drifted": False}

        if not self.anchor.vector:
            # 第一个检查点设为锚点
            self.set_anchor(current_text[:200])
            return {"drifted": False}

        current_vec = self._embed(current_text[:500])
        if not current_vec or not self.anchor.vector:
            return {"drifted": False}

        sim = self._cosine_similarity(self.anchor.vector, current_vec)

        if sim < self.threshold:
            self.drifted = True
            return {
                "drifted": True,
                "similarity": round(sim, 3),
                "original_topic": self.anchor.topic[:100],
                "current_round": self.current_round,
                "message": (
                    f"⚙ 审判庭提示：我们聊得有点远了。"
                    f"当前话题是「{self.anchor.topic[:60]}」，继续还是切换？"
                ),
            }

        return {"drifted": False, "similarity": round(sim, 3)}

    def reset(self, new_topic: str = ""):
        """重置锚点"""
        self.drifted = False
        if new_topic:
            self.set_anchor(new_topic)

    def _embed(self, text: str) -> list:
        try:
            r = httpx.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={"model": EMBED_MODEL, "prompt": text[:1000]},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("embedding", [])
        except Exception:
            pass
        return []

    def _cosine_similarity(self, a: list, b: list) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


# ─── 测试 ───
if __name__ == "__main__":
    d = DriftDetector()
    d.set_anchor("数据库备份方案设计")

    # 模拟5轮后话题还在
    for i in range(5):
        r = d.check(f"备份策略第{i+1}步: pg_dump noah_prime")
    print(f"话题未漂移: {r}")

    # 模拟漂移
    d2 = DriftDetector()
    d2.set_anchor("数据库备份方案设计")
    for i in range(5):
        r2 = d2.check("今晚吃什么好呢火锅还是烧烤")
    print(f"话题漂移: {r2}")
