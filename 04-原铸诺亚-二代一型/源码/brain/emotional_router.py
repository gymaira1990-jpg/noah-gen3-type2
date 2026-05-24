#!/usr/bin/env python3
"""情感路由升级版 · emotional_router.py

第三阶段 §5 — 情感路由分层递进体系 + 行为筛选 + 派发

四级递进判断:
  第1级 · 0.5B快速判断 (~1ms): 关键词匹配
  第2级 · 3B秘书层意图分类 (~500ms): intent+confidence
  第3级 · 3B+0.5B联合判断 (~2s): 综合上下文+历史
  第4级 · 用户确认 (可选): 置信度<50时询问

情感路由派发矩阵:
  情感(urgent) + 意图(fix) → api通道 (强制)
  情感(negative) + 意图(chat) → chat通道 (情感陪伴)
  情感(positive) + 意图(work) → api通道 (正反馈)
  情感(neutral) + 意图(knowledge) → web通道 (纯理性搜索)

情感-意图冲突仲裁:
  fix/urgent > work/code > knowledge/study > chat/emotional
  但 emotional 标签永不丢弃 — 作为前缀/后缀附加到输出
"""

import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Optional, Dict, List

EMBRYO = Path.home() / "noah-embryo"
sys.path.insert(0, str(EMBRYO))

# ═══════════════════════════════════════════════════════════════
# 情感关键词库 (扩展版: 6类×20-50词)
# ═══════════════════════════════════════════════════════════════

EMOTION_KEYWORDS = {
    "urgent": [
        "急", "马上", "立刻", "快", "坏了", "挂了", "崩了", "宕机",
        "报错", "紧急", "出事了", "救命", "help", "urgent", "asap",
        "来不及", "快点", "赶紧", "速度", "加急", "火急",
    ],
    "angry": [
        "烦死了", "无语", "气死了", "垃圾", "恶心", "差劲", "太差了",
        "什么鬼", "搞什么", "有病", "滚", "闭嘴", "废物", "蠢",
        "妈的", "草", "靠", "shit", "fuck", "damn", "anger",
    ],
    "anxious": [
        "怎么办", "好难", "不会", "搞不定", "咋整", "焦虑", "紧张",
        "害怕", "担心", "慌", "不安", "头疼", "烦躁", "纠结",
        "迷茫", "困惑", "无助", "崩溃", "压力",  "stress",
    ],
    "tired": [
        "累了", "疲惫", "困了", "不想动", "没劲", "乏力", "虚脱",
        "好累", "受不了", "坚持不住", "倦了", "疲了", "tired", "exhausted",
    ],
    "happy": [
        "哈哈", "开心", "好棒", "太好了", "nice", "great", "完美",
        "喜欢", "厉害", "优秀", "赞", "棒", "给力", "爽",
        "兴奋", "激动", "开心死了", "绝了", "awesome", "amazing",
    ],
    "satisfied": [
        "谢谢", "感谢", "多谢", "辛苦了", "好用", "可以",
        "ok", "好的", "行", "满意", "靠谱", "thanks", "thank you",
        "非常好", "真不错",
    ],
}

# 基调情感 (模型未匹配时使用)
_FALLBACK_EMOTION = "neutral"

# 情感emoji映射
_EMOJI_MAP = {
    "urgent": "⚡",
    "angry": "😤",
    "anxious": "😰",
    "tired": "😮‍💨",
    "happy": "😊",
    "satisfied": "👍",
    "neutral": "·",
}


# ═══════════════════════════════════════════════════════════════
# 句式特征检测
# ═══════════════════════════════════════════════════════════════

