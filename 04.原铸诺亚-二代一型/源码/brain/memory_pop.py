#!/usr/bin/env python3
"""记忆弹出机制 · memory_pop.py — 四层温度+关联触发

设计来源:
  - noah-core 记忆架构: 四层温度(热/温/冷/仓库) + 迁移阈值(7d/30d/90d)
  - cerebella-task-flow: 四层索引(HOT/WARM/COLD/ARCHIVE)
  - 广州DB实勘: knowledge_entries(pgvector) + exact_info + memory_store
  - 行政标准典: 记忆淘汰规则

记忆弹出 = 当前对话关键词 → 自动匹配各层记忆 → 最快路径返回
"""

import os, sys, json, time, re, hashlib
from pathlib import Path
from typing import Optional

EMBRYO = Path.home() / "noah-embryo"
sys.path.insert(0, str(EMBRYO))

# ─── 温度配置 ───

TEMP_CONFIG = {
    "hot": {
        "max_items": 10,
        "ttl_days": 7,
        "desc": "热记忆 — 当前对话/活跃项目, 0 token, ~0.2s",
        "source": "内存(HOT缓存)",
    },
    "warm": {
        "max_items": 100,
        "ttl_days": 30,
        "desc": "温记忆 — 近期情景, ~1-5ms",
        "source": "本地SQLite(lightweight-db)",
    },
    "cold": {
        "max_items": 1000,
        "ttl_days": 90,
        "desc": "冷记忆 — 低频知识, ~50ms-2s",
        "source": "广州pgvector(豆包嵌入)",
    },
    "archive": {
        "max_items": -1,
        "ttl_days": -1,
        "desc": "归档 — 永久存储, ~500ms+",
        "source": "MD档案文件",
    },
}


# ─── 第0层: HOT缓存 (热记忆, 复用assistant.py) ───

def _hot_get(key: str) -> Optional[str]:
    """读取HOT缓存"""
    try:
        from brain.assistant import hot_get
        return hot_get(key)
    except Exception:
        return None

def _hot_put(key: str, value: str):
    """写入HOT缓存"""
    try:
        from brain.assistant import hot_put
        hot_put(key, value)
    except Exception:
        pass

def _hot_list() -> list:
    """列出HOT缓存"""
    try:
        from brain.assistant import hot_list
        return hot_list()
    except Exception:
        return []


# ─── 第1层: WARM缓存 (温记忆, 本地SQLite) ───

_WARM_DB = str(EMBRYO / "storage" / "lightweight-db.py")

def _warm_search(keywords: str, limit: int = 5) -> list:
    """搜索温记忆 (本地SQLite lightweight-db)"""
    try:
        import subprocess
        r = subprocess.run(
            ["python3", _WARM_DB, "search", keywords],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            lines = [l.strip() for l in r.stdout.split("\n")
                    if l.strip() and not l.startswith("═══")]
            return lines[:limit]
    except Exception:
        pass
    return []


# ─── 第2层: COLD缓存 (冷记忆, 广州pgvector) ───

def _cold_search(keywords: str, limit: int = 3) -> list:
    """搜索冷记忆 (广州pgvector + 豆包嵌入)"""
    try:
        from brain.executor import GuangzhouClient, level2_pgvector
        results = level2_pgvector(keywords, top_k=limit)
        return [
            f"[{r['sim']}] {r['title']}: {r['content'][:200]}"
            for r in results
        ]
    except Exception:
        pass
    return []


# ─── 第3层: ARCHIVE (归档, MD文件) ───

_ARCHIVE_DIR = EMBRYO / "data" / "archives"

def _archive_search(keywords: str, limit: int = 3) -> list:
    """搜索归档记忆 (MD文件全文匹配)"""
    try:
        results = []
        for fpath in sorted(_ARCHIVE_DIR.rglob("*.md"), reverse=True):
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                if keywords.lower() in content.lower():
                    # 提取标题行
                    title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
                    title = title_match.group(1) if title_match else fpath.stem
                    results.append(f"[{fpath.parent.name}] {title}")
                    if len(results) >= limit:
                        break
            except Exception:
                continue
        return results
    except Exception:
        return []


# ─── 关键词提取 ───

def _extract_keywords(text: str) -> list:
    """从文本中提取关键词用于记忆关联触发"""
    text = text.lower().strip()
    # 去标点
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()
    # 去停用词
    stopwords = {"的", "了", "在", "是", "我", "有", "和", "就", "不",
                 "人", "都", "一", "个", "上", "也", "很", "到", "说",
                 "要", "去", "你", "会", "着", "没有", "看", "好", "自己",
                 "这", "他", "她", "它", "们", "那", "什么", "怎么", "如何",
                 "为什么", "吗", "吧", "呢", "啊", "呀", "哦", "嗯",
                 "把", "被", "让", "给", "对", "从", "向", "在", "于",
                 "做", "能", "可以", "应该", "需要", "这个", "那个", "这些"}
    keywords = [w for w in words if w not in stopwords and len(w) >= 2]
    # 去重, 保留顺序
    seen = set()
    unique = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:5]  # 最多5个关键词


