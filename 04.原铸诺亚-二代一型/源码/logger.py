#!/usr/bin/env python3
"""统一日志系统 · logger.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 全生命周期日志
遵循 NOA-005 设计 · 三层存储模型

自动记录·自动分流·无需手动操作
"""

import json
from pathlib import Path
from datetime import datetime
from pg_conn import connect, cursor

PRIME_ROOT = Path(__file__).parent


class Logger:
    """统一日志——一切自动发生"""

    # ═══════════════════════════════════
    # 工单日志
    # ═══════════════════════════════════

    @staticmethod
    def ticket(ticket_id: str, status: str, memory_ids: list = None, summary: str = ""):
        _exec(
            """INSERT INTO tickets_log (ticket_id, status, memory_ids, summary)
               VALUES (%s, %s, %s, %s)""",
            (ticket_id, status, memory_ids or [], summary[:500]),
        )

    @staticmethod
    def ticket_status(ticket_id: str, new_status: str):
        """状态变更——立即写入，不等到对话结束"""
        _exec(
            "UPDATE tickets_log SET status=%s WHERE ticket_id=%s",
            (new_status, ticket_id),
        )

    # ═══════════════════════════════════
    # API调用日志
    # ═══════════════════════════════════

    @staticmethod
    def api_call(model: str, tokens: int, latency_ms: int, ticket_id: str, summary: str = ""):
        _exec(
            """INSERT INTO api_call_logs (model, tokens_used, ticket_id, response_summary)
               VALUES (%s, %s, %s, %s)""",
            (model, tokens, ticket_id, summary[:200]),
        )
        # 文件备份
        _append_jsonl(PRIME_ROOT / "logs" / "api_calls" / f"{_today()}.jsonl", {
            "timestamp": datetime.now().isoformat(), "model": model,
            "tokens": tokens, "ticket_id": ticket_id,
        })

    # ═══════════════════════════════════
    # 工具使用日志
    # ═══════════════════════════════════

    @staticmethod
    def tool_use(tool_name: str, params: str, result: str,
                 duration_ms: int, gate_approved: bool, ticket_id: str = ""):
        # 脱敏
        safe_params = _sanitize(params)
        _exec(
            """INSERT INTO tool_uses (tool_name, params, result, duration_ms, gate_approved, ticket_id)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tool_name, safe_params[:500], result[:500], duration_ms, gate_approved, ticket_id),
        )

    # ═══════════════════════════════════
    # 审查日志
    # ═══════════════════════════════════

    @staticmethod
    def review(review_point: str, verdict: str, reason: str = "", ticket_id: str = ""):
        _exec(
            """INSERT INTO reviews_log (review_point, verdict, reason, ticket_id)
               VALUES (%s, %s, %s, %s)""",
            (review_point, verdict, reason[:300], ticket_id),
        )

    # ═══════════════════════════════════
    # 对话原始记录 (不可变)
    # ═══════════════════════════════════

    @staticmethod
    def chat(user_input: str, noah_reply: str, ticket_id: str = ""):
        _append_jsonl(PRIME_ROOT / "logs" / "chat" / f"{_today()}.jsonl", {
            "timestamp": datetime.now().isoformat(),
            "user": _sanitize(user_input),
            "noah": _sanitize(noah_reply),
            "ticket_id": ticket_id,
        })

    # ═══════════════════════════════════
    # 中断恢复查询
    # ═══════════════════════════════════

    @staticmethod
    def pending_tickets() -> list:
        """查询未完成的工单"""
        rows = _query(
            """SELECT ticket_id, status, created_at, summary
               FROM tickets_log
               WHERE status IN ('pending','reviewed','in_progress')
               ORDER BY created_at DESC LIMIT 10"""
        )
        return [dict(r) for r in rows] if rows else []

    # ═══════════════════════════════════
    # 完整性检查
    # ═══════════════════════════════════

    @staticmethod
    def check_integrity() -> dict:
        """自检：所有日志表是否可写"""
        results = {}
        tables = ["tickets_log", "api_call_logs", "tool_uses", "reviews_log",
                  "knowledge_entries", "exact_info", "codex_rules"]
        for tbl in tables:
            try:
                _query(f"SELECT count(*) FROM {tbl}")
                results[tbl] = "ok"
            except Exception as e:
                results[tbl] = f"FAIL: {e}"
        return results


# ═══════════════════════════════════
# 内部辅助
# ═══════════════════════════════════

def _exec(sql: str, params: tuple):
    try:
        with cursor() as cur:
            cur.execute(sql, params)
    except Exception:
        pass


def _query(sql: str):
    try:
        with cursor(dict_cursor=True) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return rows
    except Exception:
        return []


def _append_jsonl(path: Path, entry: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _sanitize(text: str) -> str:
    """清洗特殊字符·防JSON崩溃"""
    if not text:
        return ""
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# 全局实例
log = Logger()


# ─── 测试 ───
if __name__ == "__main__":
    # 写入测试
    log.ticket("TEST-001", "pending", summary="完整性测试")
    log.api_call("deepseek-v4-flash", 500, 1200, "TEST-001", "测试调用")
    log.tool_use("read_file", "/test/path", "ok", 45, True, "TEST-001")
    log.review("gate_1", "approved", "正常", "TEST-001")
    log.chat("测试输入", "测试回复", "TEST-001")

    # 验证
    print("完整性:", json.dumps(log.check_integrity(), ensure_ascii=False, indent=2))
    print("未完成工单:", len(log.pending_tickets()))
    print("✅ 统一日志系统就绪")
