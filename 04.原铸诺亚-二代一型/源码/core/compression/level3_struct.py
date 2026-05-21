#!/usr/bin/env python3
"""
NEP-002 L3 结构化压缩 — CtxBeGone HDR + essence-log 五段式 + 任务卡

三种输出格式:
  1. essence_log — 冷区缓存行（五段式卡片）
  2. work_order  — CtxBeGone HDR 工单（零上下文推理）
  3. task_card   — 任务卡归档格式

用法:
    from core.compression import compress

    log   = compress(text, level=3, format='essence_log')
    order = compress(text, level=3, format='work_order')
    card  = compress(text, level=3, format='task_card')

    # 自动检测格式
    result = compress(text, level=3)

返回:
    dict — 结构化卡片 JSON
"""

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── 常量 ───

ESSENCE_LOG_TAGS = ["need", "method", "decision", "action", "output"]
ESSENCE_LOG_MARKERS = {
    "【需】": "need", "【方】": "method", "【决】": "decision",
    "【行】": "action", "【产】": "output",
}

DEFAULT_MAX_ITEMS = 300
DEFAULT_TOKEN_BUDGET = 3500

SUPPORTED_FORMATS = ("essence_log", "work_order", "task_card", "auto")

# ─── 主入口 ───


def compress(text: str, format: str = "auto",
             rounds: int = 0, tags: list = None,
             task_type: str = "general",
             router_result: dict = None,
             **kwargs) -> dict:
    """L3 结构化压缩主入口

    Args:
        text:      输入文本（原始或已去噪）
        format:    输出格式 ('auto'|'essence_log'|'work_order'|'task_card')
        rounds:    对话轮次（用于 essence_log 编号）
        tags:      标签列表（用于 essence_log/task_card）
        task_type: 任务类型（用于 work_order/task_card）
        router_result: 路由分析结果（可选，work_order 专用）
        **kwargs:  扩展参数

    Returns:
        dict: 结构化卡片

    Raises:
        ValueError: format 不合法
    """
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"不支持的格式: {format}，可选: {SUPPORTED_FORMATS}")

    if format == "auto":
        format = _detect_format(text, rounds, tags)

    if format == "essence_log":
        return build_essence_log(text, rounds=rounds, tags=tags, **kwargs)
    elif format == "work_order":
        return build_work_order(text, task_type=task_type,
                                router_result=router_result, **kwargs)
    elif format == "task_card":
        return build_task_card(text, rounds=rounds, tags=tags,
                               task_type=task_type, **kwargs)

    raise ValueError(f"内部错误：未处理的 format={format}")


# ─── 格式检测 ───


def _detect_format(text: str, rounds: int = 0,
                   tags: list = None) -> str:
    """自动检测最佳输出格式"""
    if not text or not text.strip():
        return "essence_log"

    # 1. 包含结构化标记 → essence_log
    if any(m in text for m in ESSENCE_LOG_MARKERS):
        return "essence_log"

    # 2. 多轮次且有标签 → essence_log
    if rounds > 10 and tags:
        return "essence_log"

    # 3. 新任务关键词 → work_order
    task_keywords = ["做", "执行", "需要", "任务", "工单", "create",
                     "build", "implement", "fix", "write", "设计"]
    first_line = text.strip().split("\n")[0][:50]
    if any(kw in first_line for kw in task_keywords):
        return "work_order"

    # 4. 默认
    return "essence_log"


# ─── essence_log 构建器 ───