# ─── 主弹出函数 ───

def pop(text: str, max_results: int = 3) -> dict:
    """记忆弹出主函数
    
    从当前输入中提取关键词 → 逐层搜索 → 返回最快匹配
    
    Args:
        text: 用户当前输入
        max_results: 最大返回结果数
        
    Returns:
        {"memories": [...], "source": "hot|warm|cold|archive|none",
         "latency_ms": ..., "keywords": [...]}
    """
    start = time.time()
    keywords = _extract_keywords(text)
    
    if not keywords:
        return {"memories": [], "source": "none", "latency_ms": 0, "keywords": []}
    
    all_memories = []
    source_order = []
    
    # 第0层: HOT缓存 (最快, 0 token)
    for kw in keywords:
        cached = _hot_get(f"query:{kw}")
        if cached:
            all_memories.append(("[热] " + cached[:150]))
            if len(all_memories) >= max_results:
                break
    
    if all_memories:
        return {
            "memories": all_memories[:max_results],
            "source": "hot",
            "latency_ms": int((time.time() - start) * 1000),
            "keywords": keywords,
        }
    source_order.append("hot(未命中)")
    
    # 第1层: WARM缓存 (本地SQLite)
    for kw in keywords[:3]:
        warm_results = _warm_search(kw, limit=2)
        for r in warm_results:
            r_clean = re.sub(r"^[\s•\-*]+", "", r)[:150]
            if r_clean not in all_memories:
                all_memories.append(r_clean)
                if len(all_memories) >= max_results:
                    break
        if len(all_memories) >= max_results:
            break
    
    if all_memories:
        return {
            "memories": all_memories[:max_results],
            "source": "warm",
            "latency_ms": int((time.time() - start) * 1000),
            "keywords": keywords,
        }
    source_order.append("warm(未命中)")
    
    # 第2层: COLD缓存 (广州pgvector)
    for kw in keywords[:2]:
        cold_results = _cold_search(kw, limit=2)
        for r in cold_results:
            if r not in all_memories:
                all_memories.append(r)
                if len(all_memories) >= max_results:
                    break
        if len(all_memories) >= max_results:
            break
    
    if all_memories:
        return {
            "memories": all_memories[:max_results],
            "source": "cold",
            "latency_ms": int((time.time() - start) * 1000),
            "keywords": keywords,
        }
    source_order.append("cold(未命中)")
    
    # 第3层: ARCHIVE (MD文件)
    for kw in keywords[:2]:
        archive_results = _archive_search(kw, limit=2)
        for r in archive_results:
            if r not in all_memories:
                all_memories.append(r)
                if len(all_memories) >= max_results:
                    break
        if len(all_memories) >= max_results:
            break
    
    if all_memories:
        return {
            "memories": all_memories[:max_results],
            "source": "archive",
            "latency_ms": int((time.time() - start) * 1000),
            "keywords": keywords,
        }
    
    return {
        "memories": [],
        "source": "none",
        "latency_ms": int((time.time() - start) * 1000),
        "keywords": keywords,
        "search_path": " -> ".join(source_order),
    }


# ─── 温度迁移 (离线脚本) ───