def _syntax_features(text: str) -> Dict[str, float]:
    """提取句式特征用于情感判断

    Returns:
        {"疑问句": 0-1, "感叹句": 0-1, "省略句": 0-1, "重复词": 0-1}
    """
    features = {}
    
    # 疑问句
    question_markers = ["吗", "呢", "？", "?", "什么", "怎么", "如何", "为什么"]
    q_score = sum(1 for m in question_markers if m in text) / len(question_markers)
    features["疑问句"] = min(q_score, 1.0)
    
    # 感叹句
    exclamation = text.count("！") + text.count("!") + text.count("啊") * 0.5
    features["感叹句"] = min(exclamation / 3, 1.0)
    
    # 省略句
    ellipsis = text.count("...") + text.count("…") + text.count("。") * 0.2
    features["省略句"] = min(ellipsis / 5, 1.0)
    
    # 重复词
    words = text.split()
    if words:
        repeats = sum(1 for w in words if words.count(w) > 1)
        features["重复词"] = min(repeats / len(words) * 2, 1.0)
    else:
        features["重复词"] = 0
    
    return features


# ═══════════════════════════════════════════════════════════════
# 语气词检测
# ═══════════════════════════════════════════════════════════════

_TONE_MAP = {
    "疑惑": ["啊", "吗", "呢", "吧"],
    "平和": ["吧", "啦", "哦", "嗯"],
    "兴奋": ["啊!", "呀!", "哇"],
    "失落": ["唉", "哎", "啧", "唉声叹气"],
}


def _tone_features(text: str) -> Dict[str, float]:
    """提取语气词特征"""
    features = {}
    for tone, words in _TONE_MAP.items():
        score = sum(1 for w in words if w in text)
        features[tone] = min(score / len(words), 1.0)
    return features


# ═══════════════════════════════════════════════════════════════
# 第1级: 0.5B快速关键词判断 (~1ms)
# ═══════════════════════════════════════════════════════════════

_L1_CACHE = {}


def l1_detect(text: str) -> Dict:
    """第1级: 关键词快速匹配

    Returns:
        {"emotion": "...", "confidence": 0-100, "source": "l1_keyword"}
    """
    text_lower = text.lower().strip()
    cache_key = hash(text_lower) % 1000000
    if cache_key in _L1_CACHE:
        return _L1_CACHE[cache_key]

    scores = {}
    for emotion, keywords in EMOTION_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in text_lower:
                score += 10 + len(kw)  # 长关键词权重更高
        if score > 0:
            scores[emotion] = score

    if not scores:
        result = {"emotion": "neutral", "confidence": 50, "source": "l1_keyword"}
        _L1_CACHE[cache_key] = result
        return result

    # 选择最高分情感
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    confidence = min(int(scores[best] / total * 100), 90)

    result = {"emotion": best, "confidence": confidence, "source": "l1_keyword",
              "scores": scores}
    _L1_CACHE[cache_key] = result
    return result


# ═══════════════════════════════════════════════════════════════
# 第2级: 3B秘书层多维度分析 (~500ms)
# ═══════════════════════════════════════════════════════════════

def l2_detect(text: str, l1_result: Dict) -> Dict:
    """第2级: 多维情感分析 (关键词+句式+语气词)

    Args:
        text: 用户输入
        l1_result: 第1级结果

    Returns:
        {"emotion": "...", "confidence": 0-100, "source": "l2_multidim",
         "维度分解": {...}}
    """
    text_lower = text.lower().strip()

    # 关键词权重 (来自L1)
    kw_weight = 0.4
    syntax_weight = 0.3
    tone_weight = 0.2
    history_weight = 0.1

    # 关键词得分
    kw = l1_result

    # 句式特征
    syntax = _syntax_features(text_lower)
    # 感叹句 → 愤怒/兴奋倾向
    if syntax.get("感叹句", 0) > 0.5 and kw.get("emotion") == "neutral":
        kw["emotion"] = "angry"
        kw["confidence"] = 60

    # 疑问句 → 焦虑/疑惑倾向
    if syntax.get("疑问句", 0) > 0.5 and kw.get("emotion") == "neutral":
        kw["emotion"] = "anxious"
        kw["confidence"] = 55

    # 语气词
    tone = _tone_features(text_lower)
    if tone.get("失落", 0) > 0.3:
        kw["emotion"] = "tired"
        kw["confidence"] = max(kw["confidence"], 50)

    # 综合置信度提升
    if kw["emotion"] != "neutral":
        kw["confidence"] = min(kw["confidence"] + 5, 95)

    kw["source"] = "l2_multidim"
    return kw