def build_essence_log(text: str, rounds: int = 0,
                      tags: list = None, **kwargs) -> dict:
    """构建 essence-log 五段式卡片

    提取策略（按优先级）：
    1. 如果输入包含明确标记【需】【方】【决】【行】【产】→ 直接解析
    2. 如果是 dict/CompressedMemory-like → 从字段映射
    3. 纯文本 → LLM辅助提取或规则降级
    """
    items = []
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    _tags = tags or []

    # 策略1：有结构化标记
    if any(m in text for m in ESSENCE_LOG_MARKERS):
        parsed = _parse_essence_log_marked(text)
        # 填充缺失字段
        for f in ESSENCE_LOG_TAGS:
            if f not in parsed:
                parsed[f] = ""
        items.append({
            "id": f"el-{rounds or 0:03d}",
            "round": rounds,
            **parsed,
            "tags": _tags,
            "heat": kwargs.get("heat", 3),
            "ts": ts,
        })
        return _make_essence_log_output(items)

    # 策略2：有 CompressedMemory-like 结构（从 L2 传入）
    if isinstance(text, dict) or (
        hasattr(text, "decision") and hasattr(text, "action_items")
    ):
        parsed = _map_from_compressed(text)
        items.append({
            "id": f"el-{rounds or 0:03d}",
            "round": rounds,
            **parsed,
            "tags": _tags,
            "heat": kwargs.get("heat", 5),
            "ts": ts,
        })
        return _make_essence_log_output(items)

    # 策略3：纯文本 → LLM辅助
    llm_result = _llm_extract_essence(text)
    if llm_result and _all_fields_present(llm_result):
        items.append({
            "id": f"el-{rounds or 0:03d}",
            "round": rounds,
            **llm_result,
            "tags": _tags,
            "heat": kwargs.get("heat", 3),
            "ts": ts,
        })
        return _make_essence_log_output(items)

    # 策略4：规则降级 — 分块提取
    fallback = _fallback_extract(text)
    items.append({
        "id": f"el-{rounds or 0:03d}",
        "round": rounds,
        **fallback,
        "tags": _tags,
        "heat": kwargs.get("heat", 1),
        "ts": ts,
    })
    return _make_essence_log_output(items)


def _make_essence_log_output(items: list) -> dict:
    return {
        "format": "essence_log",
        "version": "1.0",
        "items": items,
    }


def _parse_essence_log_marked(text: str) -> dict:
    """解析【需】【方】【决】【行】【产】标记文本"""
    result = {}
    remaining = text
    for marker, field in ESSENCE_LOG_MARKERS.items():
        if marker in remaining:
            # 提取从本标记到下一个标记之间的内容
            parts = remaining.split(marker, 1)
            if len(parts) > 1:
                after = parts[1]
                # 找下一个标记
                next_marker_pos = len(after)
                for m in ESSENCE_LOG_MARKERS:
                    if m in after:
                        pos = after.index(m)
                        if pos < next_marker_pos:
                            next_marker_pos = pos
                value = after[:next_marker_pos].strip()
                result[field] = value
                remaining = marker + after[next_marker_pos:] if next_marker_pos < len(after) else after
    return result


def _map_from_compressed(compressed) -> dict:
    """从 CompressedMemory / dict 映射字段"""
    if isinstance(compressed, dict):
        cd = compressed
    else:
        cd = {
            "summary": getattr(compressed, "summary", ""),
            "key_points": getattr(compressed, "key_points", []),
            "decisions": getattr(compressed, "decisions", []),
            "action_items": getattr(compressed, "action_items", []),
        }

    kp = cd.get("key_points", [])
    dec = cd.get("decisions", [])
    act = cd.get("action_items", [])

    return {
        "need": cd.get("summary", "")[:120] if cd.get("summary") else (
            kp[0] if kp else ""),
        "method": "; ".join(kp[:2]) if kp else "",
        "decision": "; ".join(dec) if dec else (kp[-1] if kp else ""),
        "action": "; ".join(act) if act else "",
        "output": cd.get("outputs", []),
    }


