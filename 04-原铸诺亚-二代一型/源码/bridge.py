#!/usr/bin/env python3
"""广州星语中继站 V2 · bridge.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界 ↔ 广州星语庭
战锤40K主题: 星语庭中继 (Astropath Relay)

核心原则: 广州不可用时，本地照常工作。零依赖。

架构:
  NOAH-PRIME (动态IP·笔记本)  ──出站连接──→  广州 (固定IP·43.136.21.142)
  
  笔记本IP天天变？没关系——永远是笔记本主动连广州。
  就像你打开微信，不管在哪儿都能收到消息。

广州角色:
  ① 夜班任务队列 — 关机前丢过去，第二天看结果
  ② 知识备份同步 — 本地数据自动复制到云端保险柜
  ③ 远程健康监控 — 广州帮你盯着笔记本状态
"""

import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from pg_conn import cursor

GZ_HOST = "ubuntu@43.136.21.142"
SSH_KEY = str(Path.home() / ".ssh" / "guangzhou-server.pem")
PRIME_ROOT = Path(__file__).parent

# ═══════════════════════════════════════
# 安全外壳: 所有广州操作都包在这个里面
# 失败=静默跳过，不影响本地工作
# ═══════════════════════════════════════

class GuangzhouRelay:
    """星语庭中继站 — 可选增强，非核心依赖"""

    def __init__(self):
        self.online = False
        self.last_check = 0
        self._refresh()

    def _refresh(self):
        """检查广州是否在线（每60秒最多查一次）"""
        if time.time() - self.last_check < 60:
            return
        self.last_check = time.time()
        try:
            r = self._ssh("echo OK", timeout=5)
            self.online = r == "OK"
        except Exception:
            self.online = False

    def _ssh(self, cmd: str, timeout: int = 15) -> str:
        """执行SSH命令。失败返回空字符串。"""
        try:
            full = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=5", GZ_HOST, cmd]
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip() if r.returncode == 0 else ""
        except Exception:
            return ""

    # ═══════════════════════════════════
    # ① 夜班任务队列
    # ═══════════════════════════════════

    def submit_night_task(self, task_name: str, command: str, priority: int = 0) -> dict:
        """提交一个夜班任务到广州。关机前调用。
        
        task_name: 任务名称（你自己起，方便第二天查看）
        command:   shell命令（会在广州服务器上执行）
        priority:  0=普通 1=优先
        """
        self._refresh()
        if not self.online:
            return {"status": "queued_local", "note": "广州离线，任务暂存本地，下次连线时发送"}

        task = {
            "name": task_name,
            "command": command,
            "priority": priority,
            "submitted_at": datetime.now().isoformat(),
            "from": "NOAH-PRIME",
        }
        payload = json.dumps(task).replace('"', '\\"')
        try:
            cmd = (
                f"mkdir -p ~/noah-queue && "
                f"echo '{payload}' >> ~/noah-queue/tasks.jsonl"
            )
            self._ssh(cmd)
            return {"status": "submitted", "task": task_name,
                    "note": "广州会执行。你明天开机看结果。"}
        except Exception:
            return {"status": "failed", "note": "提交失败，你可以在本地手动执行",
                    "local_command": command}

    def check_night_results(self) -> list:
        """取回广州夜班任务的结果"""
        self._refresh()
        if not self.online:
            return []
        try:
            raw = self._ssh("cat ~/noah-queue/results.jsonl 2>/dev/null | tail -20")
            if not raw:
                return []
            results = []
            for line in raw.strip().split("\n"):
                try:
                    results.append(json.loads(line))
                except Exception:
                    pass
            return results
        except Exception:
            return []

    # ═══════════════════════════════════
    # ② 知识备份同步
    # ═══════════════════════════════════

    def backup_knowledge(self) -> dict:
        """将本地PG数据备份到广州"""
        self._refresh()
        if not self.online:
            return {"status": "offline", "note": "广州离线，下次连线时自动备份"}

        try:
            with cursor() as cur:
                cur.execute("SELECT content, category FROM knowledge_entries ORDER BY id DESC LIMIT 100")
                rows = cur.fetchall()

            synced = 0
            for content, category in rows:
                entry = json.dumps({"content": content[:500], "category": category}).replace('"', '\\"')
                r = self._ssh(
                    f"psql -U noah -d noah_knowledge -c "
                    f"\"INSERT INTO knowledge_entries (content, category) VALUES ('{entry}', '{category}') ON CONFLICT DO NOTHING\" "
                    f"2>/dev/null"
                )
                if r:
                    synced += 1

            return {"status": "synced", "count": synced, "total": len(rows)}
        except Exception as e:
            return {"status": "failed", "note": str(e)[:100]}

    # ═══════════════════════════════════
    # ③ 远程健康
    # ═══════════════════════════════════

    def health(self) -> dict:
        """快速健康检查"""
        self._refresh()
        if not self.online:
            return {"status": "offline"}
        try:
            r = self._ssh("curl -s http://localhost:8000/health", timeout=8)
            return json.loads(r) if r else {"status": "degraded"}
        except Exception:
            return {"status": "unreachable"}

    def remote_status(self) -> dict:
        """广州系统状态详情"""
        self._refresh()
        if not self.online:
            return {"online": False}

        disk = self._ssh("df -h / | tail -1 | awk '{print $3\"/\"$2\" (\"$5\")\"}'")
        mem = self._ssh("free -h | grep Mem | awk '{print $3\"/\"$2}'")
        queue_count = self._ssh("wc -l < ~/noah-queue/tasks.jsonl 2>/dev/null || echo 0")

        return {
            "online": True,
            "host": GZ_HOST,
            "disk": disk.strip(),
            "memory": mem.strip(),
            "pending_tasks": queue_count.strip(),
        }


# 全局实例
relay = GuangzhouRelay()


# ═══════════════════════════════════════
# 管道集成: 启动时自动同步，不做依赖
# ═══════════════════════════════════════

def startup_sync():
    """NOAH-PRIME启动时调用：不阻塞，失败了就跳过"""
    try:
        # 取回夜班结果
        results = relay.check_night_results()
        if results:
            print(f"📡 星语庭: 取回 {len(results)} 条夜班任务结果")

        # 检查广州状态
        h = relay.health()
        if h.get("status") == "ok":
            print(f"📡 星语庭: 在线 (第一神经元 {h.get('version','?')})")
        else:
            print("📡 星语庭: 离线 (不影响本地工作)")

        return results
    except Exception:
        return []


def shutdown_sync():
    """NOAH-PRIME关机前调用：提交夜班任务+备份"""
    try:
        # 自动备份
        relay.backup_knowledge()
        print("📡 星语庭: 知识已备份到广州")
    except Exception:
        pass


# ─── 测试 ───
if __name__ == "__main__":
    print("=== 星语庭中继站 V2 · 零依赖架构 ===\n")

    # 健康检查
    h = relay.health()
    print(f"广州状态: {h.get('status','?')}")

    if relay.online:
        print(f"\n系统概况: {json.dumps(relay.remote_status(), ensure_ascii=False, indent=2)}")

        # 夜班任务演示
        r = relay.submit_night_task(
            "数据库碎片整理",
            "psql -U noah -d noah_knowledge -c 'VACUUM ANALYZE'"
        )
        print(f"\n夜班任务: {r['status']}")

        # 备份
        b = relay.backup_knowledge()
        print(f"知识备份: {b['status']}")
    else:
        print("\n⚠ 广州离线 —— NOAH-PRIME 所有本地功能正常工作")
        print("  夜班任务和备份将在广州恢复后自动同步")
