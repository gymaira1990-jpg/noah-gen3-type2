#!/usr/bin/env python3
"""静默维护协议 · ssmp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 铸造世界维护周期 (Forge World Maintenance Cycle)

触发: 定时(每日03:00) / 空闲30分钟 / 错误率>5% / 手动
"""

import json
import time
from datetime import datetime
from pathlib import Path
from pg_conn import connect, cursor

PRIME_ROOT = Path(__file__).parent


class SSMP:
    """静默维护协议 — Silent System Maintenance Protocol"""

    def __init__(self):
        self.last_run: dict = {}
        self.idle_since: float = time.time()
        self.error_count: int = 0
        self.total_count: int = 0

    def touch(self):
        """标记活跃 — 重置空闲计时"""
        self.idle_since = time.time()

    def record_result(self, success: bool):
        """记录执行结果"""
        self.total_count += 1
        if not success:
            self.error_count += 1

    @property
    def error_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.error_count / self.total_count

    @property
    def idle_minutes(self) -> float:
        return (time.time() - self.idle_since) / 60

    def should_run(self) -> tuple:
        """检查是否应触发维护"""
        reasons = []

        # 定时检查 (简化: 距上次运行超24h)
        last = self.last_run.get("full", 0)
        if time.time() - last > 86400:
            reasons.append("定时 (24h)")

        # 空闲检查
        if self.idle_minutes > 30:
            reasons.append(f"空闲 ({self.idle_minutes:.0f}min)")

        # 错误率检查
        if self.error_rate > 0.05 and self.total_count >= 10:
            reasons.append(f"错误率 ({self.error_rate:.1%})")

        return bool(reasons), reasons

    def run_maintenance(self) -> dict:
        """执行维护"""
        if not self.should_run()[0]:
            return {"status": "skipped", "reason": "未触发"}

        results = {}

        # ① 碎片整理: PG向量重索引
        try:
            with connect(autocommit=True) as conn:
                cur = conn.cursor()
                cur.execute("REINDEX TABLE knowledge_entries")
                cur.execute("VACUUM ANALYZE knowledge_entries")
                cur.close()
            results["pg_reindex"] = "ok"
        except Exception as e:
            results["pg_reindex"] = f"failed: {e}"

        # ② 日志归档: 压缩7天前的日志
        try:
            log_dir = PRIME_ROOT / "logs" / "chat"
            if log_dir.exists():
                cutoff = time.time() - 7 * 86400
                for f in log_dir.glob("*.jsonl"):
                    if f.stat().st_mtime < cutoff:
                        # 移到 archive
                        archive = log_dir / "archive"
                        archive.mkdir(exist_ok=True)
                        f.rename(archive / f.name)
                results["log_archive"] = "ok"
        except Exception as e:
            results["log_archive"] = f"failed: {e}"

        # ③ 热度降级: freq衰减
        try:
            with cursor() as cur:
                cur.execute("UPDATE knowledge_entries SET freq = GREATEST(1, freq / 2) WHERE freq > 5")
            results["heat_decay"] = "ok"
        except Exception as e:
            results["heat_decay"] = f"failed: {e}"

        # ④ STC熔炉: 自动提炼技能
        try:
            from skill_forge import forge
            forge_result = forge.auto_forge(min_score=0.65)
            results["skill_forge"] = forge_result
        except Exception as e:
            results["skill_forge"] = f"failed: {e}"

        # ⑤ 版本归档: 废弃超30天的旧版本 → archived
        try:
            from entity_version_manager import versions
            archive_result = versions.archive_old_versions(days=30)
            results["version_archive"] = archive_result
        except Exception as e:
            results["version_archive"] = f"failed: {e}"

        self.last_run["full"] = time.time()
        return {
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "results": results,
        }


# 全局实例
ssmp = SSMP()


# ─── 测试 ───
if __name__ == "__main__":
    s = SSMP()
    should, reasons = s.should_run()
    print(f"应运行: {should} | 原因: {reasons}")
    print(f"空闲: {s.idle_minutes:.0f}min | 错误率: {s.error_rate:.1%}")

    if should:
        result = s.run_maintenance()
        print("维护结果:", json.dumps(result, ensure_ascii=False, indent=2))