def _llm_extract_essence(text: str) -> Optional[dict]:
    """调 qwen3:4b-instruct 提取 essence-log"""
    prompt = f"""请将以下对话压缩为 essence-log 格式。只输出五段式内容，不要额外说明。

【需】原始需求/问题（一句话）
【方】方案/方法（1-2句）
【决】决策/结论（1句）
【行】已执行操作（1-2句）
【产】产出物路径（文件/工具名，无则写"无"）

---
{text[:2000]}
---
"""
    try:
        import httpx, os
        # 清理代理，确保直连
        for var in ["HTTP_PROXY","HTTPS_PROXY","ALL_PROXY",
                     "http_proxy","https_proxy","all_proxy"]:
            os.environ.pop(var, None)
        api_key = "<API_KEY>"
        with httpx.Client(timeout=60) as c:
            r = c.post("https://api.deepseek.com/v1/chat/completions", json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "temperature": 0.1,
                "max_tokens": 300,
            }, headers={"Authorization": f"Bearer {api_key}"})
            data = r.json()
            output = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if not output:
            return None

        parsed = _parse_essence_log_marked(output)
        if _all_fields_present(parsed):
            return parsed

        # 尝试宽松解析
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        if len(lines) >= 5:
            return {
                "need": lines[0][:120],
                "method": lines[1][:200],
                "decision": lines[2][:200],
                "action": lines[3][:200],
                "output": lines[4] if len(lines) > 4 else "",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _fallback_extract(text: str) -> dict:
    """规则降级：按轮次分块，首句为need，尾句为decision"""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    sentences = []
    for p in paragraphs:
        sentences.extend(s.strip() for s in p.split("。") if s.strip())

    return {
        "need": sentences[0][:120] if sentences else text[:120],
        "method": sentences[1][:200] if len(sentences) > 1 else "",
        "decision": sentences[-1][:200] if len(sentences) > 2 else "",
        "action": sentences[2][:200] if len(sentences) > 3 else "",
        "output": "",
    }


def _all_fields_present(d: dict) -> bool:
    """检查五段式字段是否齐全"""
    return all(d.get(f) for f in ESSENCE_LOG_TAGS)


# ─── work_order 构建器 ───


def build_work_order(text: str, task_type: str = "general",
                     router_result: dict = None, **kwargs) -> dict:
    """构建 CtxBeGone HDR 工单"""
    task_text = text.strip()[:200]

    if router_result:
        intent = router_result.get("intent", "work")
        keywords = router_result.get("keywords", [])
        relations = router_result.get("relations", [])
        mood = router_result.get("mood", {"state": "neutral", "score": 50})
        suggest = router_result.get("suggest_load", [])
        trigger = router_result.get("trigger")
        tools = [r.split(":", 1)[1] for r in relations
                 if isinstance(r, str) and r.startswith("tool:")]
    else:
        intent = _detect_intent(task_text)
        keywords = []
        relations = []
        mood = {"state": "neutral", "score": 50}
        tools = []
        trigger = None

    notes = kwargs.get("notes", "")
    eval_parts = []
    if keywords:
        eval_parts.append(f"关键词: {', '.join(keywords[:8])}")
    if relations:
        eval_parts.append(f"关联: {', '.join(str(r) for r in relations[:6])}")
    if trigger:
        eval_parts.append(f"触发: {trigger.get('desc', str(trigger))}")

    return {
        "format": "work_order",
        "version": "1.0",
        "task": task_text,
        "intent": intent,
        "type": task_type,
        "tools": tools or ["none"],
        "notes": notes or "无额外上下文",
        "evaluation": " | ".join(eval_parts) if eval_parts else "标准流程",
        "relations": [str(r) for r in relations[:6]] if relations else [],
        "mood": mood,
    }


def _detect_intent(text: str) -> str:
    """简单意图检测"""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["调研", "研究", "分析", "调查", "research", "analyze"]):
        return "research"
    if any(kw in text_lower for kw in ["修复", "修", "改", "fix", "bug"]):
        return "fix"
    if any(kw in text_lower for kw in ["设计", "方案", "design", "architect"]):
        return "design"
    if any(kw in text_lower for kw in ["写", "创建", "生成", "write", "create", "generate"]):
        return "write"
    return "work"


# ─── task_card 构建器 ───


