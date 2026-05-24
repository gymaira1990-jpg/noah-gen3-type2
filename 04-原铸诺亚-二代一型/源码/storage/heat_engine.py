#!/usr/bin/env python3
"""热度引擎 · 三级热度计算 + 轮次衰减 + 空闲冻结 + 水线检测

热度系统设计（NEP-004 第四章）:
  L1(HOT区)     : heat ≥ 25, 衰减率 0.985
  L2(常温区)    : 15 ≤ heat < 25, 衰减率 0.975
  L3(冷区)      : 5  ≤ heat < 15, 衰减率 0.965
  archive(仓库)  : heat < 5, 衰减率 0.95

热度公式:
  heat = base + frequency_bonus + recency_bonus + importance_bonus
  范围: 0.5 ~ 50.0 (永不清零，永不超限)

用法:
  python3 heat_engine.py status             → 查看状态
  python3 heat_engine.py put <text> <intent> → 写入记录
  python3 heat_engine.py read [budget]       → 组装输出
  python3 heat_engine.py bump <id1> [id2..]  → 热度命中更新
  python3 heat_engine.py decay <round> [idle_minutes]
  python3 heat_engine.py rank <level>        → 按有效热度排序
  python3 heat_engine.py check <level>       → 水位检测
  python3 heat_engine.py test                → 运行完整性测试

归属: N-EMBRYO · NEP-004 上下文常态化架构
"""

import json, os, sys, time, uuid
from pathlib import Path
from datetime import datetime, timezone

# ─── 常量 ────────────────────────────────────────────────────────

# 存储路径
DATA_DIR = Path.home() / ".hermes" / "knowledge" / "soft-context"
DATA_FILE = DATA_DIR / "heat-engine.json"

# 降级回退文件
FALLBACK_FILE = Path.home() / "noah-embryo" / "data" / "memory" / "recent-memory.json"

# 数据模型版本
DATA_VERSION = 1

# 热度范围
HEAT_MIN = 0.5
HEAT_MAX = 50.0

# 衰减率（按层级）
DECAY_RATES = {
    "L1": 0.985,
    "L2": 0.975,
    "L3": 0.965,
    "archive": 0.95,
}

# 层级容量（用于水位检测）
CAPACITIES = {
    "L1": 30,
    "L2": 100,
    "L3": 500,
}

# Token预算（每条估算）
TOKEN_PER_ITEM = {
    "L1": 80,
    "L2": 60,
    "L3": 40,
}

# 空闲冻结阈值（分钟）
IDLE_THRESHOLD = 30

# 恢复升温系数（空闲冻结解除后）
IDLE_RECOVERY_MULT = 1.01

# 访问间隔衰减（仅用于排序，不持久化）
ACCESS_DECAY_INTERVALS = [
    (0, 10,   1.0),     # 最近10轮有访问 → 不衰减
    (10, 20,  0.8),
    (20, 50,  0.5),
    (50, 100, 0.3),
    (100,     0.1),     # 100轮以上无访问
]

# 意图重要性加分
INTENT_BONUS = {
    "work":      5,
    "fix":       8,
    "decision":  10,
    "arch":      6,
    "task":      6,
    "question":  0,
    "chat":      0,
    "unknown":   0,
}

# ─── 数据管理 ─────────────────────────────────────────────────────

def _init_data():
    """返回空数据结构的副本"""
    return {
        "version": DATA_VERSION,
        "total_rounds": 0,
        "last_decay_round": 0,
        "last_idle_round": 0,
        "items": {
            "L1": [],
            "L2": [],
            "L3": [],
            "archive": {"count": 0},
        },
    }


