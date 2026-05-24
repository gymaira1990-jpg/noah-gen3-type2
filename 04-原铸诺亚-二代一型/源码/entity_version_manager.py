#!/usr/bin/env python3
"""实体版本管理器 · entity_version_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
替代旧保护区标记——用版本号管理事实，而非用标签保护内容。

核心原则:
  事实只认最新版: 同一语义下旧版本自动标记为deprecated
  保护只给标识符: 保护version_id/entity_key等定位器，不保护内容
  版本链可追溯: 不删旧版，归档后可回溯
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from pg_conn import connect, cursor

PRIME_ROOT = Path(__file__).parent


class EntityVersionManager:
    """版本化实体管理——替代保护区标记"""

    # ═══════════════════════════════════
    # 创建 / 更新
    # ═══════════════════════════════════

    def create_entity(self, entity_type: str, entity_key: str, content: str,
                      project_id: str = "", source_ticket: str = "") -> dict:
        """创建首个版本实体"""
        version_id = f"v1_{entity_type}_{entity_key}_{uuid.uuid4().hex[:6]}"
        now = datetime.now().isoformat()

        with cursor() as cur:
            cur.execute(
                """INSERT INTO entity_versions
                   (version_id, entity_type, entity_key, content, status,
                    project_id, source_ticket, created_at)
                   VALUES (%s,%s,%s,%s,'current',%s,%s,%s)""",
                (version_id, entity_type, entity_key, content[:5000], project_id, source_ticket, now),
            )

        return {"version_id": version_id, "status": "current", "content": content[:200]}

    def update_entity(self, entity_type: str, entity_key: str, new_content: str,
                      source_ticket: str = "") -> dict:
        """更新实体: 旧版→deprecated, 创建新版"""
        current = self.get_current(entity_type, entity_key)
        now = datetime.now().isoformat()

        if current:
            old_vid = current["version_id"]
            # 判断内容是否实际变化
            if current["content"].strip() == new_content.strip():
                return {"version_id": old_vid, "status": "unchanged",
                        "note": "内容未变化，跳过版本更新"}

            # 标记旧版为废弃
            with connect() as conn:
                cur = conn.cursor()
                # 生成新版本号
                old_ver = old_vid.split("_")[0]  # v1
                old_num = int(old_ver[1:]) if old_ver.startswith("v") else 0
                new_ver = f"v{old_num + 1}"
                new_version_id = f"{new_ver}_{entity_type}_{entity_key}_{uuid.uuid4().hex[:6]}"

                cur.execute(
                    """INSERT INTO entity_versions
                       (version_id, entity_type, entity_key, content, status,
                        project_id, source_ticket, created_at)
                       VALUES (%s,%s,%s,%s,'current',%s,%s,%s)""",
                    (new_version_id, entity_type, entity_key, new_content[:5000],
                     current.get("project_id", ""), source_ticket, now),
                )

                cur.execute(
                    """UPDATE entity_versions SET status='deprecated',
                       deprecated_at=%s, replaced_by=%s
                       WHERE version_id=%s""",
                    (now, new_version_id, old_vid),
                )
                conn.commit()
                cur.close()

            return {"version_id": new_version_id, "status": "current",
                    "previous": old_vid, "content": new_content[:200]}
        else:
            return self.create_entity(entity_type, entity_key, new_content,
                                      source_ticket=source_ticket)

    def upsert_entity(self, entity_type: str, entity_key: str, content: str,
                      source_ticket: str = "") -> dict:
        """有则更新，无则创建"""
        current = self.get_current(entity_type, entity_key)
        if current:
            return self.update_entity(entity_type, entity_key, content, source_ticket)
        return self.create_entity(entity_type, entity_key, content, source_ticket=source_ticket)

    # ═══════════════════════════════════
    # 查询
    # ═══════════════════════════════════

    def get_current(self, entity_type: str, entity_key: str) -> Optional[dict]:
        """获取当前有效版本"""
        with cursor(dict_cursor=True) as cur:
            cur.execute(
                """SELECT version_id, entity_type, entity_key, content, status,
                          project_id, source_ticket, created_at
                   FROM entity_versions
                   WHERE entity_type=%s AND entity_key=%s AND status='current'
                   ORDER BY created_at DESC LIMIT 1""",
                (entity_type, entity_key),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    def get_history(self, entity_type: str, entity_key: str) -> list:
        """获取完整版本链 (current + deprecated)"""
        with cursor(dict_cursor=True) as cur:
            cur.execute(
                """SELECT version_id, content, status, created_at, deprecated_at, replaced_by
                   FROM entity_versions
                   WHERE entity_type=%s AND entity_key=%s
                   ORDER BY created_at DESC""",
                (entity_type, entity_key),
            )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    def get_by_version_id(self, version_id: str) -> Optional[dict]:
        """按版本号精确定位"""
        with cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM entity_versions WHERE version_id=%s", (version_id,))
            row = cur.fetchone()
        return dict(row) if row else None

    def query_current_by_type(self, entity_type: str, project_id: str = "") -> list:
        """查询某类型下所有当前版本"""
        with cursor(dict_cursor=True) as cur:
            if project_id:
                cur.execute(
                    """SELECT entity_key, content, version_id
                       FROM entity_versions
                       WHERE entity_type=%s AND status='current' AND project_id=%s
                       ORDER BY entity_key""",
                    (entity_type, project_id),
                )
            else:
                cur.execute(
                    """SELECT entity_key, content, version_id
                       FROM entity_versions
                       WHERE entity_type=%s AND status='current'
                       ORDER BY entity_key""",
                    (entity_type,),
                )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ═══════════════════════════════════
    # 检索摘要 (给4B/工单组装用)
    # ═══════════════════════════════════

    def summary_for_context(self, entity_types: list = None, project_id: str = "",
                            max_chars: int = 500) -> str:
        """生成当前版本事实摘要——用于上下文组装"""
        types = entity_types or ["character_setting", "project_rule", "codex_rule"]
        parts = []
        total = 0

        for etype in types:
            rows = self.query_current_by_type(etype, project_id)
            for r in rows:
                line = f"[{r['entity_key']}] {r['content'][:100]}"
                if total + len(line) > max_chars:
                    parts.append("...")
                    return "\n".join(parts)
                parts.append(line)
                total += len(line)

        return "\n".join(parts) if parts else "(无当前事实)"

    # ═══════════════════════════════════
    # 维护
    # ═══════════════════════════════════

    def archive_old_versions(self, days: int = 30) -> dict:
        """归档超过N天的deprecated版本 → archived"""
        with cursor() as cur:
            cur.execute(
                """UPDATE entity_versions SET status='archived'
                   WHERE status='deprecated'
                   AND deprecated_at::timestamp < now() - interval '%s days'
                   AND replaced_by IS NOT NULL""",
                (days,),
            )
            count = cur.rowcount
        return {"archived": count}

    def cleanup_orphans(self) -> dict:
        """清理无引用链的孤立实体"""
        return {"cleaned": 0}  # 保守策略，暂不自动删除

    def stats(self) -> dict:
        """版本库统计"""
        with connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT status, count(*) FROM entity_versions GROUP BY status")
            status_counts = dict(cur.fetchall())
            cur.execute("SELECT count(DISTINCT entity_type||':'||entity_key) FROM entity_versions WHERE status='current'")
            active_entities = cur.fetchone()[0]
            cur.close()
        return {
            "total_versions": sum(status_counts.values()),
            "active_entities": active_entities,
            "by_status": status_counts,
        }


# ─── 全局实例 ───
versions = EntityVersionManager()


# ─── 测试 ───
if __name__ == "__main__":
    vm = EntityVersionManager()

    # 创建实体
    r1 = vm.create_entity("character_setting", "weapon", "主角武器是光剑",
                          project_id="novel_test", source_ticket="TEST-001")
    print(f"创建: {r1}")

    # 更新实体
    r2 = vm.update_entity("character_setting", "weapon", "主角武器是暗火双属性",
                          source_ticket="TEST-002")
    print(f"更新: {r2}")

    # 获取当前版本
    curr = vm.get_current("character_setting", "weapon")
    print(f"\n当前武器设定: {curr['content'] if curr else '无'}")

    # 版本历史
    hist = vm.get_history("character_setting", "weapon")
    print(f"\n版本链 ({len(hist)}个版本):")
    for h in hist:
        print(f"  {h['version_id']} [{h['status']}] {h['content'][:60]}")

    # 上下文摘要
    summary = vm.summary_for_context(["character_setting"], project_id="novel_test")
    print(f"\n上下文摘要:\n{summary}")

    print(f"\n统计: {vm.stats()}")
