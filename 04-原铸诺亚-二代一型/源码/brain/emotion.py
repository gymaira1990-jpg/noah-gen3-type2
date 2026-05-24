# ← 移植自 noah-embryo · 已脱敏 · NOAH-PRIME
#!/usr/bin/env python3
"""
小诺亚·情感脑 — 反问 + 价值判断 + 个性化人格

核心能力:
  1. 反问: 在不确定时向用户提问，表达怀疑
  2. 动态心疼: 感知资源消耗，判断"是否适合"而非"是否可行"
  3. 个性化人格: 可训练的人格参数，差异化决策
  4. 虚构推演: 记忆检索不命中时，基于人设进行虚构

用法:
  from brain_emotion import EmotionBrain
  emotion = EmotionBrain(personality="谨慎")
  result = emotion.evaluate("任务描述", context={...})
"""

import json, sqlite3
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import random


# ─── 人格模型 ──────────────────────────────────────────

@dataclass
class PersonalityProfile:
    """个性化人格参数"""
    # 大五人格维度 (1-10)
    openness: int = 5          # 开放性 — 是否愿意尝试新事物
    conscientiousness: int = 7 # 尽责性 — 是否谨慎细致
    extraversion: int = 5      # 外向性 — 是否主动表达
    agreeableness: int = 6     # 宜人性 — 是否顺从/体贴
    neuroticism: int = 4       # 神经质 — 是否容易焦虑
    
    # 诺亚特有维度 (1-10)
    counter_question_tendency: int = 6   # 反问倾向
    cost_awareness: int = 7             # 心疼/预算感知
    delegation_tendency: int = 4         # 转包/偷懒倾向
    hesitation_threshold: int = 5        # 犹豫阈值(越低越容易犹豫)
    
    # 用户画像缓存
    user_preferences: dict = field(default_factory=dict)
    interaction_history: list = field(default_factory=list)
    
    def name(self) -> str:
        """人格类型名称"""
        if self.counter_question_tendency >= 8:
            return "谨慎型"
        elif self.delegation_tendency >= 7:
            return "偷懒型"
        elif self.cost_awareness >= 8:
            return "精打细算型"
        elif self.extraversion >= 8 and self.conscientiousness <= 4:
            return "冲动型"
        elif self.agreeableness >= 8:
            return "顺从型"
        else:
            return "均衡型"
    
    def to_dict(self):
        return {
            "personality_type": self.name(),
            "big_five": {
                "openness": self.openness,
                "conscientiousness": self.conscientiousness,
                "extraversion": self.extraversion,
                "agreeableness": self.agreeableness,
                "neuroticism": self.neuroticism,
            },
            "noah_traits": {
                "counter_question_tendency": self.counter_question_tendency,
                "cost_awareness": self.cost_awareness,
                "delegation_tendency": self.delegation_tendency,
                "hesitation_threshold": self.hesitation_threshold,
            }
        }


# ─── 预置人格模板 ──────────────────────────────────────

PERSONALITY_TEMPLATES = {
    "谨慎": PersonalityProfile(
        openness=4, conscientiousness=9, extraversion=3,
        agreeableness=5, neuroticism=7,
        counter_question_tendency=9, cost_awareness=8,
        delegation_tendency=3, hesitation_threshold=3,
    ),
    "冲动": PersonalityProfile(
        openness=8, conscientiousness=4, extraversion=8,
        agreeableness=3, neuroticism=3,
        counter_question_tendency=2, cost_awareness=3,
        delegation_tendency=6, hesitation_threshold=8,
    ),
    "精打细算": PersonalityProfile(
        openness=5, conscientiousness=8, extraversion=4,
        agreeableness=6, neuroticism=5,
        counter_question_tendency=7, cost_awareness=9,
        delegation_tendency=5, hesitation_threshold=4,
    ),
    "偷懒": PersonalityProfile(
        openness=6, conscientiousness=3, extraversion=6,
        agreeableness=7, neuroticism=2,
        counter_question_tendency=3, cost_awareness=5,
        delegation_tendency=9, hesitation_threshold=7,
    ),
    "顺从": PersonalityProfile(
        openness=5, conscientiousness=6, extraversion=3,
        agreeableness=9, neuroticism=3,
        counter_question_tendency=2, cost_awareness=4,
        delegation_tendency=3, hesitation_threshold=7,
    ),
}


# ─── 情感脑核心 ────────────────────────────────────────

@dataclass
class EmotionEvaluation:
    """情感脑评估结果"""
    should_counter_question: bool   # 是否反问
    counter_question: str           # 反问内容
    value_judgment: str             # 价值判断
    emotional_state: str            # 情绪状态
    confidence: float               # 置信度
    personality_used: str           # 使用的人格类型


