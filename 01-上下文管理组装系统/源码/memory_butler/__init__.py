"""
memory-butler — 抽屉级联压缩引擎 Tier 2: 记忆管家

职责:
  - 渐进摘要: 对已有方案增量更新，新方案结构化摘要
  - 项目进度追踪: 提取TFC进展，比对DB状态
  - 执行日志保护: 识别操作日志，PG固化为PROTECTED
  - 已完成任务向量冷储: completed→最终摘要→PG archive
  - 重复检测: 当前方案vs历史方案

设计: 抽屉级联压缩引擎-设计v2.0.md §二
依赖: drawer_engine.py (Tier1), PG knowledge_entries, GLM-4-Flash (via call_aux_model)
"""

import hashlib
import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 默认配置 (由 config.yaml steward: 段覆盖) ──
STEWARD_CONFIG = {
    "enabled": True,
    "trigger_interval_rounds": 5,       # 每N轮触发一次
    "glm_temperature": 0.1,
    "max_summary_tokens": 800,
    "pg_conn_string": "psql -U <user> -d noah_local -t -A",
}


def reload_config() -> None:
    """从 config.yaml 重新加载 steward 配置段。"""
    try:
        import yaml
        cfg_path = Path.home() / ".hermes" / "config.yaml"
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            sc = cfg.get("steward", {})
            if sc:
                STEWARD_CONFIG["enabled"] = sc.get("enabled", STEWARD_CONFIG["enabled"])
                STEWARD_CONFIG["trigger_interval_rounds"] = sc.get(
                    "trigger_interval_rounds", STEWARD_CONFIG["trigger_interval_rounds"]
                )
                STEWARD_CONFIG["glm_temperature"] = sc.get(
                    "glm_temperature", STEWARD_CONFIG["glm_temperature"]
                )
                STEWARD_CONFIG["max_summary_tokens"] = sc.get(
                    "max_summary_tokens", STEWARD_CONFIG["max_summary_tokens"]
                )
                logger.info("[butler] config loaded: %s", {k: v for k, v in STEWARD_CONFIG.items() if k != 'pg_conn_string'})
    except Exception:
        pass


# 启动时加载
reload_config()


# ==============================================================
# PG 助手 (与 round-compressor 一致: subprocess psql)
# ==============================================================

def _pg_exec(sql: str, timeout: int = 10) -> Optional[str]:
    """执行 SQL 返回 stdout，失败返回 None。"""
    try:
        parts = STEWARD_CONFIG["pg_conn_string"].split()
        cmd = parts + ["-c", sql]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug("[butler] PG exec failed: %s", e)
    return None


def _pg_insert_entry(
    title: str, content: str, category: str,
    tags: List[str], source: str = "memory-butler",
) -> Optional[int]:
    """写入 knowledge_entries，返回 entry_id 或 None。"""
    title_e = title[:200].replace("'", "''")
    content_e = content[:2000].replace("'", "''")
    tags_sql = "{" + ",".join(tags) + "}"
    sql = (
        f"INSERT INTO knowledge_entries "
        f"(title, content, category, tags, source, entry_type) "
        f"VALUES ("
        f"'{title_e}', '{content_e}', "
        f"'{category}', '{tags_sql}', "
        f"'{source}', 'exact_fact'"
        f") RETURNING id"
    )
    out = _pg_exec(sql)
    if out and out.isdigit():
        return int(out)
    return None


def _pg_search_tags(tag_prefix: str, limit: int = 10) -> List[Dict]:
    """按 tags 前缀搜索 knowledge_entries。"""
    sql = (
        f"SELECT id, title, content, tags, created_at "
        f"FROM knowledge_entries "
        f"WHERE tags::text LIKE '%{tag_prefix}%' "
        f"ORDER BY created_at DESC LIMIT {limit}"
    )
    out = _pg_exec(sql)
    if not out:
        return []
    rows = []
    for line in out.split("\n"):
        line = line.strip()
        if line:
            rows.append({"raw": line})  # 简化: 调用方解析
    return rows


# ==============================================================
# 渐进摘要
# ==============================================================