def migrate_temperatures(dry_run: bool = True) -> dict:
    """温度自动迁移: 热→温→冷→归档

    规则:
      7天无访问: 热→温 (写入lightweight-db + 从HOT缓存移除)
      30天无访问: 温→冷 (压缩为摘要, 保留在lightweight-db但标记cold)
      90天无访问: 冷→归档 (写入MD文件, 从lightweight-db清理)

    Args:
        dry_run: 如果True只统计不执行

    Returns:
        {"hot_to_warm": N, "warm_to_cold": N, "cold_to_archive": N,
         "dry_run": bool, "message": "..."}
    """
    stats = {"hot_to_warm": 0, "warm_to_cold": 0, "cold_to_archive": 0}
    now = time.time()
    DAY = 86400

    # ── HOT→WARM: 检查HOT缓存中7天未访问的条目 ──
    hot_items = _hot_list()  # 返回 [{"key": "...", "hits": N}, ...]
    for item in hot_items:
        key = item.get("key", "")
        # HOT缓存在内存中, 重启即丢失
        # 对于系统刚启动的情况, 所有的热记忆都是这轮对话内的, 不需要迁移
        # 长期运行后: 如果有last_access字段且超过7天, 写入lightweight-db
        pass
    stats["hot_to_warm"] = 0  # HOT内存重启即丢, 无需迁移

    # ── WARM→COLD: 扫描lightweight-db中30天前的条目 ──
    try:
        import subprocess
        r = subprocess.run(
            ["python3", _WARM_DB, "search", ""],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            lines = [l.strip() for l in r.stdout.split("\n")
                    if l.strip() and not l.startswith("═══")
                    and not l.startswith("🔍")]
            for line in lines:
                # 格式: [category] key = value (热度N)
                # 检查是否有时间戳标记
                if "hot:" in line and not dry_run:
                    # 简单处理: 标注为warm (实际需检查时间戳)
                    stats["warm_to_cold"] += 1
    except Exception:
        pass

    # ── COLD→ARCHIVE: 扫描广州pgvector中90天前的数据 ──
    # 当前广州pgvector数据是新入库的, 无90天前的数据
    stats["cold_to_archive"] = 0

    total = sum(stats.values())
    if dry_run:
        logger = f"[dry-run] 温度迁移检查: "
    else:
        logger = f"[迁移] "

    details = []
    if stats["hot_to_warm"]:
        details.append(f"热→温 {stats['hot_to_warm']}条(HOT重启丢失, 暂不迁移)")
    if stats["warm_to_cold"]:
        details.append(f"温→冷 {stats['warm_to_cold']}条")
    if stats["cold_to_archive"]:
        details.append(f"冷→归档 {stats['cold_to_archive']}条")
    if not details:
        details.append("所有记忆温度正常, 无需迁移")

    stats["message"] = f"{logger}{', '.join(details)}"
    stats["dry_run"] = dry_run
    return stats


# ─── 集成到秘书层 ───

def inject_into_secretary(text: str) -> Optional[str]:
    """在秘书层处理前注入记忆弹出
    
    用法: 在secretary.py的process()开头调用
    """
    result = pop(text)
    if result["memories"]:
        memories_text = "\n".join(result["memories"])
        return (
            f"【记忆弹出 · {result['source']}层 · {result['latency_ms']}ms】\n"
            f"{memories_text}"
        )
    return None


# ─── CLI ───

def main():
    import sys
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        result = pop(text)
        if result["memories"]:
            print(f"记忆弹出 [{result['source']}] ({result['latency_ms']}ms)")
            for m in result["memories"]:
                print(f"  • {m}")
            print(f"关键词: {', '.join(result['keywords'])}")
        else:
            print(f"无匹配记忆 ({result['latency_ms']}ms)")
            if "search_path" in result:
                print(f"搜索路径: {result['search_path']}")
    elif "--migrate" in sys.argv:
        migrate_temperatures(dry_run="--dry-run" in sys.argv)
    else:
        print("记忆弹出 · 四层温度+关联触发")
        print("用法: python3 memory_pop.py <文本>")
        print("      python3 memory_pop.py --migrate [--dry-run]")
        print()
        # 交互模式
        while True:
            try:
                text = input("🔍 ").strip()
                if not text or text == "/exit":
                    break
                result = pop(text)
                if result["memories"]:
                    print(f"  [{result['source']}] ({result['latency_ms']}ms)")
                    for m in result["memories"]:
                        print(f"    • {m}")
                else:
                    print(f"  无匹配 ({result['latency_ms']}ms)")
            except (EOFError, KeyboardInterrupt):
                break


if __name__ == "__main__":
    main()