# ═══════════════════════════════════════════════════════════════
# 第3级: 3B+0.5B联合判断 (~2s)
# ═══════════════════════════════════════════════════════════════

_L3_CACHE = {}
_L3_TTL = 3600  # 1小时


def l3_detect(text: str, l2_result: Dict) -> Dict:
    """第3级: 委托3B模型做深度情感分析

    仅当L2置信度<70且输入较复杂时触发

    Args:
        text: 用户输入
        l2_result: 第2级结果

    Returns:
        {"emotion": "...", "confidence": 0-100, "source": "l3_llm", "explanation": "..."}
    """
    # 低置信度或复杂输入才触发L3
    if l2_result["confidence"] >= 70 or len(text) < 15:
        l2_result["source"] = "l2_multidim (L3跳过)"
        return l2_result

    cache_key = hash(text) % 1000000
    if cache_key in _L3_CACHE:
        cached = _L3_CACHE[cache_key]
        if time.time() - cached.get("_cached_at", 0) < _L3_TTL:
            return cached

    try:
        from brain.secretary import _call_local_3b
        prompt = (
            f"分析以下文本的情感。仅输出JSON。\n\n"
            f"文本: {text}\n\n"
            f"情感类别: urgent/angry/anxious/tired/happy/satisfied/neutral\n"
            f'输出: {{"emotion": "...", "confidence": 0-100, "explanation": "..."}}'
        )
        response = _call_local_3b(prompt)

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            assessment = json.loads(json_match.group())
        else:
            assessment = {"emotion": l2_result["emotion"],
                          "confidence": l2_result["confidence"],
                          "explanation": "解析失败"}

        result = {
            "emotion": assessment.get("emotion", l2_result["emotion"]),
            "confidence": int(assessment.get("confidence", l2_result["confidence"])),
            "source": "l3_llm",
            "explanation": assessment.get("explanation", ""),
            "_cached_at": time.time(),
        }
        _L3_CACHE[cache_key] = result
        return result

    except Exception:
        l2_result["source"] = "l2_multidim (L3异常降级)"
        return l2_result


# ═══════════════════════════════════════════════════════════════
# 四级递进统一入口
# ═══════════════════════════════════════════════════════════════

def detect_emotion(text: str, use_l3: bool = True) -> Dict:
    """情感检测四级递进

    Args:
        text: 用户输入
        use_l3: 是否启用L3 (3B模型辅助)

    Returns:
        {"emotion": "...", "emoji": "...", "confidence": 0-100,
         "source": "...", "level": 1|2|3|4}
    """
    start = time.time()

    # L1: 关键词快速匹配
    l1 = l1_detect(text)
    if l1["confidence"] >= 80 and l1["emotion"] != "neutral":
        return {
            "emotion": l1["emotion"],
            "emoji": _EMOJI_MAP.get(l1["emotion"], "·"),
            "confidence": l1["confidence"],
            "source": "l1_keyword",
            "level": 1,
            "latency_ms": int((time.time() - start) * 1000),
        }

    # L2: 多维度分析
    l2 = l2_detect(text, l1)
    if l2["confidence"] >= 70 or not use_l3:
        return {
            "emotion": l2["emotion"],
            "emoji": _EMOJI_MAP.get(l2["emotion"], "·"),
            "confidence": l2["confidence"],
            "source": l2.get("source", "l2_multidim"),
            "level": 2,
            "latency_ms": int((time.time() - start) * 1000),
            "syntax": _syntax_features(text),
        }

    # L3: 3B模型深度分析
    l3 = l3_detect(text, l2)
    return {
        "emotion": l3["emotion"],
        "emoji": _EMOJI_MAP.get(l3["emotion"], "·"),
        "confidence": l3["confidence"],
        "source": l3.get("source", "l3_llm"),
        "level": 3,
        "latency_ms": int((time.time() - start) * 1000),
        "explanation": l3.get("explanation", ""),
    }


# ═══════════════════════════════════════════════════════════════
# 情感路由派发矩阵
# ═══════════════════════════════════════════════════════════════

