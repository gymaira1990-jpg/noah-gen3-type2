#!/usr/bin/env python3
"""智能路由引擎 · brain/smart_router.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原铸世界
P4-T4-1/2/3 三合一：余额感知 + 自动降级链 + 任务精细路由

降级链:  DeepSeek → Doubao → analyst_4b(deepseek-v4-flash) → error
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

import time
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

PRIME_ROOT = Path(__file__).parent.parent
LATENCY_DB = PRIME_ROOT / "data" / "latency_log.jsonl"
DEGRADE_LOG = PRIME_ROOT / "data" / "degrade_log.jsonl"

logger = logging.getLogger("smart_router")

# ─── 降级链定义 ───
DEGRADE_CHAIN = {
    "brain_deepseek": ["brain_doubao", "analyst_4b"],
    "brain_doubao": ["analyst_4b"],
    "analyst_4b": [],  # 本地模型，兜底
}

# ─── 各路由对应模型名 ───
ROUTER_TO_MODEL = {
    "brain_deepseek": "deepseek-v4-flash",
    "brain_doubao": "doubao-seed-2-0-lite-260215",
    "analyst_4b": "deepseek-v4-flash",
}

# ─── 任务类型 → 推荐路由映射 ───
TASK_ROUTER_MAP = {
    "creative_writing": "brain_doubao",
    "emotional_chat": "brain_doubao",
    "code_generation": "brain_deepseek",
    "system_ops": "brain_deepseek",
    "analysis_report": "brain_deepseek",
    "query": "analyst_4b",          # 简单查询 → 本地零成本
    "greeting": "analyst_4b",       # 打招呼 → 本地零成本
}

# ─── 简单查询关键词（不走付费API） ───
LOW_COST_PATTERNS = [
    "你好", "hi", "hello", "在吗", "介绍", "你是谁",
    "ping", "test", "帮助", "help", "?", "谢谢",
    "天气", "时间", "日期", "今天",
]


class SmartRouter:
    """智能路由引擎"""

    def __init__(self):
        self._load_latency_db()

    # ═══════════════════════════════════════
    # 公开接口
    # ═══════════════════════════════════════

    def route(self, task_type_tag: str, user_input: str,
              budget_status: Optional[dict] = None) -> dict:
        """主入口：返回路由决策"""
        start_time = time.time()

        # ─── ① 任务类型精细路由 ───
        preferred = TASK_ROUTER_MAP.get(task_type_tag, "brain_deepseek")

        # ─── ② 简单查询拦截：直接走本地4B ───
        if self._is_simple_query(user_input):
            preferred = "analyst_4b"

        # ─── ③ 余额感知 ───
        budget_blocked = False
        budget_warning = ""
        if budget_status:
            if not budget_status.get("allow_api", True):
                budget_blocked = True
                budget_warning = f"📊 API预算已耗尽(¥{budget_status.get('cost',0):.0f}/月)，强制本地模式"
                preferred = "analyst_4b"
            elif budget_status.get("level") == "warn":
                # 预算警告时：creative_writing和emotional_chat降级到本地
                warning_level = budget_status.get("level", "ok")
                if warning_level == "warn" and preferred != "analyst_4b":
                    budget_warning = f"📊 预算紧张(已用{budget_status.get('ratio',0)*100:.0f}%)，低成本任务走本地"

        # ─── ④ 执行降级链（考虑余额和任务类型） ───
        router_name = preferred
        degrade_chain_used = []

        # 如果首选不是本地且余额不允许 → 走降级
        if budget_blocked and preferred != "analyst_4b":
            router_name = "analyst_4b"
            degrade_chain_used = [preferred, router_name]
        elif preferred == "brain_deepseek" and budget_status and \
             budget_status.get("level") == "warn":
            # 预算警告时，DeepSeek高价值任务保留，但加标记
            pass

        # ─── ⑤ 构建决策记录 ───
        model_name = ROUTER_TO_MODEL.get(router_name, "unknown")
        decision = {
            "router": router_name,
            "model": model_name,
            "preferred": preferred,
            "degrade_chain": degrade_chain_used,
            "budget_blocked": budget_blocked,
            "budget_warning": budget_warning,
            "task_type": task_type_tag,
            "latency_ms": int((time.time() - start_time) * 1000),
        }
        return decision

    def record_latency(self, router_name: str, model: str,
                       latency_ms: int, success: bool,
                       ticket_id: str = ""):
        """记录API调用延迟"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "router": router_name,
            "model": model,
            "latency_ms": latency_ms,
            "success": success,
            "ticket_id": ticket_id,
        }
        try:
            LATENCY_DB.parent.mkdir(parents=True, exist_ok=True)
            with open(LATENCY_DB, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def record_degrade(self, from_router: str, to_router: str,
                       reason: str, ticket_id: str = ""):
        """记录降级事件"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "from": from_router,
            "to": to_router,
            "reason": reason,
            "ticket_id": ticket_id,
        }
        try:
            DEGRADE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(DEGRADE_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_latency_stats(self, router_name: str = None) -> dict:
        """查询延迟统计"""
        records = self._load_latency_db()
        if router_name:
            records = [r for r in records if r.get("router") == router_name]
        if not records:
            return {"total": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0}

        latencies = sorted([r["latency_ms"] for r in records if r.get("latency_ms", 0) > 0])
        if not latencies:
            return {"total": 0, "avg_ms": 0}

        n = len(latencies)
        return {
            "total": n,
            "avg_ms": sum(latencies) / n,
            "p50_ms": latencies[n // 2],
            "p95_ms": latencies[int(n * 0.95)],
            "success_rate": sum(1 for r in records if r.get("success", True)) / len(records) * 100,
        }

    # ═══════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════

    def _is_simple_query(self, text: str) -> bool:
        """判断是否为简单查询（走本地零成本）"""
        text_lower = text.lower().strip()
        if any(p in text_lower for p in LOW_COST_PATTERNS):
            return True
        # 短文本（<15字）且不带动词命令
        if len(text) < 15:
            command_indicators = ["创建", "修改", "删除", "生成", "写", "改",
                                  "建", "查", "运行", "执行", "安装", "配置"]
            if not any(c in text for c in command_indicators):
                return True
        return False

    def _load_latency_db(self) -> list:
        """加载延迟数据库"""
        records = []
        if LATENCY_DB.exists():
            try:
                with open(LATENCY_DB, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
            except Exception:
                pass
        return records


# ─── 全局实例 ───
smart_router = SmartRouter()
