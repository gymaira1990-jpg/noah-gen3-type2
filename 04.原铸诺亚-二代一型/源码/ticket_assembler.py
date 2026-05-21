#!/usr/bin/env python3
"""工单组装器 · ticket_assembler.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
按OA逻辑: 不同角色看到不同的工单视图。

三种形态:
  build_for_reviewer() → 0.5B审查员看的审查卡片
  build_for_llm()     → 大模型看的极简工单 (最重要)
  build_for_storage()  → 持久化存储的结构化摘要
"""

import json
from datetime import datetime
from pathlib import Path

PRIME_ROOT = Path(__file__).parent


class TicketAssembler:
    """工单组装器——三种视图，同一数据源"""

    # ═══════════════════════════════════
    # build_for_reviewer: 审查员卡片
    # ═══════════════════════════════════

    def build_for_reviewer(self, ticket: dict) -> str:
        """给0.5B审查员的精简卡片"""
        tl = ticket.get("task_layer", {})
        return json.dumps({
            "ticket_id": ticket.get("ticket_id", ""),
            "ticket_type": ticket.get("ticket_type", ""),
            "intent": tl.get("primary_intent", "")[:100],
            "urgency": tl.get("urgency", "normal"),
            "constraint_level": ticket.get("constraint_level", "high"),
            "checklist": [
                "无敏感信息泄露",
                "格式符合圣典规范",
                "意图清晰可执行",
                "无越权操作",
            ],
        }, ensure_ascii=False)

    # ═══════════════════════════════════
    # build_for_llm: 大模型极简工单 ⭐
    # ═══════════════════════════════════

    def build_for_llm(self, ticket: dict) -> str:
        """给大模型的极简工单——这是纸，价如千金。

        只包含:
          - 任务层: 本次任务是什么
          - 背景层: 仅当前版本事实
          - 要求层: 回复格式 + 纯信息输出规则

        不包含:
          - 对话历史
          - 4B分析过程
          - 0.5B审查记录
          - 废弃版本
          - 其他项目信息
          - 系统内部状态
        """
        tl = ticket.get("task_layer", {})
        al = ticket.get("affective_layer", {})
        ml = ticket.get("meta_layer", {})
        rr = ticket.get("response_requirements", {})

        parts = []

        # ① 核心问题
        intent = tl.get("primary_intent", "")
        task_type = ticket.get("task_type_tag", ticket.get("ticket_type", ""))
        parts.append(f"【核心问题】\n{intent}")

        # ② 必要背景 (仅当前版本事实)
        try:
            from entity_version_manager import versions
            facts = versions.summary_for_context(max_chars=400)
            if facts and facts != "(无当前事实)":
                parts.append(f"\n【必要背景】\n{facts}")
        except Exception:
            pass

        # ③ 回复要求
        parts.append(f"""
【回复要求】
- 输出纯信息: 不含情感共鸣、鼓励、过渡、礼貌用语、不确定铺垫
- 直接给出答案、步骤或方案
- 仅在涉及安全时附加风险提示
- 仅在需要选择时列出选项
- 先给结论，再给必要细节
- 一句话能说清就说一句话""")

        # ④ 参数(如果有)
        params = tl.get("params_extracted", {})
        if params:
            parts.append(f"\n【参数】\n{json.dumps(params, ensure_ascii=False)}")

        # ⑤ 暗含约束: 大模型不知道历史、不知道其他项目、不知道系统状态
        parts.append("""
【暗含约束】
- 你只有本文提供的信息，不要假设额外上下文
- 不要询问"是否需要更详细"——需要的话工单会写明
- 不要复述用户的问题""")

        return "\n".join(parts)

    # ═══════════════════════════════════
    # build_for_storage: 持久化摘要
    # ═══════════════════════════════════

    def build_for_storage(self, ticket: dict, result: dict = None) -> dict:
        """持久化存储的结构化摘要"""
        tl = ticket.get("task_layer", {})
        storage = {
            "ticket_id": ticket.get("ticket_id", ""),
            "ticket_type": ticket.get("ticket_type", ""),
            "task_type_tag": ticket.get("task_type_tag", ""),
            "intent": tl.get("primary_intent", "")[:200],
            "status": "completed",
            "stored_at": datetime.now().isoformat(),
        }
        if result:
            storage["result_summary"] = (result.get("reply", "") or "")[:300]
            storage["tokens_used"] = result.get("tokens", result.get("tokens_used", 0))

        return storage


# ─── 全局实例 ───
assembler = TicketAssembler()


# ─── 测试 ───
if __name__ == "__main__":
    ta = TicketAssembler()

    test_ticket = {
        "ticket_id": "TEST-001",
        "ticket_type": "execution",
        "task_type_tag": "system_ops",
        "constraint_level": "high",
        "task_layer": {
            "primary_intent": "备份数据库并检查是否有报错",
            "urgency": "important",
            "params_extracted": {"target": "noah_prime"},
        },
        "affective_layer": {"user_emotion": "neutral"},
        "response_requirements": {"format": "pure_information"},
    }

    print("=== build_for_reviewer ===")
    print(ta.build_for_reviewer(test_ticket))

    print("\n=== build_for_llm ===")
    print(ta.build_for_llm(test_ticket))

    print("\n=== build_for_storage ===")
    print(json.dumps(ta.build_for_storage(test_ticket,
          {"reply": "备份完成，无报错", "tokens": 150}),
          ensure_ascii=False, indent=2))