EMOTION_CHANNEL_MATRIX = {
    # (emotion, intent) → channel
    ("urgent", "fix"): "api",
    ("urgent", "work"): "api",
    ("urgent", "knowledge"): "api",
    ("urgent", "chat"): "chat",
    ("urgent", "study"): "api",

    ("angry", "fix"): "api",
    ("angry", "work"): "api",
    ("angry", "chat"): "chat",
    ("angry", "knowledge"): "local",

    ("anxious", "fix"): "api",
    ("anxious", "work"): "api",
    ("anxious", "chat"): "chat",
    ("anxious", "knowledge"): "web",

    ("tired", "chat"): "chat",
    ("tired", "work"): "local",
    ("tired", "knowledge"): "local",

    ("happy", "work"): "api",
    ("happy", "chat"): "chat",
    ("happy", "knowledge"): "web",
    ("happy", "study"): "web",

    ("satisfied", "chat"): "chat",
    ("satisfied", "work"): "api",
    ("satisfied", "knowledge"): "local",

    ("neutral", "chat"): "chat",
    ("neutral", "work"): "api",
    ("neutral", "knowledge"): "web",
    ("neutral", "study"): "web",
    ("neutral", "fix"): "api",
}


def route_channel(emotion: str, intent: str) -> str:
    """根据情感+意图路由通道

    Returns: "chat" | "web" | "local" | "api"
    """
    return EMOTION_CHANNEL_MATRIX.get((emotion, intent), "api")


# ═══════════════════════════════════════════════════════════════
# 情感-意图冲突仲裁
# ═══════════════════════════════════════════════════════════════

INTENT_PRIORITY = {
    "fix": 4,
    "work": 3,
    "code": 3,
    "deploy": 3,
    "knowledge": 2,
    "study": 2,
    "chat": 1,
}

EMOTION_PRIORITY = {
    "urgent": 5,
    "angry": 3,
    "anxious": 3,
    "tired": 2,
    "happy": 1,
    "satisfied": 1,
    "neutral": 0,
}


def arbitrate(emotion: str, intent: str, text: str) -> Dict:
    """情感-意图冲突仲裁

    规则:
      1. fix/urgent > work/code > knowledge/study > chat/emotional
      2. emotional标签永不丢弃 — 作为前缀/后缀附加到输出

    Returns:
        {"channel": "...", "emotion_prefix": "...", "emotion_suffix": "...",
         "priority": "...", "resolution": "..."}
    """
    emo_pri = EMOTION_PRIORITY.get(emotion, 0)
    int_pri = INTENT_PRIORITY.get(intent, 0)

    # 冲突判断
    if emo_pri > int_pri and emotion in ("urgent", "angry", "anxious"):
        # 情感优先级更高 → 先安抚再处理
        resolution = "emotion_first"
        channel = route_channel(emotion, intent)
    elif int_pri >= emo_pri:
        # 任务优先级更高 → 先处理任务, 情感作为修饰
        resolution = "task_first"
        channel = route_channel(emotion, intent)
    else:
        resolution = "balanced"
        channel = route_channel(emotion, intent)

    # 情感修饰前缀/后缀
    emotion_prefix = ""
    emotion_suffix = ""

    if emotion == "urgent":
        emotion_prefix = "⚡收到，马上处理。"
    elif emotion == "angry":
        emotion_prefix = "确实让人火大，我们一起来看看卡在哪了。"
    elif emotion == "anxious":
        emotion_prefix = "别担心，我们一步步来。"
    elif emotion == "tired":
        emotion_prefix = "辛苦了，我们尽量简化。"
    elif emotion == "happy":
        emotion_suffix = "😊"
    elif emotion == "satisfied":
        emotion_suffix = "👍"

    return {
        "channel": channel,
        "emotion_prefix": emotion_prefix,
        "emotion_suffix": emotion_suffix,
        "priority": max(emo_pri, int_pri),
        "resolution": resolution,
        "emotion_priority": emo_pri,
        "intent_priority": int_pri,
    }


# ═══════════════════════════════════════════════════════════════
# 第4级: 用户确认 (置信度<50时)
# ═══════════════════════════════════════════════════════════════

