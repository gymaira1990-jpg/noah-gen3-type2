#!/usr/bin/env python3
"""技能熔炉 · skill_forge.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: STC熔炉 (Standard Template Construct Forge)

自动从成功工单中提炼可复用经验模板。
- 扫描评分记录 → 识别高分工单
- 萃取执行模式 → 生成STC技能模板
- 向量化存储 → 语义匹配快速检索
- 统计复用 → 自动进化
"""

import json
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from pg_conn import connect, cursor

PRIME_ROOT = Path(__file__).parent
SKILLS_DIR = PRIME_ROOT / "skills"
SKILLS_DIR.mkdir(exist_ok=True)

# ─── 技能模板格式 ───
SKILL_SCHEMA = {
    "skill_id": "",           # STC-{timestamp}-{hash}
    "name": "",               # 人类可读名称
    "task_type": "",          # system_ops / code_generation / analysis_report / ...
    "trigger_patterns": [],   # 触发关键词
    "steps": [],              # 执行步骤摘要
    "tools_used": [],         # 使用过的工具
    "model_used": "",         # 使用的模型
    "source_tickets": [],     # 来源工单
    "success_rate": 0.0,      # 成功率
    "created_at": "",
    "last_used": None,
    "use_count": 0,
}


class SkillForge:
    """STC熔炉 — 将成功经验淬炼为可复用技能"""

    def __init__(self):
        self.skills: dict = {}  # skill_id → skill dict
        self._loaded = False

    # ═══════════════════════════════════
    # 候选扫描
    # ═══════════════════════════════════

    def scan_candidates(self, min_score: float = 0.8, min_count: int = 2) -> list:
        """扫描评分记录，找出可提炼为技能的工单组"""
        with cursor(dict_cursor=True) as cur:
            # 高分工单
            cur.execute(
                """SELECT sr.ticket_id, sr.efficiency, sr.accuracy, sr.stability,
                          tl.summary, tl.created_at as ticket_created
                   FROM score_records sr
                   LEFT JOIN tickets_log tl ON sr.ticket_id = tl.ticket_id
                   WHERE sr.efficiency >= %s AND sr.accuracy >= %s
                   ORDER BY sr.efficiency DESC""",
                (min_score, min_score),
            )
            high_score_tickets = cur.fetchall()

        if len(high_score_tickets) < min_count:
            return []

        # 按 task_type_tag / summary 关键词 分组
        groups = self._cluster_by_task_type(high_score_tickets)
        return groups

    def _cluster_by_task_type(self, tickets: list) -> list:
        """将高分票按语义聚类 (向量相似度法)"""
        try:
            from memory.pg_search import embed
        except Exception:
            return self._cluster_fallback(tickets)

        # 嵌入所有工单摘要
        summaries = [(t["ticket_id"], (t.get("summary") or "")[:200]) for t in tickets]
        vectors = {}
        for tid, summary in summaries:
            if summary:
                vec = embed(summary)
                if vec and not all(v == 0 for v in vec):
                    vectors[tid] = vec

        if len(vectors) < 2:
            return self._cluster_fallback(tickets)

        # 余弦相似度聚类 (阈值0.75)
        groups = []
        assigned = set()

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            return dot / (norm_a * norm_b) if norm_a and norm_b else 0

        tids_with_vec = list(vectors.keys())
        for i, tid in enumerate(tids_with_vec):
            if tid in assigned:
                continue
            group = {"label": f"cluster_{len(groups)}",
                     "tickets": [tid], "avg_score": 0.0}
            assigned.add(tid)
            # 传递闭包: 检查所有未分配工单与组内任一成员相似
            changed = True
            while changed:
                changed = False
                for j in range(i + 1, len(tids_with_vec)):
                    other = tids_with_vec[j]
                    if other in assigned:
                        continue
                    # 检查other与组内任意成员相似
                    for member in group["tickets"]:
                        if member in vectors and other in vectors:
                            if cosine(vectors[member], vectors[other]) >= 0.75:
                                group["tickets"].append(other)
                                assigned.add(other)
                                changed = True
                                break
            groups.append(group)

        # 加入无向量的工单 (归入最近组)
        for t in tickets:
            tid = t["ticket_id"]
            if tid not in assigned:
                if groups:
                    groups[0]["tickets"].append(tid)
                else:
                    groups.append({"label": "general", "tickets": [tid], "avg_score": 0.0})
                assigned.add(tid)

        # 计算均分
        score_map = {t["ticket_id"]: t["efficiency"] for t in tickets}
        for g in groups:
            scores = [score_map.get(tid, 0.7) for tid in g["tickets"]]
            g["avg_score"] = sum(scores) / max(len(scores), 1)

        return [g for g in groups if len(g["tickets"]) >= 2]

    def _cluster_fallback(self, tickets: list) -> list:
        """降级关键词聚类"""
        ticket_kw = {}
        for t in tickets:
            summary = (t.get("summary") or "")[:80]
            ticket_kw[t["ticket_id"]] = set(self._extract_keywords(summary))

        groups = []
        assigned = set()
        for tid, kw_set in ticket_kw.items():
            if tid in assigned:
                continue
            group = {"label": "|".join(sorted(kw_set)[:3]) or "general",
                     "tickets": [tid], "avg_score": 0.0}
            assigned.add(tid)
            for other_tid, other_kw in ticket_kw.items():
                if other_tid in assigned:
                    continue
                if len(kw_set & other_kw) >= 1:
                    group["tickets"].append(other_tid)
                    assigned.add(other_tid)
            groups.append(group)

        score_map = {t["ticket_id"]: t["efficiency"] for t in tickets}
        for g in groups:
            scores = [score_map.get(tid, 0.7) for tid in g["tickets"]]
            g["avg_score"] = sum(scores) / max(len(scores), 1)

        return [g for g in groups if len(g["tickets"]) >= 2]

    def _extract_keywords(self, text: str) -> list:
        """简单关键词提取 (中英混合分词)"""
        import re
        stop = {"的", "了", "是", "在", "和", "也", "就", "都", "而", "及", "与",
                "着", "或", "一个", "没有", "我们", "你们", "他们", "这个", "那个",
                "用户", "反馈", "原话", "有问题", "可以", "不对", "使用", "然后",
                ":", "：", "、", "。", "，", "！", "？", "|"}

        # ① 按中英边界+标点切分
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z_][a-zA-Z0-9_]*", text)
        # ② 去停用词+短词
        keywords = [t for t in tokens if t not in stop and len(t) >= 2]
        return keywords[:6]

    # ═══════════════════════════════════
    # 锻造技能
    # ═══════════════════════════════════

    def forge(self, ticket_ids: list, skill_name: str = "") -> Optional[dict]:
        """从一组成功工单锻造STC技能模板"""
        if not ticket_ids:
            return None

        with cursor(dict_cursor=True) as cur:
            # ① 收集工单信息
            cur.execute(
                "SELECT ticket_id, summary, status FROM tickets_log WHERE ticket_id = ANY(%s)",
                (ticket_ids,),
            )
            tickets = cur.fetchall()

            # ② 收集API调用信息
            cur.execute(
                "SELECT ticket_id, model, tokens_used, response_summary FROM api_call_logs WHERE ticket_id = ANY(%s)",
                (ticket_ids,),
            )
            api_calls = cur.fetchall()

            # ③ 收集评分
            cur.execute(
                "SELECT ticket_id, efficiency, accuracy, stability FROM score_records WHERE ticket_id = ANY(%s)",
                (ticket_ids,),
            )
            scores = cur.fetchall()

            # ④ 收集工具使用
            cur.execute(
                "SELECT ticket_id, tool_name FROM tool_uses WHERE ticket_id = ANY(%s)",
                (ticket_ids,),
            )
            tool_uses = cur.fetchall()

        if not tickets:
            return None

        # ─── 锻造技能 ───
        # 提取步骤 (从summary + response_summary)
        steps = self._extract_steps(tickets, api_calls)

        # 提取工具
        tools = list(set(t["tool_name"] for t in tool_uses))

        # 提取模型
        models = list(set(c["model"] for c in api_calls if c.get("model")))
        model = models[0] if models else "deepseek-v4-flash"

        # 提取触发模式
        summaries = [t.get("summary", "") for t in tickets]
        triggers = self._extract_triggers(summaries)

        # 任务类型 (从工单内容推断)
        task_type = self._infer_task_type(summaries, tools)

        # 成功率
        avg_score = sum(s.get("efficiency", 0.7) for s in scores) / max(len(scores), 1)
        all_statuses = [t.get("status", "") for t in tickets]
        success_rate = sum(1 for s in all_statuses if s in ("user_confirmed_good", "completed")) / max(len(all_statuses), 1)

        # 生成技能ID
        ts = datetime.now().strftime("%Y%m%d%H%M")
        skill_id = f"STC-{ts}-{abs(hash('|'.join(ticket_ids))) % 10000:04d}"

        skill = {
            "skill_id": skill_id,
            "name": skill_name or f"自动提炼:{triggers[0] if triggers else '通用'}",
            "task_type": task_type,
            "trigger_patterns": triggers,
            "steps": steps,
            "tools_used": tools,
            "model_used": model,
            "source_tickets": ticket_ids,
            "success_rate": round(success_rate, 3),
            "avg_score": round(avg_score, 3),
            "created_at": datetime.now().isoformat(),
            "last_used": None,
            "use_count": 0,
        }

        # ─── 持久化 ───
        self._save_skill(skill)
        self._embed_skill(skill)

        return skill

    def _extract_steps(self, tickets: list, api_calls: list) -> list:
        """从工单摘要提取执行步骤"""
        steps = []
        seen = set()
        for t in tickets:
            summary = (t.get("summary") or "").strip()
            if summary and "用户反馈" not in summary and summary not in seen:
                # 拆分为步骤
                for line in summary.replace("；", "。").replace("|", "。").split("。"):
                    line = line.strip()
                    if len(line) > 5 and line not in seen:
                        steps.append(line)
                        seen.add(line)
        return steps[:8]  # 最多8步

    def _extract_triggers(self, summaries: list) -> list:
        """从摘要提取触发模式"""
        all_kw = []
        for s in summaries:
            all_kw.extend(self._extract_keywords(s))
        # 取高频词
        from collections import Counter
        freq = Counter(all_kw)
        return [w for w, _ in freq.most_common(5)]

    def _infer_task_type(self, summaries: list, tools: list) -> str:
        """推断任务类型"""
        combined = " ".join(summaries)
        if any(k in combined for k in ["代码", "code", "编程", "函数", "类"]):
            return "code_generation"
        if any(k in combined for k in ["写", "创作", "故事", "文章"]):
            return "creative_writing"
        if any(k in combined for k in ["分析", "报告", "查询", "查看"]):
            return "analysis_report"
        if any(k in combined for k in ["对话", "聊天", "情感"]):
            return "emotional_chat"
        return "system_ops"

    # ═══════════════════════════════════
    # 持久化
    # ═══════════════════════════════════

    def _save_skill(self, skill: dict):
        """保存为JSON文件"""
        filepath = SKILLS_DIR / f"{skill['skill_id']}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(skill, f, ensure_ascii=False, indent=2)

    def _embed_skill(self, skill: dict):
        """向量化并存入PG"""
        try:
            from memory.pg_search import embed

            # 构建搜索文本: 名称 + 触发词 + 步骤
            search_text = f"{skill['name']} {' '.join(skill['trigger_patterns'])} {' '.join(skill['steps'][:3])}"
            vec = embed(search_text)

            if vec and not all(v == 0 for v in vec):
                with cursor() as cur:
                    cur.execute(
                        """INSERT INTO knowledge_entries (content, embedding, category, tags, source)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (id) DO NOTHING""",
                        (
                            f"[STC技能] {skill['name']}\n触发: {', '.join(skill['trigger_patterns'])}\n步骤: {'; '.join(skill['steps'][:5])}",
                            vec,
                            "skill_template",
                            [skill["task_type"], "stc", f"score_{skill['avg_score']}"],
                            f"skill_forge:{skill['skill_id']}",
                        ),
                    )
        except Exception:
            pass

    # ═══════════════════════════════════
    # 检索匹配
    # ═══════════════════════════════════

    def match(self, query: str, top_k: int = 3, threshold: float = 0.45) -> list:
        """语义匹配已有技能"""
        self._ensure_loaded()

        # ① 向量检索
        try:
            from memory.pg_search import search_semantic
            results = search_semantic(f"[STC技能匹配] {query}", top_k=top_k, threshold=threshold)
        except Exception:
            results = []

        # ② 过滤skill类别的结果，加载完整技能
        matched_skills = []
        for r in results:
            if r.get("category") == "skill_template" or "stc" in str(r.get("tags", [])):
                # 从source提取skill_id
                source = r.get("source", "")
                if "skill_forge:" in source:
                    skill_id = source.split("skill_forge:")[-1]
                    skill = self.load_skill(skill_id)
                    if skill:
                        skill["_match_similarity"] = r.get("similarity", 0)
                        matched_skills.append(skill)

        # ③ 降级: 关键词匹配
        if not matched_skills:
            matched_skills = self._keyword_match(query)

        return matched_skills

    def _keyword_match(self, query: str) -> list:
        """关键词匹配降级检索 (含子串+字符重叠)"""
        self._ensure_loaded()
        matched = []
        for skill in self.skills.values():
            triggers = skill.get("trigger_patterns", [])
            name = skill.get("name", "")
            score = 0
            for t in triggers:
                if t in query or query in t:
                    score += 0.35
                else:
                    # 字符重叠度匹配 (中文字符集交集)
                    t_chars = set(t)
                    q_chars = set(query)
                    overlap = len(t_chars & q_chars)
                    if overlap >= 2:
                        score += 0.1 * min(overlap, 5)
            if any(k in query for k in name.split(":")):
                score += 0.2
            if score > 0.15:
                skill["_match_similarity"] = min(score, 1.0)
                matched.append(skill)
        return sorted(matched, key=lambda s: s.get("_match_similarity", 0), reverse=True)[:3]

    def load_skill(self, skill_id: str) -> Optional[dict]:
        """加载单个技能"""
        filepath = SKILLS_DIR / f"{skill_id}.json"
        if filepath.exists():
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        return None

    def _ensure_loaded(self):
        """懒加载所有技能到内存"""
        if self._loaded:
            return
        for fp in SKILLS_DIR.glob("STC-*.json"):
            try:
                with open(fp, encoding="utf-8") as f:
                    skill = json.load(f)
                    self.skills[skill["skill_id"]] = skill
            except Exception:
                pass
        self._loaded = True

    # ═══════════════════════════════════
    # 技能应用
    # ═══════════════════════════════════

    def apply(self, skill_id: str, context: str = "") -> str:
        """应用技能模板——生成可直接执行的指令"""
        skill = self.load_skill(skill_id)
        if not skill:
            return ""

        # 更新使用统计
        skill["use_count"] = skill.get("use_count", 0) + 1
        skill["last_used"] = datetime.now().isoformat()
        self._save_skill(skill)

        # 生成执行指令
        prompt = (
            f"[STC技能应用] 技能: {skill['name']}\n"
            f"类型: {skill['task_type']}\n"
            f"步骤:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(skill['steps'])) +
            f"\n推荐工具: {', '.join(skill['tools_used']) if skill['tools_used'] else '无'}"
            f"\n推荐模型: {skill['model_used']}"
            f"\n成功率: {skill['success_rate']*100:.0f}%"
        )
        if context:
            prompt += f"\n\n当前上下文: {context[:300]}"

        return prompt

    def list_all(self) -> list:
        """列出所有技能摘要"""
        self._ensure_loaded()
        return [
            {
                "skill_id": s["skill_id"],
                "name": s["name"],
                "task_type": s["task_type"],
                "success_rate": s.get("success_rate", 0),
                "use_count": s.get("use_count", 0),
                "steps_count": len(s.get("steps", [])),
            }
            for s in self.skills.values()
        ]

    # ═══════════════════════════════════
    # 自动锻造 (供SSMP调用)
    # ═══════════════════════════════════

    def auto_forge(self, min_score: float = 0.75) -> dict:
        """自动扫描并锻造新技能"""
        groups = self.scan_candidates(min_score=min_score, min_count=2)
        forged = []
        skipped = []

        for g in groups:
            # 检查是否已存在类似技能
            existing = self.match(" ".join(g["tickets"]))
            if existing and existing[0].get("_match_similarity", 0) > 0.8:
                skipped.append(g["label"])
                continue

            skill = self.forge(g["tickets"])
            if skill:
                forged.append(skill["skill_id"])

        return {
            "scanned_groups": len(groups),
            "forged": forged,
            "skipped_existing": skipped,
            "timestamp": datetime.now().isoformat(),
        }


