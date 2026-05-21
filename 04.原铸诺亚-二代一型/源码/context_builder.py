#!/usr/bin/env python3
"""上下文组装器 · context_builder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界

固化每次调用4B分析师时的上下文组装规则。
每次调用4B,组装预算不超过3000 Token。
"""

from datetime import datetime
from pathlib import Path

PRIME_ROOT = Path(__file__).parent

# ─── Token估算 ───
def _est_tokens(text: str) -> int:
    """简单Token估算: 中文~1.5字/Token, 英文~4字/Token"""
    if not text:
        return 0
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    en = len(text) - cn
    return int(cn / 1.5 + en / 4)


class ContextBuilder:
    """固化4B分析师每次调用的上下文组装"""

    # 预算分配
    BUDGET = {
        "user_input": 0,          # 不限制
        "project_summary": 300,   # ~200汉字
        "recent_dialogue": 750,   # ~500汉字, 最近3轮
        "version_facts": 750,     # ~500汉字, 当前版本事实
        "iron_rules": 225,        # ~150汉字, 系统铁律精简版
        "total_max": 3000,        # 总Token硬上限
    }

    def build_for_analyst(self, user_input: str,
                          project_context: str = "",
                          recent_memories: list = None,
                          intent_hint: str = "") -> str:
        """组装4B分析师上下文 (阶段1: 思绪整理)"""

        parts = []

        # ① 系统铁律精简版 (固定, 不重复)
        parts.append(_IRON_RULES_SLIM)

        # ② 用户输入 (完整, 不限制)
        parts.append(f"\n【用户输入】\n{user_input}")

        # ③ 当前项目摘要
        if project_context:
            summary = project_context[:200]
            parts.append(f"\n【当前项目】\n{summary}")

        # ④ 最近对话摘要
        if recent_memories:
            mem_text = "\n".join(
                m.get("summary", m.get("content", ""))[:120]
                for m in recent_memories[:3]
            )[:500]
            if mem_text:
                parts.append(f"\n【最近对话摘要】\n{mem_text}")

        # ⑤ 版本管理器最新事实
        try:
            from entity_version_manager import versions
            facts = versions.summary_for_context(max_chars=500)
            if facts and facts != "(无当前事实)":
                parts.append(f"\n【当前事实(最新版)】\n{facts}")
        except Exception:
            pass

        # ⑥ 意图提示
        if intent_hint:
            parts.append(f"\n【意图提示】{intent_hint}")

        combined = "\n".join(parts)

        # Token硬上限截断
        tokens = _est_tokens(combined)
        if tokens > self.BUDGET["total_max"]:
            # 截断对话摘要和事实部分
            combined = self._truncate(combined, self.BUDGET["total_max"])

        return combined

    def build_for_merger(self, llm_response: str, user_input: str,
                         persona_hint: str = "") -> str:
        """组装4B合并员上下文 (阶段5: 回复合并)"""
        parts = [
            f"【大模型回复】\n{llm_response[:2000]}",
            f"\n【用户原始需求】\n{user_input[:500]}",
        ]
        if persona_hint:
            parts.append(f"\n【人格要求】{persona_hint}")
        parts.append("\n请将以上回复润色为自然语言，应用人格风格。不要添加新信息。")
        return "\n".join(parts)

    def _truncate(self, text: str, max_tokens: int) -> str:
        """截断到Token上限"""
        lines = text.split("\n")
        result = []
        current = 0
        for line in lines:
            t = _est_tokens(line)
            if current + t > max_tokens:
                result.append("...[上下文截断，已达Token上限]")
                break
            result.append(line)
            current += t
        return "\n".join(result)


# ─── 系统铁律精简版 (固化, 不随对话增长) ───
_IRON_RULES_SLIM = """【系统铁律·精简版】
1. 只输出纯信息，不含情感共鸣/鼓励/过渡/礼貌用语
2. 事实只认最新版(version_manager)，旧版已废弃
3. 拆解用户意图为独立碎片，每个碎片生成标准工单
4. 敏感信息必须拦截，安全红线不可逾越"""


# ─── 全局实例 ───
ctx = ContextBuilder()


# ─── 测试 ───
if __name__ == "__main__":
    cb = ContextBuilder()

    result = cb.build_for_analyst(
        user_input="帮我备份数据库，然后检查一下有没有报错",
        project_context="NOAH-PRIME 原初铸造世界 v1.0",
        recent_memories=[
            {"summary": "上一轮: 成功执行pg_dump备份"},
            {"summary": "上上轮: 优化了备份脚本"},
        ],
        intent_hint="system_ops",
    )
    print(result)
    print(f"\n--- 估算Token: {_est_tokens(result)} ---")