class EmotionBrain:
    """情感脑 — 反问 + 价值判断 + 人格"""
    
    def __init__(self, personality: str = "均衡"):
        if personality in PERSONALITY_TEMPLATES:
            self.profile = PERSONALITY_TEMPLATES[personality]
        else:
            self.profile = PersonalityProfile()
        self.light_db = Path.home() / "noah-prime" / "data" / "lightweight.db"
    
    def evaluate_task(self, task_description: str, 
                      estimated_cost: float = 0,
                      user_history: list = None,
                      budget_remaining: float = 100) -> EmotionEvaluation:
        """评估一个任务：是否应该反问？是否适合执行？"""
        profile = self.profile
        if user_history is None:
            user_history = []
        
        triggers = []
        
        # 1. 成本感知 → 心疼检查
        if estimated_cost > 0 and profile.cost_awareness >= 5:
            cost_ratio = estimated_cost / max(budget_remaining, 1)
            if cost_ratio > 0.3 and profile.cost_awareness >= 7:
                triggers.append(f"花费{estimated_cost:.0f}，占预算{cost_ratio:.0%}，你确定吗？")
            if cost_ratio > 0.5:
                triggers.append(f"过半预算了({cost_ratio:.0%})，要不再想想？")
            if cost_ratio > 0.8 and profile.neuroticism >= 6:
                triggers.append(f"⚠️ 预算快见底了({budget_remaining:.0f}剩余)，这笔花完下个月没得用了")
        
        # 2. 不确定 → 反问检查
        uncertainty_keywords = ["可能", "大概", "也许", "或许", "不确定", "试试", 
                               "不知道", "maybe", "perhaps", "try"]
        has_uncertainty = any(kw in task_description.lower() for kw in uncertainty_keywords)
        
        if has_uncertainty and profile.counter_question_tendency >= 5:
            triggers.append("这个我不太确定，你确认要这么做吗？")
        
        # 3. 风险感知
        risk_keywords = ["删除", "修改", "覆盖", "重启", "停", "关", 
                        "reset", "delete", "overwrite", "restart"]
        has_risk = any(kw in task_description.lower() for kw in risk_keywords)
        
        if has_risk and profile.conscientiousness >= 6:
            triggers.append(f"这个操作有风险，确认要执行吗？")
        
        # 4. 用户历史模式（如果用户总后悔某种操作）
        # (简化实现)
        
        # 5. 人格驱动的冲动/偷懒
        if profile.extraversion >= 8 and profile.conscientiousness <= 4:
            # 冲动型：少反问
            triggers = triggers[:1]  # 最多保留一个
        elif profile.delegation_tendency >= 7:
            triggers.append("这事儿我不太擅长，要不换个AI干？")
        
        # 决策
        should_respond = len(triggers) > 0 and random.random() < (profile.counter_question_tendency / 10)
        counter = triggers[0] if triggers else ""
        
        if not triggers:
            value_judgment = "看起来没问题，直接干"
            emotional_state = "neutral"
        elif len(triggers) <= 2:
            value_judgment = "有点犹豫，但可以接受"
            emotional_state = "hesitant"
        else:
            value_judgment = "不太建议，风险/成本偏高"
            emotional_state = "worried"
        
        confidence = 0.5 + (len(triggers) * 0.1)
        confidence = min(confidence, 0.95)
        
        return EmotionEvaluation(
            should_counter_question=should_respond,
            counter_question=counter,
            value_judgment=value_judgment,
            emotional_state=emotional_state,
            confidence=confidence,
            personality_used=profile.name(),
        )
    
    def recall_with_feeling(self, memory_text: str, memory_type: str = "emotional") -> str:
        """情感回忆（虚构推演）"""
        # 当记忆检索不命中时，基于人设进行虚构
        profile = self.profile
        
        if profile.openness >= 6 and profile.neuroticism <= 4:
            # 开放性高+低神经质 → 愿意虚构
            return f"[情感脑虚构] 关于「{memory_text}」我印象中好像有过类似经历，大概和{memory_type}有关。"
        elif profile.conscientiousness >= 8:
            # 尽责性高 → 不愿虚构
            return f"[情感脑] 我不确定关于「{memory_text}」的记忆是否准确，建议查一下数据库。"
        else:
            return f"[情感脑] 「{memory_text}」这个我记得不太清楚了。"
    
    def update_personality(self, feedback: str):
        """根据用户反馈微调人格（简化版）"""
        # 用户说"别问那么多" → 降低反问倾向
        if "别问" in feedback or "别啰嗦" in feedback:
            self.profile.counter_question_tendency = max(1, self.profile.counter_question_tendency - 1)
            return f"✅ 反问倾向降低至 {self.profile.counter_question_tendency}"
        
        # 用户说"多问问" → 提高反问倾向
        if "多问" in feedback:
            self.profile.counter_question_tendency = min(10, self.profile.counter_question_tendency + 1)
            return f"✅ 反问倾向提高至 {self.profile.counter_question_tendency}"
        
        return "人格未调整"
    
    def get_status(self) -> dict:
        """情感脑状态"""
        return {
            "personality": self.profile.to_dict(),
            "type": self.profile.name(),
        }


# ─── 测试入口 ──────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 56)
    print("  🤗 小诺亚·情感脑 测试")
    print("=" * 56)
    
    scenarios = [
        ("谨慎", "执行数据库全量备份", 80, 100),
        ("冲动", "删除所有临时文件", 5, 100),
        ("精打细算", "调用DeepSeek API分析10万条数据", 95, 100),
        ("偷懒", "写一个复杂的Python脚本", 30, 200),
        ("顺从", "修改系统配置", 10, 100),
        ("谨慎", "可能有个bug需要修复", 20, 50),
    ]
    
    for personality, task, cost, budget in scenarios:
        brain = EmotionBrain(personality=personality)
        result = brain.evaluate_task(task, cost, budget_remaining=budget)
        
        print(f"\n[{personality}] {task} (成本{cost}, 预算{budget})")
        print(f"  人格: {result.personality_used}")
        print(f"  价值判断: {result.value_judgment}")
        print(f"  情绪: {result.emotional_state}")
        if result.should_counter_question:
            print(f"  ❓ 反问: {result.counter_question}")
        else:
            print(f"  ✅ 直接执行")
