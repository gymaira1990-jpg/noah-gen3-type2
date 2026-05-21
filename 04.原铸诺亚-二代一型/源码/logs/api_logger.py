#!/usr/bin/env python3
"""API调用日志 · logs/api_logger.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 伺服 skull 记录 (Servo-skull Log)

每次在线API调用必修记录: 时间戳、模型、Token、工单ID、摘要
存入 PG api_call_logs 表 + 追加 logs/api_calls/ 文件
"""

import json
from datetime import datetime
from pathlib import Path
from pg_conn import cursor

LOG_DIR = Path(__file__).parent.parent / "logs" / "api_calls"
LOG_DIR.mkdir(parents=True, exist_ok=True)


class ApiLogger:
    """伺服 skull — 记录每一次星语庭/国教圣堂的通联"""

    def __init__(self):
        self.today_log: list = []

    def log(self, model: str, tokens_used: int, ticket_id: str = "",
            response_summary: str = "", status: str = "success",
            duration_ms: int = 0):
        """记录一次API调用"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "tokens_used": tokens_used,
            "ticket_id": ticket_id,
            "response_summary": response_summary[:200],
            "status": status,
            "duration_ms": duration_ms,
        }

        # ① 文件日志 (追加)
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"{today}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # ② PG日志
        try:
            with cursor() as cur:
                cur.execute(
                    """INSERT INTO api_call_logs (timestamp, model, tokens_used, ticket_id, response_summary)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (entry["timestamp"], model, tokens_used, ticket_id, response_summary[:200]),
                )
        except Exception:
            pass

        self.today_log.append(entry)

    def today_summary(self) -> dict:
        """今日统计"""
        total_tokens = sum(e["tokens_used"] for e in self.today_log)
        models_used = {}
        for e in self.today_log:
            m = e["model"]
            models_used[m] = models_used.get(m, 0) + 1
        return {
            "calls": len(self.today_log),
            "tokens": total_tokens,
            "models": models_used,
            "cost_estimate": f"≈ ¥{total_tokens * 0.000002:.4f} (DeepSeek Flash ~2元/百万token)",
        }

    def query_logs(self, days: int = 7) -> list:
        """查询近期日志 (从PG)"""
        try:
            with cursor() as cur:
                cur.execute(
                    """SELECT timestamp, model, tokens_used, ticket_id, response_summary
                       FROM api_call_logs
                       WHERE timestamp > now() - interval '%s days'
                       ORDER BY timestamp DESC LIMIT 100""",
                    (days,),
                )
                rows = cur.fetchall()
            return [
                {"timestamp": str(r[0]), "model": r[1], "tokens": r[2],
                 "ticket": r[3], "summary": r[4]}
                for r in rows
            ]
        except Exception:
            return []


# 全局实例
api_logger = ApiLogger()


# ─── 测试 ───
if __name__ == "__main__":
    api_logger.log("deepseek-v4-flash", 850, "20260509-NOA-TEST",
                   "数据库备份方案生成完毕", duration_ms=3200)
    api_logger.log("doubao-seed-2-0-lite", 320, "20260509-NOA-TEST2",
                   "情感回复生成", duration_ms=1200)
    print("今日统计:", json.dumps(api_logger.today_summary(), ensure_ascii=False, indent=2))
