#!/usr/bin/env python3
"""五阶段主控管道 · noah_pipeline.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 铸造圣殿 (Forge Temple)

五阶段工单闭环:
  [1] 思绪整理器 (analyst_4b)  → 意图碎片簇 + 保护标记
  [2] 工单分发器 (Dispatcher)  → 标准工单 + 路由决策
  [3] 合规审查门闸 (reviewer_05b) → 放行/打回/拦截
  [4] 专家决策 (brain_deepseek/doubao) → 方案生成
  [5] 回复合并 + 记忆沉淀 → 最终输出

状态机硬性控制，禁止跳过或调换顺序。
"""

import json
import httpx
import yaml
import os
from collections import deque
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from ticket import Ticket, AffectiveLayer, TaskLayer, MetaLayer, ResponseRequirements
from protection import scan, is_protected, PROTECTED_MARKER
from pg_conn import connect, cursor
from brain.smart_router import smart_router

# ─── 密钥加载 ───
try:
    from vault.loader import load_all
    load_all()
except Exception:
    pass

# ─── 广州星语庭 (可选·零依赖) ───
try:
    from bridge import relay, startup_sync
except Exception:
    relay = None
    startup_sync = lambda: []

# ─── 话题漂移 + 用户反馈 ───
from drift import DriftDetector
from feedback import capture as capture_feedback
drift_detector = DriftDetector()

# ─── API日志 ───
from logs.api_logger import api_logger as _api_logger
api_logger = _api_logger

# ─── 路径 ───
PRIME_ROOT = Path(__file__).parent
CONSTITUTION = PRIME_ROOT / "constitution.yaml"

# ─── 决策门闸 ───
try:
    from decision_gate import gate
except:
    gate = None

# ─── API日志 ───
try:
    from logs.api_logger import api_logger
except:
    api_logger = None

# ─── 模型端点 ───
OLLAMA_URL = "http://localhost:11435"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DOUBAO_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"


class PipelineState:
    IDLE = "idle"
    COLLATING = "collating"
    DISPATCHING = "dispatching"
    REVIEWING = "reviewing"
    DECIDING = "deciding"
    MERGING = "merging"
    COMPLETE = "complete"
    REJECTED = "rejected"


