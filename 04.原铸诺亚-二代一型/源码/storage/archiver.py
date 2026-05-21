#!/usr/bin/env python3
"""四层存储引擎 · archiver.py — 胚胎版

精简自 noah-factory/soft-context/storage.py
移除: LanceDB依赖、广州同步、复杂注册表
保留: L1内存/L2 SQLite(lightweight-db)/L3 MD归档

用法:
  from archiver import store, search
  store("log", {"id": "chat-xxx", "summary": "..."})
  results = search("chat", limit=5)
"""

import json, os, subprocess, time
from pathlib import Path
from datetime import datetime

BASE = Path.home() / "noah-embryo"
LIGHT_DB = BASE / "storage" / "lightweight-db.py"
ARCHIVE_DIR = BASE / "data" / "archives"
RECENT_MEM = BASE / "storage" / "recent-memory.py"

# ─── L1: 近期记忆（内存+recent-memory） ───

def store_recent(text: str, intent: str = "chat"):
    """写入近期记忆"""
    try:
        subprocess.run(
            ["python3", str(RECENT_MEM), "put", text[:500], intent],
            capture_output=True, text=True, timeout=5,
        )
    except:
        pass

def load_recent(max_tokens: int = 1000) -> str:
    """读取近期记忆"""
    try:
        r = subprocess.run(
            ["python3", str(RECENT_MEM), "read", str(max_tokens)],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            lines = [l for l in r.stdout.split("\n") if l.strip() and not l.startswith("═══")]
            return "\n".join(lines[:10]) if lines else ""
    except:
        pass
    return ""


# ─── L2: 持久化存储（lightweight-db SQLite） ───

def store_persistent(key: str, value: str, category: str = "selflog"):
    """写入持久化存储"""
    try:
        subprocess.run(
            ["python3", str(LIGHT_DB), "set", key, value[:500], category],
            capture_output=True, text=True, timeout=5,
        )
    except:
        pass

def search_persistent(query: str, limit: int = 5) -> list:
    """关键词检索持久化存储"""
    try:
        r = subprocess.run(
            ["python3", str(LIGHT_DB), "search", query],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and l.startswith("  •")]
            return lines[:limit]
    except:
        pass
    return []


# ─── L3: MD归档 ───

def store_archive(data: dict, subdir: str = "chat"):
    """写入MD归档文件"""
    ts = int(time.time())
    date_str = datetime.now().strftime("%Y-%m-%d")
    target_dir = ARCHIVE_DIR / subdir / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    
    filepath = target_dir / f"{data.get('id', f'entry-{ts}')}.md"
    content = [f"# {data.get('title', '诺亚胚胎记录')}",
               f"> 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
               f"> ID: {data.get('id', f'entry-{ts}')}",
               "",
               data.get("content", data.get("summary", "")),
               ""]
    
    try:
        filepath.write_text("\n".join(content), encoding="utf-8")
        return str(filepath)
    except:
        return None


# ─── 统一接口 ───

def store(record_type: str, data: dict):
    """统一存储入口：L1+L2+L3"""
    text = data.get("summary", data.get("content", ""))
    intent = data.get("intent", "chat")
    
    # L1: 近期记忆
    store_recent(text, intent)
    
    # L2: 持久化存储
    key = data.get("id", f"{record_type}-{int(time.time())}")
    store_persistent(key, text, record_type)
    
    # L3: MD归档（重要记录）
    if record_type in ("log", "milestone", "tfc"):
        store_archive(data, record_type)

def search(query: str, limit: int = 5) -> list:
    """统一检索入口"""
    return search_persistent(query, limit)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "store":
        store(sys.argv[2], {"id": f"manual-{int(time.time())}", "summary": sys.argv[3] if len(sys.argv) > 3 else ""})
        print("✅ stored")
    elif len(sys.argv) > 2 and sys.argv[1] == "search":
        results = search(sys.argv[2])
        for r in results:
            print(r)
    else:
        print("用法: python3 archiver.py store|search <args>")