def needs_confirmation(emotion_result: Dict) -> bool:
    """判断是否需要询问用户确认"""
    return emotion_result["confidence"] < 50 and emotion_result["emotion"] != "neutral"


def build_confirmation_prompt(emotion_result: Dict) -> str:
    """生成询问用户的提示"""
    return (
        f"我看你好像有点{emotion_result['emotion']}，"
        f"你是想聊聊还是需要我帮你做点什么？"
    )


# ═══════════════════════════════════════════════════════════════
# 兼容: 替换secretary.py中的旧detect_emotion
# ═══════════════════════════════════════════════════════════════

# 旧接口映射 (供secretary.py无缝替换)
_EMOJI_MAP_OLD = {
    "positive": "😊",
    "negative": "😞",
    "urgent": "⚡",
    "neutral": "·",
}

_EMOTION_MERGE_MAP = {
    "happy": "positive",
    "satisfied": "positive",
    "angry": "negative",
    "anxious": "negative",
    "tired": "negative",
}


def detect_emotion_compat(text: str) -> Dict:
    """兼容接口: 将新6类映射回旧4类

    secretary.py 的旧代码期望: positive/negative/urgent/neutral
    """
    result = detect_emotion(text, use_l3=False)
    old_emotion = _EMOTION_MERGE_MAP.get(result["emotion"], result["emotion"])

    return {
        "emotion": old_emotion,
        "emoji": _EMOJI_MAP_OLD.get(old_emotion, "·"),
        "confidence": result["confidence"],
        "source": result["source"],
        "level": result["level"],
        "raw_emotion": result["emotion"],  # 保留原始6类
    }


# ═══════════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════════

def self_test() -> Dict:
    """自检: 验证各功能"""
    results = {
        "l1_urgent": False,
        "l1_angry": False,
        "l1_happy": False,
        "l1_neutral": False,
        "l2_syntax": False,
        "route_chat": False,
        "route_api": False,
        "arbitrate_urgent_fix": False,
        "compat_map": False,
    }

    # L1检测
    r1 = l1_detect("快！服务器崩了")
    results["l1_urgent"] = r1["emotion"] == "urgent"

    r2 = l1_detect("气死了，什么垃圾")
    results["l1_angry"] = r2["emotion"] == "angry"

    r3 = l1_detect("哈哈，太棒了")
    results["l1_happy"] = r3["emotion"] == "happy"

    r4 = l1_detect("桌子是木头的")
    results["l1_neutral"] = r4["emotion"] == "neutral"

    # L2句式
    syntax = _syntax_features("怎么办？？好难啊！！！")
    results["l2_syntax"] = syntax.get("疑问句", 0) > 0.1 and syntax.get("感叹句", 0) > 0.3

    # 路由
    results["route_chat"] = route_channel("happy", "chat") == "chat"
    results["route_api"] = route_channel("urgent", "fix") == "api"

    # 冲突仲裁
    arb = arbitrate("angry", "fix", "烦死了这个bug")
    results["arbitrate_urgent_fix"] = arb["channel"] == "api"

    # 兼容映射
    compat = detect_emotion_compat("哈哈")
    results["compat_map"] = compat["emotion"] == "positive"

    results["all_pass"] = all(results.values())
    return results


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import sys
    if "--self-test" in sys.argv:
        results = self_test()
        for k, v in results.items():
            print(f"  {'✅' if v else '❌'} {k}")
        print(f"\n  {'✅ 全部通过' if results.get('all_pass') else '❌ 存在失败'}")
        return

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        emotion = detect_emotion(text)
        print(f"情感: {emotion['emotion']} {emotion['emoji']} ({emotion['confidence']}%)")
        print(f"来源: L{emotion['level']} | {emotion['source']}")
        print(f"耗时: {emotion.get('latency_ms', 0)}ms")
        if emotion.get("explanation"):
            print(f"解释: {emotion['explanation']}")
    else:
        print("情感路由 · emotional_router.py")
        print("用法: python3 emotional_router.py <文本>  # 情感检测")
        print("      python3 emotional_router.py --self-test")


if __name__ == "__main__":
    main()