def progressive_summarize(
    project_name: str,
    new_dialogue: str,
    call_aux_model_fn,
    existing_summary: Optional[str] = None,
) -> str:
    """渐进摘要: 有旧摘要→增量更新, 无→新建。

    Args:
        project_name: 项目名 (如 "原铸诺亚")
        new_dialogue: 新增对话片段
        call_aux_model_fn: call_aux_model 函数引用
        existing_summary: 已有摘要(如搜索到), None 表示新建

    Returns:
        生成的摘要文本
    """
    if existing_summary:
        # 增量更新
        system_msg = (
            "你是一个渐进摘要助理。以下为已有方案摘要和新增讨论。\n"
            "请增量更新摘要，不删除已有内容，只添加新信息。\n"
            "保持结构化格式: ## 方案、已决策、待定、已完成、关联TFC、风险/注意。"
        )
        user_msg = (
            f"已有摘要:\n{existing_summary}\n\n"
            f"新增讨论:\n{new_dialogue}\n\n"
            f"输出增量更新后的完整摘要。不要只输出增量部分，输出完整版。"
        )
    else:
        # 新建
        system_msg = (
            "你是一个方案摘要助理。提取以下对话中的方案/计划/决策，\n"
            "输出结构化摘要。格式:\n"
            "## 方案: <名称>\n"
            "  当前进度: <状态>\n"
            "  已决策: <列表>\n"
            "  待定: <列表>\n"
            "  已完成: <列表>\n"
            "  关联TFC: <编号>\n"
            "  风险/注意: <列表>"
        )
        user_msg = (
            f"提取以下对话中的方案/计划/决策:\n\n{new_dialogue}"
        )

    result = call_aux_model_fn(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=STEWARD_CONFIG["glm_temperature"],
        max_tokens=STEWARD_CONFIG["max_summary_tokens"],
    )

    return result or "摘要生成失败"


# ==============================================================
# 执行日志保护
# ==============================================================

EXECUTION_PATTERNS = [
    r'(我执行了|我改了|我部署了|我配置了|我安装了|我写了|我创建了|我新建了|我删除了|我修改了)\s*:?.+',
    r'(write_file|patch|terminal|apt install|pip install|git commit|git push|service\s+\w+\s+(start|restart|stop|enable))',
    r'(已部署|已安装|已配置|已修改|已创建|已推送|已上线)',
    r'(crontab|systemctl|chmod|chown|sed\s+-i|scp|rsync)',
]


def extract_execution_log(content: str) -> Optional[Dict]:
    """从文本中提取执行日志。

    Returns:
        {text, category, tfc_ref} 或 None
    """
    lines = content.split("\n")
    logs = []
    tfc_refs = set()
    for line in lines:
        for pat in EXECUTION_PATTERNS:
            m = re.search(pat, line.strip(), re.IGNORECASE)
            if m:
                logs.append(line.strip()[:200])
                tfc_m = re.findall(r'(?:TFC|NCP|PRJ)-\d+', line, re.IGNORECASE)
                for t in tfc_m:
                    tfc_refs.add(t.upper())
                break

    if logs:
        return {
            "text": "\n".join(logs),
            "category": "execution_log",
            "tfc_ref": list(tfc_refs) if tfc_refs else None,
        }
    return None


# ==============================================================
# 已完成任务冷储
# ==============================================================

def archive_completed_task(
    tfc_id: str,
    related_summaries: List[str],
    call_aux_model_fn,
) -> Optional[str]:
    """将已完成任务压缩为最终摘要(300-500 tok)。

    Args:
        tfc_id: TFC 编号
        related_summaries: 相关对话摘要列表
        call_aux_model_fn: call_aux_model 函数引用

    Returns:
        最终摘要文本 或 None
    """
    text = "\n---\n".join(related_summaries)
    system_msg = (
        f"你是一个归档助理。请将以下与任务 {tfc_id} 相关的对话摘要，\n"
        f"压缩为最终归档摘要(300-500 tokens)。只保留: \n"
        f"做了什么、为什么做、关键决策、结果、遗留问题。"
    )
    user_msg = f"任务 {tfc_id} 的相关摘要:\n\n{text}"

    result = call_aux_model_fn(
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=600,
    )
    return result


# ==============================================================
# Butler 主循环
# ==============================================================