# ─── 全局实例 ───
forge = SkillForge()


# ─── 测试 ───
if __name__ == "__main__":
    f = SkillForge()

    # 扫描候选
    print("=== 候选扫描 ===")
    candidates = f.scan_candidates(min_score=0.6, min_count=2)
    if candidates:
        for c in candidates:
            print(f"  {c['label']}: {len(c['tickets'])}票, 均分{c['avg_score']:.2f}")
            # 锻造第一个
            skill = f.forge(c["tickets"])
            if skill:
                print(f"  → 锻造技能: {skill['skill_id']} {skill['name']}")
    else:
        print("  候选不足 (需≥2个高分工单)")

    # 列出技能
    print("\n=== 已有技能 ===")
    for s in f.list_all():
        print(f"  {s['skill_id']} | {s['name']} | {s['task_type']} | 成功率{s['success_rate']*100:.0f}%")

    # 测试匹配
    print("\n=== 技能匹配测试 ===")
    test_queries = ["备份数据库", "检查系统状态", "写一个Python函数"]
    for q in test_queries:
        matches = f.match(q)
        if matches:
            print(f"  「{q}」→ 命中: {matches[0]['name']} (相似度{matches[0].get('_match_similarity', 0):.2f})")
        else:
            print(f"  「{q}」→ 无匹配技能")
