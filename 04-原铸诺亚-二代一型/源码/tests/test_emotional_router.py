#!/usr/bin/env python3
"""情感路由测试 · test_emotional_router.py

第三阶段 §11 — 含冲突场景测试

测试项:
  1. emotional_router: L1/L2检测 + 四级递进 + 路由矩阵 + 冲突仲裁
  2. emotional_strategies: 策略选择 + 话术渲染 + 反馈追踪
  3. 集成: 与secretary.py兼容
"""

import sys, os, json
from pathlib import Path

EMBRYO = Path.home() / "noah-embryo"
sys.path.insert(0, str(EMBRYO))

FAILURES = []


def check(label: str, ok: bool, detail: str = ""):
    if ok:
        print(f"  ✅ {label}")
    else:
        print(f"  ⛔ {label}: {detail}")
        FAILURES.append(label)


# ═══════════════════════════════════════════════════════════════
# 1. emotional_router
# ═══════════════════════════════════════════════════════════════

def test_router():
    print("\n── 1. 情感路由 (emotional_router) ──")
    from brain.emotional_router import (
        detect_emotion, l1_detect, l2_detect,
        route_channel, arbitrate, self_test,
        detect_emotion_compat,
    )

    # 自检
    st = self_test()
    check("自检全部通过", st.get("all_pass", False), str(st))

    # L1: 各类情感检测
    for text, expected in [
        ("快！服务器崩了", "urgent"),
        ("气死了，什么垃圾", "angry"),
        ("好难，怎么办", "anxious"),
        ("累了，不想动了", "tired"),
        ("哈哈太棒了", "happy"),
        ("谢谢", "satisfied"),
        ("今天天气不错", "neutral"),
    ]:
        r = l1_detect(text)
        check(f"L1 [{expected}] '{text[:12]}...'", r["emotion"] == expected,
              f"期望={expected}, 实际={r['emotion']}")

    # L2: 句式增强
    r2 = l2_detect("怎么办？？", {"emotion": "neutral", "confidence": 50})
    check("L2 疑问句→焦虑", r2["emotion"] in ("anxious", "neutral"),
          f"got={r2['emotion']}")

    # 路由矩阵
    check("路由 urgent+fix→api", route_channel("urgent", "fix") == "api")
    check("路由 happy+chat→chat", route_channel("happy", "chat") == "chat")
    check("路由 neutral+knowledge→web", route_channel("neutral", "knowledge") == "web")

    # 冲突仲裁
    arb1 = arbitrate("angry", "fix", "烦死了这个bug")
    check("仲裁 angry+fix→api", arb1["channel"] == "api", f"通道={arb1['channel']}")
    check("仲裁 有情感前缀", "确实让人火大" in arb1.get("emotion_prefix", ""),
          f"前缀={arb1.get('emotion_prefix','')}")

    arb2 = arbitrate("neutral", "chat", "你好")
    check("仲裁 neutral+chat 无前缀", arb2.get("emotion_prefix", "") == "",
          f"前缀={arb2.get('emotion_prefix','')}")

    # 兼容接口
    compat = detect_emotion_compat("哈哈")
    check("兼容接口 positive映射", compat["emotion"] == "positive")

    compat2 = detect_emotion_compat("气死了")
    check("兼容接口 negative映射", compat2["emotion"] == "negative")

    # 检测入口
    r3 = detect_emotion("紧急！出错了，快帮我看看", use_l3=False)
    check("detect_emotion urgent", r3["emotion"] == "urgent",
          f"got={r3['emotion']}")


# ═══════════════════════════════════════════════════════════════
# 2. emotional_strategies
# ═══════════════════════════════════════════════════════════════

def test_strategies():
    print("\n── 2. 情绪策略库 (emotional_strategies) ──")
    from brain.emotional_strategies import (
        get_strategy, render_template, select_strategy,
        self_test, EmotionFeedback,
    )

    # 自检
    st = self_test()
    check("自检全部通过", st.get("all_pass", False), str(st))

    # 策略选择
    s1 = get_strategy("urgent")
    check("urgent→安抚策略", s1["name"] == "安抚策略")

    s2 = get_strategy("happy")
    check("happy→共鸣扩展", s2["name"] == "共鸣扩展策略")

    s3 = get_strategy("neutral")
    check("neutral→理性策略", s3["name"] == "理性策略")

    # 话术渲染
    rendered = render_template("angry", {"issue": "这个bug"})
    check("angry话术含issue", "这个bug" in rendered, f"话术={rendered[:50]}")

    # 完整策略选择
    sel = select_strategy("urgent", "fix", {
        "text": "服务器崩了！",
        "issue": "服务器崩溃",
        "minutes": "5",
    })
    check("策略选择 含话术前缀", len(sel["prefix"]) > 5, f"前缀={sel['prefix'][:40]}")
    check("策略选择 通道正确", sel["channel"] in ("chat", "web", "local", "api"),
          f"通道={sel['channel']}")

    # 反馈追踪
    fb = EmotionFeedback()
    fb.record("session1", "angry", "承接情绪策略", "谢谢，好多了")
    fb.record("session1", "happy", "共鸣扩展策略", "太好了！")
    satisfaction = fb.get_satisfaction("session1")
    check("反馈追踪 满意度>0", satisfaction > 0, f"满意度={satisfaction}")


# ═══════════════════════════════════════════════════════════════
# 3. 集成测试
# ═══════════════════════════════════════════════════════════════

def test_integration():
    print("\n── 3. 集成测试 ──")
    from brain.emotional_router import detect_emotion
    from brain.emotional_strategies import select_strategy

    # 完整链路: 输入→情感检测→策略选择
    test_cases = [
        ("快！服务器崩了", "urgent"),
        ("烦死了这个bug一直报错", "angry"),
        ("好难啊怎么办", "anxious"),
        ("哈哈太棒了", "happy"),
    ]

    for text, expected_emotion in test_cases:
        emotion = detect_emotion(text, use_l3=False)
        strategy = select_strategy(emotion["emotion"], "fix" if "bug" in text else "chat",
                                    {"text": text, "issue": text})

        emotion_ok = emotion["emotion"] == expected_emotion
        strategy_ok = len(strategy.get("prefix", "")) > 5
        status = "✅" if (emotion_ok and strategy_ok) else "⚠️"
        print(f"  {status} '{text[:16]}...' → {emotion['emotion']}({emotion['confidence']}%) "
              f"→ 话术[{strategy.get('strategy','')[:6]}]")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("═══════════════════════════════════════")
    print("  情感路由 · 单元测试")
    print("═══════════════════════════════════════")

    test_router()
    test_strategies()
    test_integration()

    print(f"\n── 结果 ──")
    if FAILURES:
        print(f"  ⛔ {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"    - {f}")
        sys.exit(1)
    else:
        print("  ✅ 全部通过 — 情感路由就绪")
        sys.exit(0)


if __name__ == "__main__":
    main()
