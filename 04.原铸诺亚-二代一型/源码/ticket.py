#!/usr/bin/env python3
"""工单系统 · ticket.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 圣典诏令 (Codex Edict)

工单格式遵循 诺亚生命计划 · 第一阶段 §4.1 标准
"""

import json
import uuid
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Optional, List

TICKET_TYPES = ["execution", "query", "emotional", "review", "planning", "maintenance"]
TASK_TAGS = ["creative_writing", "code_generation", "system_ops", "emotional_chat", "analysis_report"]
CONSTRAINT_LEVELS = ["low", "medium", "medium_high", "high", "extreme"]
URGENCY_LEVELS = ["normal", "important", "critical"]


@dataclass
class AffectiveLayer:
    user_emotion: str = "neutral"
    expected_tone: str = "warm"
    social_context: str = ""


@dataclass
class TaskLayer:
    primary_intent: str = ""
    sub_tasks: List[str] = field(default_factory=list)
    params_extracted: dict = field(default_factory=dict)
    urgency: str = "normal"
    tools_required: List[str] = field(default_factory=list)
    tools_used_in_execution: List[str] = field(default_factory=list)


@dataclass
class MetaLayer:
    relevant_memories_retrieved: bool = False
    memory_ids: List[str] = field(default_factory=list)
    project_hint: Optional[str] = None
    expert_team_required: bool = False


@dataclass
class ResponseRequirements:
    format: str = "markdown"
    max_steps: int = 5
    must_include: List[str] = field(default_factory=lambda: ["action_plan"])
    forbidden_phrases: List[str] = field(default_factory=list)


@dataclass
class Ticket:
    ticket_id: str = ""
    ticket_type: str = "execution"
    created_at: str = ""
    source_module: str = "analyst_4b"
    task_type_tag: str = "system_ops"
    constraint_level: str = "high"
    affective_layer: AffectiveLayer = field(default_factory=AffectiveLayer)
    task_layer: TaskLayer = field(default_factory=TaskLayer)
    meta_layer: MetaLayer = field(default_factory=MetaLayer)
    response_requirements: ResponseRequirements = field(default_factory=ResponseRequirements)

    def __post_init__(self):
        if not self.ticket_id:
            self.ticket_id = f"{datetime.now().strftime('%Y%m%d')}-NOA-{uuid.uuid4().hex[:4]}"
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def to_protected(self) -> str:
        """包装为保护标记 <<TICKET>>"""
        return f"<<TICKET>>\n{self.to_json()}\n<</TICKET>>"

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        return cls(
            ticket_id=data.get("ticket_id", ""),
            ticket_type=data.get("ticket_type", "execution"),
            created_at=data.get("created_at", ""),
            source_module=data.get("source_module", "analyst_4b"),
            task_type_tag=data.get("task_type_tag", "system_ops"),
            constraint_level=data.get("constraint_level", "high"),
            affective_layer=AffectiveLayer(**data.get("affective_layer", {})),
            task_layer=TaskLayer(**data.get("task_layer", {})),
            meta_layer=MetaLayer(**data.get("meta_layer", {})),
            response_requirements=ResponseRequirements(**data.get("response_requirements", {})),
        )

    def validate(self) -> dict:
        """验证工单合法性"""
        errors = []
        if self.ticket_type not in TICKET_TYPES:
            errors.append(f"ticket_type 非法: {self.ticket_type}")
        if self.task_type_tag not in TASK_TAGS:
            errors.append(f"task_type_tag 非法: {self.task_type_tag}")
        if self.constraint_level not in CONSTRAINT_LEVELS:
            errors.append(f"constraint_level 非法: {self.constraint_level}")
        if self.task_layer.urgency not in URGENCY_LEVELS:
            errors.append(f"urgency 非法: {self.task_layer.urgency}")
        if not self.task_layer.primary_intent:
            errors.append("primary_intent 不能为空")
        # 人称铁律: 工单中禁止"你""我"
        intent = self.task_layer.primary_intent
        if intent and ("你" in intent or "我" in intent):
            errors.append("人称铁律违规: 工单中禁止使用'你'或'我'")
        return {"valid": len(errors) == 0, "errors": errors}


def route(ticket: Ticket, task_matrix: dict) -> str:
    """工单路由：查task_type_matrix决定模型"""
    tag = ticket.task_type_tag
    if tag in task_matrix:
        return task_matrix[tag].get("router", "need_clarification")
    return "need_clarification"


# ─── 测试 ───
if __name__ == "__main__":
    t = Ticket(
        ticket_type="execution",
        task_type_tag="system_ops",
        constraint_level="high",
        task_layer=TaskLayer(
            primary_intent="备份数据库",
            sub_tasks=["dump PG", "compress", "store"],
            urgency="important",
        ),
        meta_layer=MetaLayer(project_hint="NOAH-PRIME"),
    )
    print("工单验证:", t.validate())
    print("路由结果:", route(t, {
        "system_ops": {"router": "brain_deepseek"},
        "creative_writing": {"router": "brain_doubao"},
    }))
    print("\n保护标记格式:\n", t.to_protected()[:200])
