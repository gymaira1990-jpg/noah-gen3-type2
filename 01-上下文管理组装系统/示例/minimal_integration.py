"""
minimal_integration.py — 最小接入示例

纯 Python 接入 Tier1 抽屉级联压缩引擎，不依赖任何框架。
约 60 行代码即可获得完整的抽屉压缩能力。

用法:
    from minimal_integration import MinimalCompressor
    
    def my_llm(messages):
        # 你的 LLM 调用实现
        return "模拟摘要"
    
    comp = MinimalCompressor(llm_call_fn=my_llm)
    comp.feed("你好")
    comp.feed("我们来设计一个上下文管理系统")
    context = comp.get_context()
    print(context)
"""

import sys
import os

# 添加源码路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "源码"))

from drawer_engine import (
    DrawerStack,
    NoiseFilter,
    ProtectionDetector,
    UniqueKeyIndex,
    TemperatureIndex,
)


class MinimalCompressor:
    """最小抽屉级联压缩器。

    只需传入一个 LLM 调用函数，即可获得完整的抽屉压缩能力。
    包含：噪音过滤、保护识别、key 身份管理、抽屉级联、温度追踪。
    """

    def __init__(self, llm_call_fn, drawer_capacity: int = 3):
        """
        Args:
            llm_call_fn: 辅助模型调用函数
                签名: fn(messages: list[dict], temperature=0.1, max_tokens=512) -> str|None
            drawer_capacity: 每层抽屉容量 (默认 3)
        """
        self.drawer = DrawerStack(capacity=drawer_capacity)
        self.noise = NoiseFilter()
        self.protector = ProtectionDetector()
        self.keys = UniqueKeyIndex()
        self.temperature = TemperatureIndex()
        self.llm_call = llm_call_fn
        self.round = 0

    def feed(self, user_message: str) -> None:
        """每轮用户消息后调用。

        处理链: 噪音过滤 → 保护检测 → key 检查 → 推入抽屉 → 温度命中 → 满则压缩
        """
        # 1. 噪音过滤
        if self.noise.is_noise(user_message):
            return

        # 2. 保护检测
        info = self.protector.detect(user_message)
        self.keys.tick()
        if info["key"]:
            verdict = self.keys.check(info["key"], user_message,
                                       info["protection_type"])
            if verdict["action"] == "skip":
                return
            self.keys.register(info["key"], user_message,
                               info["protection_type"])

        # 3. 推入抽屉
        self.drawer.push({
            "role": "user",
            "content": user_message,
            "_protected": info["protected"],
        })

        # 4. 温度命中
        self.temperature.hit(
            info["key"] or user_message[:40],
            user_message,
            info.get("importance_bonus", 0),
        )
        self.round += 1

        # 5. 抽屉满 → 压缩递交
        while self.drawer.is_top_full:
            items = self.drawer.pop_top()
            protected = [m for m in items if m.get("_protected")]
            compressible = [m for m in items if not m.get("_protected")]

            if compressible:
                text = "\n".join(
                    str(m.get("content", "")) for m in compressible
                )
                summary = self.llm_call([
                    {"role": "system",
                     "content": f"压缩以下{len(compressible)}条消息为 200 tok 摘要"},
                    {"role": "user", "content": text},
                ])
                self.drawer.push_summary(
                    {"role": "system", "content": f"[摘要] {summary}"}
                )

            # 保护条目放回头部（不被压缩，保持可见）
            for m in protected:
                self.drawer.push_to_head(m)

    def get_context(self) -> list:
        """获取当前上下文（给 LLM 的消息列表）。"""
        return self.drawer.get_context_items()

    def get_stats(self) -> dict:
        """获取状态统计。"""
        return {
            "round": self.round,
            "drawer_level": self.drawer.current_level,
            "drawer_top_fill": self.drawer.get_top_fill(),
            "temperature": self.temperature.get_stats(),
            "keys": self.keys.get_stats(),
        }


# ── 使用示例 ──────────────────────────────────────────

if __name__ == "__main__":

    def demo_llm(messages):
        """模拟 LLM 调用（用你自己的实现替换）。"""
        # 实际使用时, 替换为:
        # import requests
        # import os
        # response = requests.post(
        #     "https://api.siliconflow.cn/v1/chat/completions",
        #     headers={"Authorization": f"Bearer {os.environ['SILICONFLOW_API_KEY']}"},
        #     json={"model": "Qwen/Qwen3-8B", "messages": messages},
        # )
        # return response.json()["choices"][0]["message"]["content"]
        return "这是一个模拟的摘要输出。"

    comp = MinimalCompressor(llm_call_fn=demo_llm)

    # 模拟几轮对话
    comp.feed("你好")
    comp.feed("我们来设计一个上下文管理系统")
    comp.feed("核心用抽屉级联，N=3")
    comp.feed("TFC-155: 抽屉容量设为4")

    print("=== 上下文条目 ===")
    for item in comp.get_context():
        role = item.get("role", "?")
        content = str(item.get("content", ""))[:80]
        print(f"  [{role}] {content}")

    print("\n=== 状态 ===")
    import json
    print(json.dumps(comp.get_stats(), ensure_ascii=False, indent=2))