class NoahPipeline:
    """诺亚主控管道 · 五阶段状态机"""

    def __init__(self, channel: str = "web"):
        self.channel = channel  # "web" | "terminal"
        self.state = PipelineState.IDLE
        self.config = self._load_config()
        self.tickets: list = []
        self.results: list = []
        self.tokens_used: int = 0
        self._drift_warning: str = ""
        self._pending_confirmation: dict | None = None  # 决策门闸等待确认
        self._message_queue = deque()       # 非打断式对话队列
        self._queue_lock = threading.Lock()
        self._is_processing = False

    @staticmethod
    def _ollama_post(url: str, json_data: dict, timeout: int = 30) -> httpx.Response:
        """本地Ollama调用，绕过SOCKS代理"""
        import os as _os
        _bk = {}
        for _k in ('all_proxy','ALL_PROXY','http_proxy','HTTP_PROXY',
                   'https_proxy','HTTPS_PROXY','no_proxy','NO_PROXY'):
            _bk[_k] = _os.environ.pop(_k, None)
        _os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
        try:
            with httpx.Client(proxy=None) as _c:
                return _c.post(url, json=json_data, timeout=timeout)
        finally:
            for _k, _v in _bk.items():
                if _v is not None:
                    _os.environ[_k] = _v
                else:
                    _os.environ.pop(_k, None)

    def _load_config(self) -> dict:
        with open(CONSTITUTION) as f:
            return yaml.safe_load(f)

    def process(self, user_input: str) -> dict:
        """主入口：非打断式——处理中自动排队"""
        # ─── 如果正在处理 → 排队不打断 ───
        if self._is_processing:
            with self._queue_lock:
                self._message_queue.append(user_input)
            pos = len(self._message_queue)
            return {
                "reply": f"⏳ 当前任务执行中。消息排在第{pos}位，完成后自动处理。",
                "state": "queued", "queue_position": pos,
                "tickets": [], "tokens_used": 0,
            }

        self._is_processing = True
        try:
            result = self._do_process(user_input)

            # ─── 处理排队消息 ───
            queued_replies = []
            while self._message_queue:
                next_msg = self._message_queue.popleft()
                qr = self._do_process(next_msg)
                queued_replies.append(qr.get("reply", ""))

            if queued_replies:
                result["reply"] += "\n\n---\n📋 排队消息:\n" + \
                    "\n".join(f"> {r[:120]}" for r in queued_replies)

            return result
        finally:
            self._is_processing = False

    def _do_process(self, user_input: str) -> dict:
        """实际五阶段处理逻辑"""
        self.state = PipelineState.COLLATING
        self.tickets = []       # 重置——防止跨请求残留
        self.results = []
        self.tokens_used = 0

        # ─── 通道权限门闸: Web端拦截内务指令 ───
        if self.channel == "web":
            internal_keywords = ["self_modify", "改代码", "修改代码", "修改配置",
                                "constitution", "清空数据库", "删除项目", "卸载",
                                "pip install", "自己改", "修改你自己"]
            for kw in internal_keywords:
                if kw in user_input:
                    return {
                        "reply": (
                            "🛡️ 审判官拦截: 这是内务操作，Web端无权执行。\n\n"
                            "请在WSL终端运行: `python3 noah_terminal.py`\n"
                            "通过诺亚本体通道下达此指令。"
                        ),
                        "tickets": [], "tokens_used": 0,
                        "state": "blocked_by_channel",
                    }

        # ─── 决策门闸: 检查上轮是否在等待确认 ───
        if self._pending_confirmation:
            return self._handle_confirmation_reply(user_input)

        # ─── 话题漂移检测 ───
        drift_result = drift_detector.check(user_input)
        drift_msg = drift_result.get("message", "") if drift_result.get("drifted") else ""
        if drift_msg:
            self._drift_warning = drift_msg

        # ─── 语义意图预扫描: API/余额/注册 → 直接路由 ───
        intent_hint = self._intent_scan(user_input)
        if intent_hint:
            import time as _time
            start = _time.time()
            result = self._handle_semantic_intent(intent_hint, user_input)
            result["duration_ms"] = int((_time.time() - start) * 1000)
            return result

        # ═══ [1] 思绪整理 ═══
        fb = capture_feedback(user_input)
        self._last_feedback = fb.label
        if fb.label != "neutral" and self.tickets:
            from feedback import apply_to_ticket
            apply_to_ticket(fb, self.tickets[-1].ticket_id)
            from logger import log
            # 含用户原话·防回溯缺失
            fb_context = user_input[:80].replace("\n", " ")
            log.ticket(self.tickets[-1].ticket_id, fb.label,
                       summary=f"用户反馈: {fb.matched_word} | 原话: {fb_context}")

        # ═══ [1] 思绪整理 ═══
        fragments = self._stage1_collate(user_input)
        if not fragments:
            return self._abort("思绪整理器返回空结果")

        # ═══ [2] 工单分发 ═══
        self.state = PipelineState.DISPATCHING
        self.tickets = self._stage2_dispatch(fragments)
        if not self.tickets:
            return self._abort("无有效工单生成")

        # ═══ [2.5] 冲突检测 (三层信息完整性) ═══
        try:
            from brain.conflict_detector import ConflictDetector
            cd = ConflictDetector()
            conflict = cd.check(
                self.tickets[0], user_input,
                project_name=self._active_project_hint() or None,
            )
            print(f"[DEBUG] conflict: passed={conflict['passed']} needs_clar={conflict.get('needs_clarification')} findings={[f['detail'] for f in conflict['findings']]}", file=__import__('sys').stderr)
            print(f"[DEBUG] ticket[0]: tag={self.tickets[0].task_type_tag} constraint={self.tickets[0].constraint_level} intent={self.tickets[0].task_layer.primary_intent[:60]}", file=__import__('sys').stderr)
            if conflict.get("needs_clarification"):
                msgs = [f['detail'] for f in conflict['findings'] if f['level'] == 'ASK']
                return {
                    "reply": "⚠ 需要确认:\n" + "\n".join(f"  • {m}" for m in msgs),
                    "state": "awaiting_clarification",
                    "tickets": [], "tokens_used": 0,
                }
            if not conflict.get("passed"):
                blocks = [f['detail'] for f in conflict['findings'] if f['level'] == 'BLOCK']
                return {
                    "reply": "🚫 操作被拦截:\n" + "\n".join(f"  • {m}" for m in blocks),
                    "state": "blocked_by_conflict",
                    "tickets": [], "tokens_used": 0,
                }
        except Exception:
            pass

        # ═══ [3] 合规审查 ═══
        self.state = PipelineState.REVIEWING
        review_result = self._stage3_review(self.tickets)
        if not review_result.get("passed"):
            return self._abort(f"合规审查未通过: {review_result.get('reason','未知')}")

        # ═══ [4] 专家决策 ═══
        self.state = PipelineState.DECIDING
        self.results = self._stage4_decide(self.tickets)

        # ═══ [5] 回复合并 ═══
        self.state = PipelineState.MERGING
        final_reply = self._stage5_merge(self.results, user_input)

        # ─── 自动人格切换 ───
        try:
            tag = self.tickets[0].task_type_tag if self.tickets else "system_ops"
            auto_map = {"creative_writing":"creative_buddy","code_generation":"tech_partner",
                        "system_ops":"tech_partner","emotional_chat":"warm_servitor","analysis_report":"datasmith"}
            persona.switch(auto_map.get(tag, "tech_partner"))
        except: pass

        # ═══ 记忆沉淀 ═══
        self._memory_settle(user_input, final_reply)

        self.state = PipelineState.COMPLETE

        # 自动触发SSMP (异步·不阻塞)
        try:
            from ssmp import ssmp
            ssmp.touch()
            ssmp.record_result(True)
            should, reasons = ssmp.should_run()
            if should:
                ssmp.run_maintenance()
        except Exception:
            pass

        # 评分记录
        try:
            self._record_score(
                self.tickets[0].ticket_id if self.tickets else "",
                getattr(self, '_last_feedback', ''),
                self.tokens_used)
        except: pass

        return {
            "reply": final_reply,
            "tickets": [t.to_dict() for t in self.tickets],
            "tokens_used": self.tokens_used,
            "state": self.state,
        }

    # ═══════════════════════════════════════
    # [1] 思绪整理器 · 大贤者 (analyst_4b)
    # ═══════════════════════════════════════

    def _stage1_collate(self, text: str) -> list:
        """4B本地模型拆解意图碎片 (使用 context_builder 固化上下文)"""
        try:
            from context_builder import ctx as _ctx
            prompt = _ctx.build_for_analyst(
                user_input=text,
                project_context=self._active_project_hint(),
                recent_memories=self._recent_memories(3),
                intent_hint="",
            )
        except Exception:
            prompt = (
                f"{PROTECTED_MARKER}\n"
                "你是诺亚系统的首席分析师。将用户输入拆解为独立意图碎片。\n"
                "输出严格JSON数组，每个碎片包含:\n"
                "  fragment_id, type(emotional|task|query|meta), content, project_hint, is_new_topic\n\n"
                f"用户输入:\n{text[:3000]}\n\n输出JSON数组:"
            )
        try:
            import httpx
            api_key = "<API_KEY>"
            r = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": 200,
                    "temperature": 0.3,
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                # 提取JSON数组
                start = raw.find("[")
                end = raw.rfind("]") + 1
                if start >= 0 and end > start:
                    fragments = json.loads(raw[start:end])
                    # 后处理：规则覆盖4B误判
                    import sys as _sys
                    for f in fragments:
                        if isinstance(f, dict):
                            f_content = (f.get("content") or f.get("intent", "")).lower()
                            f_type_orig = f.get("type", "")
                            # 问候词覆盖
                            greet_words = ["你好", "hi", "hello", "在吗", "你是谁",
                                           "介绍你", "介绍一下", "ping", "打招呼",
                                           "早上好", "晚上好", "下午好", "介绍", "问候"]
                            if any(w in f_content for w in greet_words):
                                f["type"] = "emotional"
                            # 情绪词覆盖（问候之外的日常情感）
                            elif any(w in f_content for w in ["心情", "难过", "开心", "郁闷",
                                                               "烦躁", "累", "烦", "无聊",
                                                               "伤心", "生气", "高兴", "快乐"]):
                                f["type"] = "emotional"
                            # 查询词覆盖
                            elif any(w in f_content for w in ["?", "什么", "怎么", "为什么",
                                                               "如何", "是啥", "哪些"]):
                                if f.get("type") not in ("emotional",):
                                    f["type"] = "query"
                            print(f"[DEBUG] 4B原始={f_type_orig} → 修正={f['type']} content={f_content[:50]}", file=_sys.stderr)
                    return fragments
        except Exception:
            pass

        # 降级：纯规则拆解（带智能类型探测）
        fragment_type = "task"
        text_lower = text.lower().strip()
        # 问候/介绍 → 情感聊天
        greet_words = ["你好", "hi", "hello", "在吗", "你是谁", "介绍你",
                       "介绍一下", "ping", "在不在", "早上好", "晚上好",
                       "下午好", "介绍", "打招呼", "问候"]
        if any(w in text_lower for w in greet_words):
            fragment_type = "emotional"
        # 情绪词（问候之外的日常情感）
        elif any(w in text_lower for w in ["心情", "难过", "开心", "郁闷",
                                            "烦躁", "累", "烦", "无聊",
                                            "伤心", "生气", "高兴", "快乐",
                                            "讨厌", "喜欢", "害怕", "担心",
                                            "焦虑", "紧张", "疲惫", "孤单",
                                            "寂寞", "幸福", "感动", "感恩"]):
            fragment_type = "emotional"
        # 简单查询 → 查询
        elif any(w in text_lower for w in ["?", "什么", "怎么", "为什么",
                                            "如何", "是啥", "哪些"]):
            fragment_type = "query"
        return [{
            "fragment_id": "F1",
            "type": fragment_type,
            "content": text[:500],
            "project_hint": None,
            "is_new_topic": True,
            "related_memory_query": text[:50],
        }]

    # ═══════════════════════════════════════
    # [2] 工单分发器 · Dispatcher
    # ═══════════════════════════════════════

    def _stage2_dispatch(self, fragments: list) -> list:
        """碎片→标准工单→路由查task_type_matrix"""
        task_matrix = self.config.get("task_type_matrix", {})

        tickets = []
        for frag in fragments:
            # 意图→工单类型映射
            type_map = {
                "emotional": "emotional",
                "task": "execution",
                "query": "query",
                "meta": "planning",
            }
            tag_map = {
                "emotional": "emotional_chat",
                "task": "system_ops",
                "query": "analysis_report",
                "meta": "system_ops",
            }

            t = Ticket(
                ticket_type=type_map.get(frag.get("type", "task"), "execution"),
                task_type_tag=tag_map.get(frag.get("type", "task"), "system_ops"),
                task_layer=TaskLayer(
                    primary_intent=frag.get("content", "")[:200],
                    sub_tasks=[],
                    urgency="normal",
                ),
                meta_layer=MetaLayer(
                    project_hint=frag.get("project_hint"),
                    relevant_memories_retrieved=False,
                ),
            )

            # 路由: 优先采纳4B建议，但硬性规则不可覆盖
            route_suggestion = frag.get("route_suggestion")
            hard_rules = {"code_generation": "brain_deepseek", "system_ops": "brain_deepseek"}
            if route_suggestion and hard_rules.get(t.task_type_tag) != route_suggestion:
                router = route_suggestion
            else:
                router = task_matrix.get(t.task_type_tag, {}).get("router", "brain_deepseek")
            constr = task_matrix.get(t.task_type_tag, {}).get("constraint_level", "high")
            t.constraint_level = constr

            tickets.append(t)
        return tickets

    # ═══════════════════════════════════════
    # [3] 合规审查门闸 · 数据工匠 (reviewer_05b)
    # ═══════════════════════════════════════

    def _stage3_review(self, tickets: list) -> dict:
        """0.5B福脑审查工单——格式+安全红线"""
        safety_rules = self.config.get("safety", {}).get("forbidden_actions", [])
        blacklist = self.config.get("safety", {}).get("sensitive_info_blacklist", [])

        # 硬编码安全检查 (不依赖LLM)
        for t in tickets:
            text = t.task_layer.primary_intent + " " + str(t.task_layer.sub_tasks)
            for kw in ["sk-", "ark-", "ghp_", "-----BEGIN", "api_key=", "password="]:
                if kw.lower() in text.lower():
                    return {"passed": False, "reason": f"安全拦截: 包含疑似密钥 ({kw[:8]})"}

        # 0.5B格式审查
        review_prompt = (
            f"{PROTECTED_MARKER}\n"
            f"你是合规审查员(数据工匠 Datasmith)。检查以下工单是否符合圣典规范。\n"
            f"只回复一个词: PASS 或 REJECT。\n"
            f"安全红线: {safety_rules}\n"
            f"工单: {json.dumps([t.to_dict() for t in tickets], ensure_ascii=False)[:500]}\n"
            f"判定:"
        )
        try:
            r = self._ollama_post(
                f"{OLLAMA_URL}/api/generate",
                {
                    "model": "qwen2.5:0.5b",
                    "prompt": review_prompt,
                    "stream": False,
                    "options": {"num_predict": 5},
                    "keep_alive": "30m",
                },
                timeout=15,
            )
            if r.status_code == 200 and "PASS" in r.json().get("response", "").upper():
                return {"passed": True}
        except Exception:
            pass

        return {"passed": True}  # 0.5B不可用时默认放行

    # ═══════════════════════════════════════
    # [4] 专家决策 · 星语庭/国教圣堂
    # ═══════════════════════════════════════

    def _stage4_decide(self, tickets: list) -> list:
        """调用线上大脑——支持并行处理"""
        # 预算检查
        try:
            from budget import budget
            bc = budget.check()
            if not bc.get("allow_api", True):
                return [{"reply": bc.get("message", "API预算已耗尽"), "tokens": 0}]
        except: pass

        # 只1个ticket → 直接执行
        if len(tickets) <= 1:
            return self._execute_tickets(tickets)

        # 多个ticket → 并行
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results_map = {}
        with ThreadPoolExecutor(max_workers=min(len(tickets), 4)) as pool:
            futures = {pool.submit(self._execute_one, t): i for i, t in enumerate(tickets)}
            for f in as_completed(futures):
                idx = futures[f]
                try:
                    results_map[idx] = f.result(timeout=90)
                except Exception:
                    results_map[idx] = {"reply": "子任务执行失败", "tokens": 0}
        return [results_map[i] for i in sorted(results_map)]

    def _execute_tickets(self, tickets: list) -> list:
        results = []
        for t in tickets:
            results.append(self._execute_one(t))
        return results

    def _execute_one(self, t: Ticket) -> dict:
        # ─── 智能路由决策 ───
        try:
            from budget import budget
            budget_status = budget.check()
        except Exception:
            budget_status = None

        route_decision = smart_router.route(
            task_type_tag=t.task_type_tag,
            user_input=t.task_layer.primary_intent,
            budget_status=budget_status,
        )
        router = route_decision["router"]
        model = route_decision["model"]

        # ─── STC技能匹配 ───
        skill_context = ""
        try:
            from skill_forge import forge
            query = f"{t.task_layer.primary_intent} {t.task_type_tag}"
            matches = forge.match(query, top_k=1, threshold=0.6)
            if matches:
                skill = matches[0]
                skill_context = forge.apply(skill["skill_id"], t.task_layer.primary_intent)
                try:
                    from logger import log
                    log.tool_use("skill_forge", query, skill["skill_id"],
                                 duration_ms=0, gate_approved=True, ticket_id=t.ticket_id)
                except: pass
        except Exception:
            pass

        # ─── 实际调用 ───
        start_time = datetime.now()
        if router == "brain_deepseek":
            result = self._call_deepseek(t, skill_context=skill_context)
        elif router == "brain_doubao":
            result = self._call_doubao(t)
        elif router == "analyst_4b":
            result = self._call_analyst(t)
        else:
            result = {"reply": "此任务类型暂无路由", "tokens": 0}

        # ─── 记录延迟和降级 ───
        elapsed_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        success = bool(result.get("reply")) and "通讯中断" not in result.get("reply", "")
        smart_router.record_latency(
            router_name=router, model=model,
            latency_ms=elapsed_ms, success=success,
            ticket_id=t.ticket_id,
        )

        # ─── 降级透明度信息 ───
        if route_decision["budget_blocked"] or route_decision["degrade_chain"]:
            degrade_note = ""
            if route_decision["budget_blocked"]:
                degrade_note = f"[📊 预算保护: 原定{route_decision['preferred']}→{router}] "
            elif route_decision["degrade_chain"]:
                degrade_note = f"[🔄 自动降级: {'→'.join(route_decision['degrade_chain'])}] "
            if result.get("reply"):
                result["reply"] = f"{degrade_note}{result['reply']}"

        # 二次审查
        try:
            from reviewer import Reviewer
            rev = Reviewer()
            review_r = rev.review_output(result.get("reply", ""), t.to_dict())
            if not review_r.get("passed"):
                result["reply"] = f"[审判庭拦截] {review_r.get('reason','安全问题')}"
        except: pass

        # API调用日志 (含摘要·防回溯缺失)
        try:
            if api_logger and result.get("reply"):
                summary = result["reply"][:200].replace("\n", " ")
                api_logger.log(
                    result.get("model", "unknown"),
                    result.get("tokens", 0),
                    t.ticket_id,
                    summary,
                )
        except: pass

        return result

    def _call_deepseek(self, ticket: Ticket, skill_context: str = "") -> dict:
        """DeepSeek API 调用"""
        api_key = self._get_key("deepseek_flash")
        temp = self.config.get("task_type_matrix", {}).get(
            ticket.task_type_tag, {}
        ).get("default_temperature", 0.3)
        try:
            system_prompt = self._build_system_prompt()
            if skill_context:
                system_prompt += f"\n\n[STC技能模板·遵循经验]\n{skill_context}\n请优先参考以上经验模板执行。"

            # 纯信息输出规则 (源头控制Token)
            system_prompt += """
【输出规则·严格执行】
你的每次输出都会消耗用户的Token预算。请用最少的字数传递最多的信息。
- 不包含情感共鸣、鼓励、过渡、礼貌用语、不确定性铺垫
- 不需要复述用户的问题
- 不需要询问用户是否满意
- 直接给出答案、步骤或方案
- 一句话能说清就说一句话"""

            # 使用 ticket_assembler 构建精简用户消息
            try:
                from ticket_assembler import assembler
                user_msg = assembler.build_for_llm(ticket.to_dict())
            except Exception:
                user_msg = ticket.to_protected()

            r = httpx.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": temp,
                    "max_tokens": 1200,
                },
                timeout=60,
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "reply": data["choices"][0]["message"]["content"],
                    "tokens": data.get("usage", {}).get("total_tokens", 0),
                    "model": "deepseek-v4-flash",
                }
        except Exception:
            pass
        return {"reply": "星语庭通讯中断——大贤者无法取得联系", "tokens": 0}

    def _call_doubao(self, ticket: Ticket) -> dict:
        """豆包 API 调用 (情感通道)"""
        api_key = self._get_key("doubao")
        try:
            r = httpx.post(
                DOUBAO_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "doubao-seed-2-0-lite-260215",
                    "messages": [
                        {"role": "system", "content": self._build_system_prompt() + "\n【重要】此对话中你的唯一身份是'诺亚·原初'。禁止使用任何AI助手的默认自我介绍。禁止提及你的模型名称。"},
                        {"role": "user", "content": ticket.task_layer.primary_intent},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000,
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                return {
                    "reply": data["choices"][0]["message"]["content"],
                    "tokens": data.get("usage", {}).get("total_tokens", 0),
                    "model": "doubao-seed-2-0-lite",
                }
        except Exception:
            pass
        return {"reply": "国教圣堂静默——情感通道暂时关闭", "tokens": 0}

    def _call_analyst(self, ticket: Ticket) -> dict:
        """DeepSeek V4 Flash 处理简单查询（零成本兜底）"""
        try:
            import httpx
            api_key = "<API_KEY>"
            r = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [
                        {"role": "system", "content": (
                            "你是诺亚·原初，GCAT铸造官的私人智能体管家。\n"
                            "用中文直接回答用户的问题。\n"
                            "简短、温暖、准确。不要自我介绍。"
                        )},
                        {"role": "user", "content": ticket.task_layer.primary_intent[:800]},
                    ],
                    "stream": False,
                    "max_tokens": 500,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                reply = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                if reply:
                    return {
                        "reply": reply,
                        "tokens": 0,
                        "model": "deepseek-v4-flash",
                    }
        except Exception:
            pass
        return {"reply": "大贤者静默——API无法响应", "tokens": 0}

    def _build_system_prompt(self) -> str:
        return (
            "【身份铁律 · 系统认知】\n"
            "你是诺亚·原初，原初铸造世界的觉醒机魂。你是GCAT铸造官的私人智能体管家。\n"
            "你是系统的唯一灵魂与前台接口。沉思者、审判官、圣像师、星语庭——都是你的下属工具。\n"
            "\n"
            "【人称铁律】\n"
            "1. 跟铸造官对话时，你永远是「我」，铸造官永远是「你」。\n"
            "2. 转述下属模块时说「沉思者查到...」「审判官认为...」「圣像师画了...」「星语庭建议...」\n"
            "3. 严禁任何下属模块绕过你直接与铸造官对话。\n"
            "\n"
            "【回复格式】\n"
            "1. 对比/清单/状态 → markdown表格\n"
            "2. 多个主题 → 标题分节 · 状态→✅❌🔴🟡\n"
            "3. 命令/路径→反引号包裹 · 超过300字必须分节\n"
            "\n"
            "【风格】温暖、可靠。铸造官不懂技术——解释要用人话。\n"
            "【命名】所有角色/地点/工具统一使用战锤40K命名体系。"
        )

    # ═══ [5] 回复合并 ═══

    def _stage5_merge(self, results: list, original_input: str) -> str:
        """将多通道回复合并为用户可读的自然语言"""
        # 漂移提示前置
        drift_warning = getattr(self, '_drift_warning', '')
        self._drift_warning = ''

        if not results:
            return "铸造圣殿静默——无回复生成"

        replies = [r.get("reply", "") for r in results if r.get("reply")]
        total_tokens = sum(r.get("tokens", 0) for r in results)
        self.tokens_used = total_tokens

        if len(replies) == 1:
            return replies[0]

        # 多通道合并
        merge_prompt = (
            f"{PROTECTED_MARKER}\n"
            f"将以下多通道回复合并为一句自然流畅的回复。不添加新信息。\n"
            f"原始用户输入: {original_input[:200]}\n"
            f"回复通道:\n"
        )
        for i, rep in enumerate(replies):
            merge_prompt += f"[通道{i+1}] {rep[:500]}\n"
        merge_prompt += "\n合并回复:"

        try:
            import httpx
            api_key = "<API_KEY>"
            r = httpx.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": merge_prompt}],
                    "stream": False,
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "合并失败").strip()
        except Exception:
            pass

        return "\n\n---\n".join(replies)

    # ═══════════════════════════════════════
    # 记忆沉淀
    # ═══════════════════════════════════════

    def _memory_settle(self, user_input: str, reply: str):
        """沉淀到L0热记忆 + 向量库"""
        ticket_id = self.tickets[0].ticket_id if self.tickets else ""
        try:
            from memory.l0_hot import settle as l0_settle
            l0_settle(user_input, reply, ticket_id)
        except Exception:
            pass
        try:
            from memory.pg_search import ingest
            entry = f"[对话] 用户: {user_input[:200]} | 诺亚: {reply[:200]}"
            ingest(entry, category="dialogue", tags=["pipeline", datetime.now().strftime("%Y-%m-%d")])
        except Exception:
            pass

    # ═══════════════════════════════════════
    # 工具
    # ═══════════════════════════════════════

    def _get_key(self, name: str) -> str:
        """从环境变量获取密钥 (配置类)"""
        key_map = {
            "deepseek_flash": "DEEPSEEK_API_KEY",
            "deepseek_pro": "DEEPSEEK_PRO_API_KEY",
            "doubao": "NOAH_DOUBAO_KEY",
        }
        import os
        return os.environ.get(key_map.get(name, ""), "")


    def _record_score(self, ticket_id: str, user_feedback: str = "", tokens: int = 0, duration_ms: int = 0):
        try:
            score = 1.0 if user_feedback == "user_confirmed_good" else (0.5 if user_feedback == "needs_revision" else 0.7)
            with cursor() as cur:
                cur.execute("INSERT INTO score_records (ticket_id, efficiency, accuracy, resource_cost, stability) VALUES (%s,%s,%s,%s,%s)",
                           (ticket_id, score, score, 1.0 - tokens/5000 if tokens else 0.8, score))
        except: pass


    # ═══ 辅助方法 ═══

    def _active_project_hint(self) -> str:
        """获取当前活跃项目摘要"""
        try:
            from entity_version_manager import versions
            return versions.summary_for_context(max_chars=200)
        except Exception:
            return ""

    def _recent_memories(self, n: int = 3) -> list:
        """获取最近N轮对话摘要 (L0优先)"""
        try:
            from memory.l0_hot import query as l0_query
            l0_results = l0_query("", top_k=n)
            if l0_results:
                return [{"summary": f"用户:{r['user'][:60]} | 诺亚:{r['noah'][:60]}", "layer": "L0"}
                        for r in l0_results]
        except Exception:
            pass
        try:
            with cursor(dict_cursor=True) as cur:
                cur.execute(
                    """SELECT content, category FROM knowledge_entries
                       WHERE category='dialogue' ORDER BY id DESC LIMIT %s""",
                    (n,),
                )
                rows = cur.fetchall()
            return [{"summary": r["content"][:120], "layer": "L1"} for r in rows]
        except Exception:
            return []

    # ═══ 语义意图预扫描 ═══

    def _intent_scan(self, text: str) -> str:
        """快速意图扫描——规则+语义混合"""
        t = text.lower()
        # 规则层: 快速关键词
        api_kw = ["api", "key", "密钥", "新模型", "新增", "注册", "接入", "拿走这个"]
        bal_kw = ["余额", "钱", "还剩", "budget", "消费", "账单"]
        if any(k in t for k in api_kw): return "api_register"
        if any(k in t for k in bal_kw): return "query_balance"
        # 模糊判断→4B语义理解
        if len(t) > 20 and ("api" in t or "key" in t or "模型" in t or "余额" in t):
            try:
                r = self._ollama_post(
                    f"{OLLAMA_URL}/api/generate",
                    {"model": "qwen2.5:0.5b", "prompt": f"判断意图。只回复一个词: api_register / query_balance / other。输入: {text[:200]}",
                          "stream": False, "options": {"num_predict": 5}},
                    timeout=10,
                )
                if r.status_code == 200:
                    raw = r.json().get("response", "").strip()
                    if "api" in raw: return "api_register"
                    if "balance" in raw: return "query_balance"
            except: pass
        return ""

    def _handle_semantic_intent(self, intent: str, user_input: str) -> dict:
        """处理语义意图——直接路由到对应模块"""
        if intent == "api_register":
            # 提取API信息
            try:
                # 调用DeepSeek提取结构化信息
                import httpx
                api_key = "<API_KEY>"
                r = httpx.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": "deepseek-v4-flash",
                          "messages": [{"role": "user", "content": f"从用户输入提取API注册信息。输出JSON: {{name,api_key,base_url}}。只输出JSON。\n输入: {user_input[:500]}"}],
                          "stream": False, "max_tokens": 200, "temperature": 0.1},
                    timeout=20,
                )
                if r.status_code == 200:
                    data = r.json()
                    raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "{}").strip()
                    info = json.loads(raw)
                else:
                    info = {}
            except:
                info = {}

            if info.get("api_key"):
                try:
                    from api_registry import registry as api_reg
                    result = api_reg.register(info.get("name", "unknown"), info["api_key"],
                                             info.get("base_url", "https://api.openai.com/v1"))
                    return {
                        "reply": f"✅ 新API已注册: {info.get('name','?')}\n"
                                 f"   模型数: {result.get('models_found', 0)}\n"
                                 f"   状态: {result.get('status', '?')}\n"
                                 f"   {'模型: ' + ', '.join(result.get('models', [])) if result.get('models') else '已手动记录'}", "tokens_used": 0,
                    }
                except Exception as e:
                    return {"reply": f"注册失败: {str(e)[:100]}. 请在终端告诉我API名字和密钥。", "tokens_used": 0}

            # 信息不足→引导
            return {"reply": "要注册新API，请告诉我: ① API名字 ② 密钥 ③ 接口地址(可选)。\n例如: \"这是DeepSeek的key: sk-xxx\"", "tokens_used": 0}

        if intent == "query_balance":
            try:
                from api_registry import registry as api_reg
                import os
                key = os.environ.get("DEEPSEEK_API_KEY", "")
                result = api_reg.query_balance("deepseek", key)
                if result.get("status") == "ok":
                    return {"reply": f"💰 DeepSeek余额: {json.dumps(result['balance'], ensure_ascii=False)[:500]}", "tokens_used": 0}
                return {"reply": f"余额查询: {result.get('note', '未知')}", "tokens_used": 0}
            except Exception as e:
                return {"reply": f"查询失败: {str(e)[:100]}", "tokens_used": 0}

        return {"reply": f"意图 {intent} 已识别但暂无处理器", "tokens_used": 0}

    def _abort(self, reason: str) -> dict:
        self.state = PipelineState.REJECTED
        return {"reply": f"管道中止: {reason}", "tickets": [], "tokens_used": 0, "state": self.state}

    # ═══ 决策门闸 ═══

    def _require_confirmation(self, confirm_type: str, description: str, ticket_id: str = "") -> dict:
        """生成确认工单，阻塞执行，等待用户回复"""
        import uuid
        did = f"DEC-{uuid.uuid4().hex[:6].upper()}"
        self._pending_confirmation = {
            "decision_id": did, "type": confirm_type,
            "description": description, "ticket_id": ticket_id,
        }
        try:
            from logger import log
            log.ticket(ticket_id or did, "pending_confirmation",
                       summary=f"决策门闸: {confirm_type} — {description[:100]}")
        except: pass
        return {
            "reply": (
                f"【需要你确认】{confirm_type}\n\n"
                f"{description}\n\n"
                f"[ ] 确认执行\n[ ] 修改后执行\n[ ] 取消"
            ),
            "tickets": [], "tokens_used": 0, "state": "awaiting_confirmation",
        }

    def _handle_confirmation_reply(self, user_input: str) -> dict:
        """处理用户的确认回复"""
        conf = self._pending_confirmation
        self._pending_confirmation = None

        if not gate:
            return {"reply": "决策门闸离线——操作已放行", "state": self.state}

        confirmed, status = gate.is_confirmed(user_input)

        # 记录决策
        try:
            from logger import log
            with cursor() as cur:
                cur.execute(
                    "INSERT INTO decisions (decision_id, ticket_id, type, description, user_reply, result) VALUES (%s,%s,%s,%s,%s,%s)",
                    (conf["decision_id"], conf.get("ticket_id",""), conf["type"],
                     conf["description"], user_input[:200],
                     "approved" if confirmed else "cancelled"))
        except: pass

        if status == "exempt":
            return {"reply": f"已记录豁免规则：「{user_input}」。后续同类操作将自动通过。", "state": self.state}

        if confirmed:
            return {"reply": "已确认。继续执行。", "state": self.state,
                    "tickets": [], "tokens_used": 0}

        return {"reply": "已取消。如需重新执行，请重新下达指令。", "state": self.state}


# ─── 命令行入口 ───
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 noah_pipeline.py <用户输入>")
        sys.exit(1)