def _get_storage_dir() -> Path:
    """确保存储目录存在"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def _load_data() -> dict:
    """从文件加载数据，不存在则初始化"""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 确保关键字段存在
            if "items" not in data:
                data["items"] = {"L1": [], "L2": [], "L3": [], "archive": {"count": 0}}
            for level in ["L1", "L2", "L3"]:
                if level not in data["items"]:
                    data["items"][level] = []
            if "archive" not in data["items"]:
                data["items"]["archive"] = {"count": 0}
            if "version" not in data:
                data["version"] = DATA_VERSION
            return data
        except (json.JSONDecodeError, KeyError):
            print("警告: 数据文件损坏，重新初始化", file=sys.stderr)

    # 尝试从旧 recent-memory.json 降级读取
    if FALLBACK_FILE.exists():
        try:
            with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            data = _init_data()
            data["total_rounds"] = old.get("total_rounds", 0)
            # 将旧 light/mid/heavy 映射到 L1/L2/L3
            for item in old.get("light", []):
                data["items"]["L1"].append(_old_to_new_item(item, "L1"))
            for item in old.get("mid", []):
                data["items"]["L2"].append(_old_to_new_item(item, "L2"))
            for item in old.get("heavy", []):
                data["items"]["L3"].append(_old_to_new_item(item, "L3"))
            data["items"]["archive"]["count"] = old.get("archived", 0)
            _save_data(data)
            print(f"已从旧文件 {FALLBACK_FILE} 迁移数据", file=sys.stderr)
            return data
        except (json.JSONDecodeError, KeyError):
            pass

    return _init_data()


def _old_to_new_item(old: dict, level: str) -> dict:
    """将 recent-memory.py 旧格式转换为新格式"""
    now_iso = datetime.now(timezone.utc).isoformat()
    heat = _calc_heat(
        intent=old.get("intent", "unknown"),
        freq=old.get("freq", 1),
        recency=1.0,
        importance_flags={},
    )
    return {
        "id": str(uuid.uuid4()),
        "round": old.get("round", 1),
        "text": old.get("text", ""),
        "intent": old.get("intent", "unknown"),
        "heat": min(HEAT_MAX, max(HEAT_MIN, heat)),
        "freq": old.get("freq", 1),
        "access_round": old.get("round", 1),
        "emotion_tag": None,
        "has_tasks": False,
        "importance_bonus": 0,
        "blood_refs": [],
        "created_at": old.get("ts", now_iso),
        "updated_at": now_iso,
    }


def _save_data(data: dict):
    """保存数据到文件"""
    _get_storage_dir()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── 热度公式 ─────────────────────────────────────────────────────

def _detect_importance_flags(text: str, intent: str) -> dict:
    """从文本中检测重要性标记"""
    text_lower = text.lower() if text else ""
    return {
        "has_decision": any(kw in text_lower for kw in
                            ["决定", "决策", "确定", "结论", "decision", "decide", "conclude"]),
        "has_file_path": any(kw in text_lower for kw in
                             ["/home/", "/mnt/", "/workspace", ".py", ".md", ".json",
                              "路径", "文件", "目录"]),
        "has_action_items": any(kw in text_lower for kw in
                                ["TODO", "待办", "下一步", "需要做", "fixme", "FIXME"]),
        "has_unfinished_tasks": any(kw in text_lower for kw in
                                    ["未完成", "进行中", "wip", "WIP", "继续"]),
        "is_emotion_event": intent in ("emotion", "feeling", "mood") or
                            any(kw in text_lower for kw in
                                ["生气", "难过", "着急", "urgent", "angry", "sad"]),
    }


def _calc_heat(intent: str, freq: int, recency: float,
               importance_flags: dict = None) -> float:
    """计算热度值

    Args:
        intent: 意图标签
        freq: 被检索次数
        recency: 新近度 (0.0~1.0), 越新越高
        importance_flags: 重要性标记字典

    Returns:
        热度值 (HEAT_MIN ~ HEAT_MAX)
    """
    base = 1.0
    frequency_bonus = freq * 2.0          # 每被检索+2分
    recency_bonus = max(0, recency) * 10.0  # 越新越高
    importance_bonus = 0

    # 意图加分
    importance_bonus += INTENT_BONUS.get(intent, 0)

    if importance_flags:
        if importance_flags.get("has_decision"):
            importance_bonus += 4
        if importance_flags.get("has_file_path"):
            importance_bonus += 2
        if importance_flags.get("has_action_items"):
            importance_bonus += 3
        if importance_flags.get("has_unfinished_tasks"):
            importance_bonus += 6
        if importance_flags.get("is_emotion_event"):
            importance_bonus += 5

    total = base + frequency_bonus + recency_bonus + importance_bonus
    return max(HEAT_MIN, min(HEAT_MAX, total))


def _calc_recency(item_round: int, current_round: int) -> float:
    """计算新近度 (0.0~1.0)"""
    if current_round <= 0:
        return 0.0
    delta = current_round - item_round
    if delta <= 0:
        return 1.0
    # 使用半衰期衰减: 半衰期 = 20 轮
    half_life = 20.0
    return max(0.0, 1.0 - delta / half_life)


def _get_access_decay_mult(rounds_since_access: int) -> float:
    """获取访问间隔衰减系数（仅用于排序）"""
    for interval in ACCESS_DECAY_INTERVALS:
        if len(interval) == 3:
            lo, hi, mult = interval
            if lo <= rounds_since_access < hi:
                return mult
        else:
            lo, mult = interval
            if rounds_since_access >= lo:
                return mult
    return 0.1


def _determine_level(heat: float) -> str:
    """根据热度值决定应在哪层"""
    if heat >= 25:
        return "L1"
    elif heat >= 15:
        return "L2"
    elif heat >= 5:
        return "L3"
    else:
        return "archive"


# ─── 核心接口 ────────────────────────────────────────────────────

def put(round_num: int, text: str, intent: str,
        emotion_tag: str = None, has_tasks: bool = False,
        blood_refs: list = None, file_refs: list = None):
    """写入一条记录

    Args:
        round_num: 轮次号
        text: 去噪后文本
        intent: 意图标签
        emotion_tag: 情感标签 (可选)
        has_tasks: 是否包含未完成任务
        blood_refs: 血缘引用列表 (可选)
        file_refs: 文件引用列表 (可选)
    """
    data = _load_data()

    # 更新总轮次
    if round_num > data["total_rounds"]:
        data["total_rounds"] = round_num

    # 检测重要性标记
    flags = _detect_importance_flags(text, intent)

    # 如果有文件引用，显式标记
    if file_refs:
        flags["has_file_path"] = True

    # 计算新近度
    recency = _calc_recency(round_num, data["total_rounds"])

    # 计算初始热度
    heat = _calc_heat(intent, 1, recency, flags)

    # 新条目强制入L1，层级变化由淘汰/衰减驱动
    level = "L1"

    now_iso = datetime.now(timezone.utc).isoformat()

    item = {
        "id": str(uuid.uuid4()),
        "round": round_num,
        "text": text,
        "intent": intent,
        "heat": heat,
        "freq": 1,
        "access_round": round_num,
        "emotion_tag": emotion_tag,
        "has_tasks": has_tasks or flags.get("has_action_items", False),
        "importance_bonus": INTENT_BONUS.get(intent, 0) +
                            (4 if flags.get("has_decision") else 0) +
                            (2 if flags.get("has_file_path") else 0) +
                            (3 if flags.get("has_action_items") else 0) +
                            (6 if flags.get("has_unfinished_tasks") else 0) +
                            (5 if flags.get("is_emotion_event") else 0),
        "blood_refs": blood_refs or [],
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    data["items"][level].append(item)
    _save_data(data)


def bump(item_ids: list):
    """热度更新：命中检索时调用

    Args:
        item_ids: 被命中的条目id列表
    """
    if not item_ids:
        return
    data = _load_data()
    id_set = set(item_ids)

    for level in ["L1", "L2", "L3"]:
        for item in data["items"][level]:
            if item["id"] in id_set:
                # 增加检索频率
                item["freq"] = item.get("freq", 1) + 1
                # 更新访问轮次
                item["access_round"] = data["total_rounds"]
                # 重新计算热度
                recency = _calc_recency(item["round"], data["total_rounds"])
                flags = _detect_importance_flags(item.get("text", ""), item.get("intent", ""))
                item["heat"] = _calc_heat(
                    item.get("intent", "unknown"),
                    item["freq"],
                    recency,
                    flags,
                )
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                break

    _save_data(data)


def decay(current_round: int, idle_minutes: int = 0):
    """衰减：每轮对话结束时调用

    Args:
        current_round: 当前轮次
        idle_minutes: 距离上次对话的分钟数 (空闲检测)
    """
    data = _load_data()

    # 空闲冻结检测
    if idle_minutes >= IDLE_THRESHOLD:
        # 跳过本轮衰减，记录空闲轮次
        data["last_idle_round"] = current_round
        # 但执行恢复升温（轻微）
        for level in ["L1", "L2", "L3"]:
            for item in data["items"][level]:
                item["heat"] = min(HEAT_MAX, item["heat"] * IDLE_RECOVERY_MULT)
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_data(data)
        return

    # 同轮不重复衰减
    if current_round <= data.get("last_decay_round", 0):
        return

    # 执行衰减
    for level in ["L1", "L2", "L3"]:
        rate = DECAY_RATES.get(level, 0.975)
        for item in data["items"][level]:
            old_heat = item["heat"]
            item["heat"] = max(HEAT_MIN, old_heat * rate)
            item["updated_at"] = datetime.now(timezone.utc).isoformat()

    data["last_decay_round"] = current_round
    _save_data(data)


def read(token_budget: int = 6000) -> str:
    """读取组装（供大模型加载）

    Args:
        token_budget: Token预算上限

    Returns:
        格式化后的上下文文本
    """
    data = _load_data()
    lines = []
    used_tokens = 0

    # 按层级顺序读取：L1 → L2 → L3
    for level in ["L1", "L2", "L3"]:
        items = data["items"].get(level, [])
        if not items:
            continue

        # 按热度降序排列
        sorted_items = sorted(items, key=lambda x: -x.get("heat", 0))

        level_lines = []
        level_tokens = 0

        for item in sorted_items:
            text = item.get("text", "")
            heat = item.get("heat", 0)
            rnd = item.get("round", 0)
            intent = item.get("intent", "unknown")
            freq = item.get("freq", 1)

            line = f"[R{rnd}|{intent}|heat={heat:.1f}|freq={freq}] {text}"
            line_tokens = len(line) // 2  # 粗略估算

            if used_tokens + level_tokens + line_tokens > token_budget:
                break

            level_lines.append(line)
            level_tokens += line_tokens

        if level_lines:
            level_name = {"L1": "🔥 HOT 热记忆区", "L2": "🌡️ 常温记忆区", "L3": "❄️ 冷记忆区"}.get(level, level)
            lines.append(f"═══ {level_name} ═══")
            lines.extend(level_lines)
            lines.append("")
            used_tokens += level_tokens

    # 添加汇总信息
    if data["items"]["L1"] or data["items"]["L2"] or data["items"]["L3"]:
        lines.append(f"--- 共{data['total_rounds']}轮 | "
                     f"L1:{len(data['items']['L1'])}条 | "
                     f"L2:{len(data['items']['L2'])}条 | "
                     f"L3:{len(data['items']['L3'])}条 | "
                     f"归档:{data['items']['archive']['count']}条 "
                     f"(预估{used_tokens} tokens)")

    return "\n".join(lines)


def status() -> dict:
    """状态查询

    Returns:
        状态字典
    """
    data = _load_data()

    # 计算各级汇总
    levels_info = {}
    total_heat = 0.0
    total_items = 0

    for level in ["L1", "L2", "L3"]:
        items = data["items"].get(level, [])
        if items:
            heats = [it.get("heat", 0) for it in items]
            avg_heat = sum(heats) / len(heats)
            max_heat = max(heats)
            min_heat = min(heats)
        else:
            avg_heat = max_heat = min_heat = 0.0

        total_heat += sum(it.get("heat", 0) for it in items)
        total_items += len(items)

        levels_info[level] = {
            "count": len(items),
            "avg_heat": round(avg_heat, 2),
            "max_heat": round(max_heat, 2),
            "min_heat": round(min_heat, 2),
        }

    levels_info["archive"] = {
        "count": data["items"]["archive"]["count"],
    }

    return {
        "version": data.get("version", DATA_VERSION),
        "total_rounds": data["total_rounds"],
        "last_decay_round": data.get("last_decay_round", 0),
        "last_idle_round": data.get("last_idle_round", 0),
        "total_items": total_items,
        "total_heat": round(total_heat, 2),
        "avg_heat": round(total_heat / max(total_items, 1), 2),
        "levels": levels_info,
        "data_file": str(DATA_FILE),
    }


def check_watermark(level: str) -> dict:
    """水位检测（供水线系统调用）

    Args:
        level: 缓存层级 ("L1", "L2", "L3")

    Returns:
        水位检测结果字典
    """
    data = _load_data()
    items = data["items"].get(level, [])
    capacity = CAPACITIES.get(level, 30)
    tokens_per = TOKEN_PER_ITEM.get(level, 60)

    current_tokens = len(items) * tokens_per
    budget_tokens = capacity * tokens_per
    watermark_pct = round((len(items) / max(capacity, 1)) * 100, 1)

    # 建议动作
    if watermark_pct >= 95:
        suggested_action = "emergency_evict"
    elif watermark_pct >= 85:
        suggested_action = "evict"
    elif watermark_pct >= 70:
        suggested_action = "pre_compress"
    else:
        suggested_action = "normal"

    return {
        "watermark_pct": watermark_pct,
        "current_tokens": current_tokens,
        "budget_tokens": budget_tokens,
        "items_count": len(items),
        "capacity_items": capacity,
        "suggested_action": suggested_action,
    }


def rank(level: str, include_decay: bool = True) -> list:
    """排序：按有效热度降序（用于淘汰决策）

    Args:
        level: 缓存层级
        include_decay: 是否应用访问间隔衰减

    Returns:
        按有效热度降序排列的条目列表
    """
    data = _load_data()
    items = data["items"].get(level, [])
    current_round = data["total_rounds"]

    scored = []
    for item in items:
        effective_heat = item.get("heat", 0)

        if include_decay:
            rounds_since_access = current_round - item.get("access_round", item.get("round", 0))
            decay_mult = _get_access_decay_mult(rounds_since_access)
            effective_heat = effective_heat * decay_mult

        scored.append({
            "id": item["id"],
            "heat": item.get("heat", 0),
            "effective_heat": round(effective_heat, 2),
            "round": item.get("round", 0),
            "access_round": item.get("access_round", 0),
            "text": item.get("text", "")[:60],
            "intent": item.get("intent", "unknown"),
            "freq": item.get("freq", 1),
        })

    scored.sort(key=lambda x: -x["effective_heat"])
    return scored


# ─── CLI 工具 ─────────────────────────────────────────────────────

def _cmd_status():
    s = status()
    print("═══ 热度引擎状态 ═══")
    print(f"  数据文件: {s['data_file']}")
    print(f"  版本: v{s['version']}")
    print(f"  总轮次: {s['total_rounds']}")
    print(f"  最后衰减轮: {s['last_decay_round']}")
    print(f"  最后空闲轮: {s['last_idle_round']}")
    print(f"  总条目: {s['total_items']}")
    print(f"  总热度: {s['total_heat']}")
    print(f"  平均热度: {s['avg_heat']}")
    print()
    for level in ["L1", "L2", "L3"]:
        info = s["levels"][level]
        wm = check_watermark(level)
        print(f"  {level}: {info['count']}条 | "
              f"热度 {info['min_heat']}~{info['max_heat']}(avg={info['avg_heat']}) | "
              f"水位 {wm['watermark_pct']}%")
    print(f"  archive: {s['levels']['archive']['count']}条")


def _cmd_put(args):
    if len(args) < 2:
        print("用法: put <文本> <意图> [--emotion TAG] [--tasks] [--refs id1,id2]")
        return
    text = args[0]
    intent = args[1] if len(args) > 1 else "unknown"

    emotion_tag = None
    has_tasks = False
    blood_refs = None

    for i, a in enumerate(args[2:], start=2):
        if a == "--emotion" and i + 1 < len(args):
            emotion_tag = args[i + 1]
        elif a == "--tasks":
            has_tasks = True
        elif a == "--refs" and i + 1 < len(args):
            blood_refs = [r.strip() for r in args[i + 1].split(",")]

    data = _load_data()
    round_num = data["total_rounds"] + 1
    put(round_num, text, intent, emotion_tag, has_tasks, blood_refs)
    print(f"已写入 第{round_num}轮 | intent={intent} | 热度已计算")


def _cmd_read(args):
    budget = int(args[0]) if args else 6000
    output = read(budget)
    print(output)


def _cmd_bump(args):
    if not args:
        print("用法: bump <id1> [id2 ...]")
        return
    bump(args)
    print(f"已更新热度: {args}")


def _cmd_decay(args):
    current_round = int(args[0]) if args else 0
    idle_minutes = int(args[1]) if len(args) > 1 else 0
    decay(current_round, idle_minutes)
    idle_note = f" (空闲{idle_minutes}分钟，跳过衰减→恢复升温)" if idle_minutes >= IDLE_THRESHOLD else ""
    print(f"第{current_round}轮衰减完成{idle_note}")


def _cmd_rank(args):
    level = args[0] if args else "L1"
    if level not in ("L1", "L2", "L3"):
        print("层级须为 L1/L2/L3")
        return
    results = rank(level)
    print(f"═══ {level} 按有效热度排序 ═══")
    for r in results:
        print(f"  heat={r['heat']:6.1f} | eff={r['effective_heat']:6.1f} | "
              f"R{r['round']:4d} | freq={r['freq']:2d} | "
              f"[{r['intent']}] {r['text']}")
    if not results:
        print("  (空)")


def _cmd_check(args):
    level = args[0] if args else "L1"
    if level not in ("L1", "L2", "L3"):
        print("层级须为 L1/L2/L3")
        return
    wm = check_watermark(level)
    print(f"═══ {level} 水位检测 ═══")
    for k, v in wm.items():
        print(f"  {k}: {v}")
    print(f"  建议: {wm['suggested_action']}")


def _cmd_test():
    """运行完整性测试"""
    print("═══ 热度引擎完整性测试 ═══\n")

    # 1. 备份当前数据
    backup = None
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            backup = f.read()

    # 清空数据
    _save_data(_init_data())

    errors = 0
    tests_passed = 0

    try:
        # --- 测试1: 写入 ---
        print("[测试1] 写入记录...")
        for i in range(1, 11):
            put(i, f"这是第{i}轮对话的内容", "work" if i % 2 == 0 else "chat")
        data = _load_data()
        total = len(data["items"]["L1"]) + len(data["items"]["L2"]) + len(data["items"]["L3"])
        assert total == 10, f"应有10条记录，实际{total}"
        tests_passed += 1
        print(f"  ✅ 写入10条成功 (L1:{len(data['items']['L1'])} "
              f"L2:{len(data['items']['L2'])} L3:{len(data['items']['L3'])})\n")

        # --- 测试2: 热度公式 ---
        print("[测试2] 热度公式验证...")
        h_work = _calc_heat("work", 1, 1.0, {"has_decision": True, "has_file_path": True,
                                              "has_action_items": False, "has_unfinished_tasks": False,
                                              "is_emotion_event": False})
        assert HEAT_MIN <= h_work <= HEAT_MAX, f"work热度超范围: {h_work}"
        assert h_work > 10, f"work+决策+文件 热度应>10: {h_work}"

        h_chat = _calc_heat("chat", 1, 0.1, {})
        assert h_chat <= h_work, f"chat热度({h_chat})不应高于work({h_work})"

        h_fix = _calc_heat("fix", 3, 1.0, {"has_decision": True})
        assert h_fix >= h_work, f"fix热度({h_fix})应高于work({h_work})"

        tests_passed += 1
        print(f"  ✅ 热度公式合理: work={h_work:.1f} chat={h_chat:.1f} fix={h_fix:.1f}\n")

        # --- 测试3: 衰减 ---
        print("[测试3] 衰减逻辑...")
        data = _load_data()
        heat_before = {}
        for level in ["L1", "L2", "L3"]:
            for item in data["items"][level]:
                heat_before[item["id"]] = item["heat"]

        decay(20, idle_minutes=0)
        data = _load_data()

        for item_id, old_heat in heat_before.items():
            # 找到更新后的条目
            for level in ["L1", "L2", "L3"]:
                for item in data["items"][level]:
                    if item["id"] == item_id:
                        assert item["heat"] <= old_heat, f"衰减后热度({item['heat']})应≤衰减前({old_heat})"
                        assert item["heat"] >= HEAT_MIN, f"热度不应低于{HEAT_MIN}"
                        break

        tests_passed += 1
        print(f"  ✅ 衰减正确: last_decay_round={data['last_decay_round']}, 最低热度={HEAT_MIN}\n")

        # --- 测试4: 空闲冻结 ---
        print("[测试4] 空闲冻结...")
        data = _load_data()
        heat_before_idle = {}
        for level in ["L1", "L2", "L3"]:
            for item in data["items"][level]:
                heat_before_idle[item["id"]] = item["heat"]

        decay(21, idle_minutes=45)  # 超过30分钟 → 空闲冻结
        data = _load_data()

        for item_id, old_heat in heat_before_idle.items():
            for level in ["L1", "L2", "L3"]:
                for item in data["items"][level]:
                    if item["id"] == item_id:
                        expected = min(HEAT_MAX, old_heat * IDLE_RECOVERY_MULT)
                        assert abs(item["heat"] - expected) < 0.01, \
                            f"空闲恢复后热度应为{expected:.2f}, 实际{item['heat']:.2f}"
                        break

        tests_passed += 1
        print(f"  ✅ 空闲冻结正确: 最后空闲轮={data['last_idle_round']}, 恢复系数={IDLE_RECOVERY_MULT}\n")

        # --- 测试5: bump ---
        print("[测试5] bump检索命中...")
        data = _load_data()
        # 找到有数据的层
        bump_level = None
        for lv in ["L1", "L2", "L3"]:
            if data["items"].get(lv):
                bump_level = lv
                break
        if bump_level:
            target_id = data["items"][bump_level][0]["id"]
            heat_before_bump = data["items"][bump_level][0]["heat"]
            freq_before = data["items"][bump_level][0]["freq"]

            bump([target_id])
            data = _load_data()
            new_heat = heat_before_bump
            for item in data["items"][bump_level]:
                if item["id"] == target_id:
                    assert item["freq"] == freq_before + 1, f"freq应+1: {item['freq']} vs {freq_before+1}"
                    assert HEAT_MIN <= item["heat"] <= HEAT_MAX, f"热度超范围: {item['heat']}"
                    new_heat = item["heat"]
                    break
            tests_passed += 1
            print(f"  ✅ bump成功: freq {freq_before}→{freq_before+1}, "
                  f"heat {heat_before_bump:.1f}→{new_heat:.1f}\n")
        else:
            print(f"  ⚠️ 跳过bump测试（无数据）\n")

        # --- 测试6: read ---
        print("[测试6] read组装...")
        output = read(token_budget=2000)
        assert len(output) > 0, "read输出不应为空"
        assert "HOT" in output or "L1" in output, "应包含HOT区标记"
        tests_passed += 1
        print(f"  ✅ read输出成功 ({len(output)} chars)\n")

        # --- 测试7: check_watermark ---
        print("[测试7] 水位检测...")
        wm_l1 = check_watermark("L1")
        assert "watermark_pct" in wm_l1
        assert "suggested_action" in wm_l1
        tests_passed += 1
        print(f"  ✅ L1水位: {wm_l1['watermark_pct']}% → {wm_l1['suggested_action']}\n")

        # --- 测试8: rank ---
        print("[测试8] 排序...")
        # 寻找有数据的层级
        rank_level = "L2"
        for lv in ["L1", "L2", "L3"]:
            if data["items"].get(lv):
                rank_level = lv
                break
        ranked = rank(rank_level)
        assert len(ranked) > 0, f"{rank_level} rank结果不应为空"
        if len(ranked) > 1:
            assert ranked[0]["effective_heat"] >= ranked[-1]["effective_heat"], "应降序排列"
        tests_passed += 1
        print(f"  ✅ rank排序正确 ({len(ranked)}条, 层级={rank_level})\n")

        # --- 测试9: 热度范围 ---
        print("[测试9] 热度范围验证...")
        for level in ["L1", "L2", "L3"]:
            for item in data["items"][level]:
                assert HEAT_MIN <= item["heat"] <= HEAT_MAX, \
                    f"热度超范围: {item['heat']} (id={item['id'][:8]})"
        tests_passed += 1
        print(f"  ✅ 所有条目热度在 [{HEAT_MIN}, {HEAT_MAX}] 范围内\n")

        # --- 测试10: status ---
        print("[测试10] status...")
        s = status()
        assert s["total_rounds"] >= 10
        assert "levels" in s
        tests_passed += 1
        print(f"  ✅ status成功: {s['total_items']}条, {s['total_rounds']}轮\n")

        print(f"═══ 测试结果: {tests_passed}/10 通过, {errors} 错误 ═══")

    except AssertionError as e:
        errors += 1
        print(f"  ❌ 断言失败: {e}")
    except Exception as e:
        errors += 1
        print(f"  ❌ 异常: {e}")
    finally:
        # 恢复原始数据
        if backup:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                f.write(backup)
        else:
            _save_data(_init_data())


def main():
    if len(sys.argv) < 2:
        print("用法: python3 heat_engine.py {status|put|read|bump|decay|rank|check|test} [参数]")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "status": _cmd_status,
        "put": lambda: _cmd_put(args),
        "read": lambda: _cmd_read(args),
        "bump": lambda: _cmd_bump(args),
        "decay": lambda: _cmd_decay(args),
        "rank": lambda: _cmd_rank(args),
        "check": lambda: _cmd_check(args),
        "test": _cmd_test,
    }

    fn = commands.get(cmd)
    if fn:
        fn()
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: status put read bump decay rank check test")


if __name__ == "__main__":
    main()