def build_task_card(text: str, rounds: int = 0,
                    tags: list = None, task_type: str = "general",
                    **kwargs) -> dict:
    """构建任务卡归档格式"""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    task_id = kwargs.get("task_id", f"TFC-{rounds:03d}")
    priority = kwargs.get("priority", "medium")
    _tags = tags or []

    # 从essence-log格式解析
    if isinstance(text, dict) and text.get("format") == "essence_log":
        items = text.get("items", [])
        if items:
            item = items[0]
            return {
                "format": "task_card",
                "version": "1.0",
                "id": task_id,
                "title": item.get("need", "")[:80],
                "type": task_type,
                "status": kwargs.get("status", "active"),
                "priority": priority,
                "tags": _tags or item.get("tags", []),
                "summary": item.get("need", ""),
                "key_decisions": [item.get("decision", "")],
                "outputs": [item.get("output", "")] if item.get("output") else [],
                "session": kwargs.get("session", ""),
                "created": ts,
                "updated": ts,
            }

    # 纯文本模式
    lines = text.strip().split("\n")
    title = lines[0][:80] if lines else "未命名任务"

    return {
        "format": "task_card",
        "version": "1.0",
        "id": task_id,
        "title": title,
        "type": task_type,
        "status": kwargs.get("status", "active"),
        "priority": priority,
        "tags": _tags,
        "summary": text[:300] if text else "",
        "key_decisions": [],
        "outputs": [],
        "session": kwargs.get("session", ""),
        "created": ts,
        "updated": ts,
    }


# ─── 工具函数 ───


def parse_essence_log_tags(text: str) -> dict:
    """从文本中解析【需】【方】【决】【行】【产】标记"""
    return _parse_essence_log_marked(text)


def merge_essence_logs(existing: list, new_items: list,
                       max_items: int = DEFAULT_MAX_ITEMS) -> list:
    """合并 essence-log 列表，去重+排序+裁剪"""
    seen_rounds = set()
    merged = []

    # 已有的
    for item in existing:
        r = item.get("round")
        if r is not None:
            seen_rounds.add(r)
        merged.append(item)

    # 新增的（去重）
    for item in new_items:
        r = item.get("round")
        if r is not None and r in seen_rounds:
            continue
        if r is not None:
            seen_rounds.add(r)
        merged.append(item)

    # 按 round 降序排序
    merged.sort(key=lambda x: x.get("round", 0), reverse=True)

    # 超额裁剪（低 heat 优先淘汰）
    if len(merged) > max_items:
        merged.sort(key=lambda x: (
            x.get("heat", 0),
            x.get("round", 0)
        ), reverse=True)
        merged = merged[:max_items]

    return merged


def essence_log_to_text(items: list) -> str:
    """将 essence-log 列表转为可读文本"""
    lines = []
    for item in items:
        parts = []
        for field in ESSENCE_LOG_TAGS:
            val = item.get(field, "")
            if val:
                marker_map = {v: k for k, v in ESSENCE_LOG_MARKERS.items()}
                parts.append(f"{marker_map.get(field, f'[{field}]')} {val}")
        if parts:
            lines.append("\n".join(parts))
            lines.append("---")
    return "\n".join(lines)


def estimate_token_count(card: dict) -> int:
    """估算结构化卡片的token数（4字符 ≈ 1 tok）"""
    text = json.dumps(card, ensure_ascii=False)
    return len(text) // 4


# ─── CLI 入口 ───


def main():
    import sys
    if len(sys.argv) < 2:
        print("用法: python3 level3_struct.py <text> [--format essence_log|work_order|task_card]")
        print("       python3 level3_struct.py --interactive")
        sys.exit(1)

    if sys.argv[1] == "--interactive":
        print("L3 结构化压缩 — 交互模式（输入exit退出）")
        while True:
            try:
                text = input("\n> ").strip()
                if text.lower() in ("exit", "q"):
                    break
                if not text:
                    continue
                fmt = "auto"
                if " --format " in text:
                    parts = text.split(" --format ")
                    text = parts[0]
                    fmt = parts[1].strip()
                result = compress(text, format=fmt)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                print(f"[Token估算: ~{estimate_token_count(result)} tok]")
            except KeyboardInterrupt:
                break
        return

    text = " ".join(sys.argv[1:])
    fmt = "auto"
    if " --format " in text:
        parts = text.split(" --format ")
        text = parts[0]
        fmt = parts[1].strip()

    result = compress(text, format=fmt)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[Token估算: ~{estimate_token_count(result)} tok]")


if __name__ == "__main__":
    main()