class MemoryButler:
    """记忆管家。在每轮压缩后处理对话框内容。"""

    def __init__(self, call_aux_model_fn):
        self._call_aux_model = call_aux_model_fn
        self._round_count = 0
        self._last_butler_round = 0
        self._processed_keys: set = set()
        self._stats = {
            "summaries_created": 0,
            "summaries_updated": 0,
            "execution_logs_saved": 0,
            "tasks_archived": 0,
            "duplicates_found": 0,
        }
        self._perf_stats = {
            "cycles_run": 0,
            "total_duration_ms": 0,
            "avg_duration_ms": 0.0,
            "last_duration_ms": 0,
            "pg_writes_ok": 0,
            "pg_writes_fail": 0,
            "glm_calls": 0,
            "glm_errors": 0,
        }

    def tick(self, drawer_items: List[Dict], user_message: str = "") -> None:
        """每 N 轮触发一次管家处理。

        Args:
            drawer_items: 当前抽屉条目列表 (从 drawer.get_context_items())
            user_message: 本轮用户消息
        """
        self._round_count += 1

        if not STEWARD_CONFIG.get("enabled", True):
            return

        interval = STEWARD_CONFIG.get("trigger_interval_rounds", 5)
        if self._round_count - self._last_butler_round < interval:
            return

        self._butler_cycle(drawer_items, user_message)
        self._last_butler_round = self._round_count

    def _butler_cycle(self, drawer_items: List[Dict], user_message: str) -> None:
        """单次管家处理周期。"""
        _t0 = time.monotonic()
        logger.info("[butler] cycle start, drawer_items=%d", len(drawer_items))

        all_text = "\n".join([
            str(item.get("content", "")) for item in drawer_items
        ])
        combined = all_text + "\n" + user_message

        # 2. 渐进摘要
        plans = re.findall(
            r'(?:设计|方案|架构|计划)\s*[:：]\s*(.{2,30})',
            combined, re.IGNORECASE,
        )
        for plan_name in plans[:3]:
            plan_name = plan_name.strip()
            key = f"plan:{plan_name}"
            if key in self._processed_keys:
                continue
            self._processed_keys.add(key)

            existing = _pg_search_tags(f"incremental_summary,{key}")
            existing_summary = existing[0]["raw"] if existing else None

            _t1 = time.monotonic()
            summary = progressive_summarize(
                plan_name, combined,
                self._call_aux_model,
                existing_summary=existing_summary,
            )
            self._perf_stats["glm_calls"] += 1
            if not summary or summary == "摘要生成失败":
                self._perf_stats["glm_errors"] += 1
            if summary and summary != "摘要生成失败":
                entry_id = _pg_insert_entry(
                    title=f"渐进摘要: {plan_name}",
                    content=summary,
                    category="project_progress",
                    tags=[key, "incremental_summary", f"project:{plan_name}"],
                )
                if entry_id:
                    self._perf_stats["pg_writes_ok"] += 1
                    self._stats["summaries_updated" if existing_summary else "summaries_created"] += 1
                    logger.info(
                        "[butler] summary %s: %s (entry=%s)",
                        "updated" if existing_summary else "created",
                        plan_name, entry_id,
                    )
                else:
                    self._perf_stats["pg_writes_fail"] += 1
            _dur1 = (time.monotonic() - _t1) * 1000
            logger.debug("[butler] plan '%s' took %dms", plan_name, _dur1)

        # 3. 执行日志保护
        _t2 = time.monotonic()
        exec_log = extract_execution_log(user_message)
        if exec_log:
            key = f"exec:{hashlib.md5(exec_log['text'].encode()).hexdigest()[:12]}"
            if key not in self._processed_keys:
                self._processed_keys.add(key)
                tags = ["execution_log"]
                if exec_log["tfc_ref"]:
                    tags.extend(exec_log["tfc_ref"])
                entry_id = _pg_insert_entry(
                    title=f"执行日志: {time.strftime('%Y-%m-%d %H:%M')}",
                    content=exec_log["text"],
                    category=exec_log["category"],
                    tags=tags,
                )
                if entry_id:
                    self._perf_stats["pg_writes_ok"] += 1
                    self._stats["execution_logs_saved"] += 1
                    logger.info("[butler] exec log saved (entry=%s)", entry_id)
                else:
                    self._perf_stats["pg_writes_fail"] += 1
        _dur2 = (time.monotonic() - _t2) * 1000
        if exec_log:
            logger.debug("[butler] exec log extraction took %dms", _dur2)

        # 4. 重复检测
        _t3 = time.monotonic()
        self._check_duplicates(combined)
        _dur3 = (time.monotonic() - _t3) * 1000

        # 更新性能指标
        _dur_total = (time.monotonic() - _t0) * 1000
        self._perf_stats["cycles_run"] += 1
        self._perf_stats["last_duration_ms"] = int(_dur_total)
        self._perf_stats["total_duration_ms"] += int(_dur_total)
        self._perf_stats["avg_duration_ms"] = (
            self._perf_stats["total_duration_ms"] / self._perf_stats["cycles_run"]
        )

        logger.info(
            "[butler] cycle done in %dms: %s",
            int(_dur_total),
            {k: v for k, v in self._stats.items() if v > 0},
        )

    def _check_duplicates(self, text: str) -> None:
        """检查当前方案 vs 历史方案重复。"""
        tfc_matches = re.findall(r'(TFC|NCP|PRJ)-\d+', text, re.IGNORECASE)
        if not tfc_matches:
            return
        for ref in set(m.upper() for m in tfc_matches):
            existing = _pg_search_tags(f"tfc:{ref}")
            if existing and ref not in self._processed_keys:
                self._processed_keys.add(ref)
                self._stats["duplicates_found"] += 1
                logger.warning(
                    "[butler] 注意: %s 已有历史记录, 请确认不是重复造轮子.",
                    ref,
                )

    def get_stats(self) -> Dict:
        return dict(self._stats)

    def get_perf_stats(self) -> Dict:
        """返回性能指标快照。"""
        return dict(self._perf_stats)

    def reset(self) -> None:
        """新会话重置。"""
        self._round_count = 0
        self._last_butler_round = 0
        self._processed_keys.clear()
        self._stats = {k: 0 for k in self._stats}
        self._perf_stats = {
            "cycles_run": 0,
            "total_duration_ms": 0,
            "avg_duration_ms": 0.0,
            "last_duration_ms": 0,
            "pg_writes_ok": 0,
            "pg_writes_fail": 0,
            "glm_calls": 0,
            "glm_errors": 0,
        }
