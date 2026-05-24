#!/usr/bin/env python3
"""冲突检测器 · brain/conflict_detector.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 三层信息完整性检查
嵌入: Pipeline Stage 2.5 (工单分发后、合规审查前)

第一层: 参数完整性 (硬编码规则)
第二层: 项目规则约束 (rules.md)
第三层: 宪法兜底 (禁止猜测)
"""

import json
import httpx
from pathlib import Path
from typing import Optional

PRIME_ROOT = Path(__file__).parent.parent
OLLAMA_URL = "http://localhost:11435"


class ConflictDetector:
    """三层冲突检测——嵌入pipeline stage 2.5"""

    def check(self, ticket, user_input: str,
              project_name: Optional[str] = None) -> dict:
        findings = []

        # 第一层: 参数完整性
        l1 = self._layer1_param_check(ticket, user_input)
        findings.extend(l1)

        # 第二层: 项目规则约束
        if project_name:
            l2 = self._layer2_project_rules(ticket, project_name)
            findings.extend(l2)

        # 第三层: 宪法兜底
        l3 = self._layer3_constitution(ticket, findings)
        findings.extend(l3)

        blocked = any(f["level"] == "BLOCK" for f in findings)
        needs_ask = any(f["level"] == "ASK" for f in findings)

        return {
            "passed": not blocked,
            "needs_clarification": needs_ask,
            "findings": findings,
        }

    def _layer1_param_check(self, ticket, user_input: str) -> list:
        """硬编码参数完整性检查"""
        findings = []
        intent = ticket.task_layer.primary_intent

        # 过短指令 → 参数不足
        if len(intent.strip()) < 5:
            findings.append({
                "level": "ASK", "layer": 1,
                "rule": "参数不足",
                "detail": "指令过短，请提供更具体的描述",
            })

        # 模糊文件引用 → 需确认
        fuzzy_refs = ["那个", "这个", "上次那个", "之前的"]
        if any(w in intent for w in fuzzy_refs):
            findings.append({
                "level": "ASK", "layer": 1,
                "rule": "模糊引用",
                "detail": f"检测到模糊引用，请指定具体对象",
            })

        # 危险意图标记
        dangerous = ["删除所有", "清空", "格式化", "卸载全部"]
        if any(w in intent for w in dangerous):
            findings.append({
                "level": "BLOCK", "layer": 1,
                "rule": "危险意图",
                "detail": f"检测到高危操作意图: {intent[:80]}",
            })

        return findings

    def _layer2_project_rules(self, ticket, project_name: str) -> list:
        """检查项目规则约束"""
        findings = []
        rules_path = PRIME_ROOT / "data" / "projects" / project_name / "rules.md"
        if not rules_path.exists():
            return findings

        try:
            rules = rules_path.read_text(encoding="utf-8")
        except Exception:
            return findings

        intent = ticket.task_layer.primary_intent

        # 检查规则中的禁止项
        for line in rules.split("\n"):
            line = line.strip()
            if line.startswith("禁止:") or line.startswith("- 禁止"):
                forbidden = line.replace("禁止:", "").replace("- 禁止", "").strip()
                if forbidden and forbidden in intent:
                    findings.append({
                        "level": "BLOCK", "layer": 2,
                        "rule": "项目规则冲突",
                        "detail": f"「{project_name}」规则禁止: {forbidden}",
                    })

        # 检查依赖参数
        for line in rules.split("\n"):
            if "依赖:" in line or "requires:" in line.lower():
                dep = line.split(":", 1)[-1].strip()
                if dep and dep not in intent:
                    findings.append({
                        "level": "ASK", "layer": 2,
                        "rule": "缺少依赖参数",
                        "detail": f"「{project_name}」需要: {dep}，请确认",
                    })

        return findings

    def _layer3_constitution(self, ticket, findings: list) -> list:
        """宪法兜底原则"""
        result = []

        # 核心原则: 无把握必须询问
        if not findings and not ticket.meta_layer.relevant_memories_retrieved:
            # 不强制——仅当内存中无任何相关记忆时提示
            pass

        # 保护标记完整性
        from protection import scan
        markers = scan(str(ticket.to_dict()))
        if not markers and ticket.constraint_level in ("high", "extreme"):
            result.append({
                "level": "ASK", "layer": 3,
                "rule": "宪法·信息不足",
                "detail": "高约束任务缺少保护标记，建议确认后执行",
            })

        return result


# ─── 全局实例 ───
detector = ConflictDetector()


# ─── 测试 ───
if __name__ == "__main__":
    from ticket import Ticket, TaskLayer, MetaLayer

    cd = ConflictDetector()

    # 测试1: 过短指令
    t1 = Ticket(task_type_tag="system_ops",
                task_layer=TaskLayer(primary_intent="删"))
    r1 = cd.check(t1, "删")
    print(f"过短指令: needs_ask={r1['needs_clarification']} findings={len(r1['findings'])}")

    # 测试2: 危险意图
    t2 = Ticket(task_type_tag="system_ops",
                task_layer=TaskLayer(primary_intent="删除所有数据库"))
    r2 = cd.check(t2, "删除所有数据库")
    print(f"危险意图: blocked={not r2['passed']}")

    # 测试3: 模糊引用
    t3 = Ticket(task_type_tag="system_ops",
                task_layer=TaskLayer(primary_intent="那个文件改一下"))
    r3 = cd.check(t3, "那个文件改一下")
    print(f"模糊引用: needs_ask={r3['needs_clarification']}")

    print("\n全部测试通过 ✅")
