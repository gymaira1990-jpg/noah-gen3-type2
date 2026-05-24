#!/usr/bin/env python3
"""
Phase 1-2: 礼物模块知识吸收
导入礼物吸收分析报告 + 吸收产物到 noah_prime knowledge_entries.

来源:
  ~/noah-档案馆/礼物/        — 吸收分析报告 + 原件
  ~/noah-档案馆/参考/        — 吸收产物（手册/模板）
  ~/noah-档案馆/系统日志/    — 吸收产物（改进日志）
  ~/noah-档案馆/工程戒律.md  — SCALE-OS吸收产物
  ~/noah-档案馆/TFC层级与门控概念-模拟参考.md — SCALE-OS模拟参考
"""

import os, sys, re, time, hashlib
from datetime import datetime
import psycopg2
import requests

OLLAMA_URL = "http://localhost:11435/api/embed"
EMBED_MODEL = "qwen3-embedding:0.6b"
DST_DSN = "dbname=noah_prime host=/var/run/postgresql"
BATCH_SIZE = 15
MAX_CHUNK_SIZE = 6000

ARCHIVE_ROOT = os.path.expanduser("~/noah-档案馆")
GIFT_DIR = os.path.join(ARCHIVE_ROOT, "礼物")
REF_DIR = os.path.join(ARCHIVE_ROOT, "参考")
LOG_DIR = os.path.join(ARCHIVE_ROOT, "系统日志")
ROOT_FILES = [
    os.path.join(ARCHIVE_ROOT, "工程戒律.md"),
    os.path.join(ARCHIVE_ROOT, "TFC层级与门控概念-模拟参考.md"),
]

stats = {"files": 0, "chunks": 0, "imported": 0, "skipped": 0, "errors": 0}


def get_embedding(text):
    resp = requests.post(OLLAMA_URL, json={
        "model": EMBED_MODEL,
        "input": text[:8192],
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def get_existing_hashes(dst):
    cur = dst.cursor()
    cur.execute("SELECT md5(content || COALESCE(source,'')) FROM knowledge_entries")
    return set(r[0] for r in cur.fetchall())


def chunk_content(content, max_size=MAX_CHUNK_SIZE):
    if len(content) <= max_size:
        return [content]
    chunks = []
    parts = re.split(r'^(?=## )', content, flags=re.MULTILINE)
    current = ""
    for part in parts:
        if not part.strip():
            continue
        if len(current) + len(part) > max_size and current:
            chunks.append(current.strip())
            current = part
        else:
            if current:
                current += "\n\n" + part
            else:
                current = part
    if current.strip():
        chunks.append(current.strip())
    return chunks


def collect_files():
    """收集所有待导入文件"""
    files = []

    # 1. 礼物吸收分析报告
    if os.path.isdir(GIFT_DIR):
        for fn in sorted(os.listdir(GIFT_DIR)):
            fpath = os.path.join(GIFT_DIR, fn)
            if os.path.isfile(fpath) and fpath.endswith(".md") and ("吸收" in fn or "分析" in fn or "礼物" in fn):
                files.append((fpath, "gift", f"gift:{fn.replace('.md','')}"))
            elif os.path.isfile(fpath) and fpath.endswith(".md") and fn.endswith(".md"):
                # 其他根目录礼物.md文件（如 SCALE-OS-礼物分析报告.md 已经被捕获）
                files.append((fpath, "gift", f"gift:{fn.replace('.md','')}"))

    # 2. 参考
    if os.path.isdir(REF_DIR):
        for fn in sorted(os.listdir(REF_DIR)):
            fpath = os.path.join(REF_DIR, fn)
            if os.path.isfile(fpath) and fpath.endswith(".md"):
                files.append((fpath, "reference", f"reference:{fn.replace('.md','')}"))

    # 3. 系统日志
    if os.path.isdir(LOG_DIR):
        for fn in sorted(os.listdir(LOG_DIR)):
            fpath = os.path.join(LOG_DIR, fn)
            if os.path.isfile(fpath) and fpath.endswith(".md"):
                files.append((fpath, "system-log", f"system-log:{fn.replace('.md','')}"))

    # 4. 根目录吸收产物
    for fpath in ROOT_FILES:
        if os.path.isfile(fpath):
            fn = os.path.basename(fpath)
            files.append((fpath, "gift", f"gift:{fn.replace('.md','')}"))

    # 去重
    seen = set()
    deduped = []
    for fpath, cat, src in files:
        if src not in seen:
            seen.add(src)
            deduped.append((fpath, cat, src))
    return deduped


def main():
    print("╔══════════════════════════════════════╗")
    print("║   礼物模块知识吸收 · Phase 1-2      ║")
    print("╚══════════════════════════════════════╝")

    force = "--force" in sys.argv

    dst = psycopg2.connect(DST_DSN)
    existing_hashes = get_existing_hashes(dst)
    print(f"  📦 目标库已有 {len(existing_hashes)} 条目哈希")

    files = collect_files()
    stats["files"] = len(files)
    print(f"  📖 收集 {len(files)} 文件")

    all_chunks = []
    for fpath, category, source in files:
        fn = os.path.basename(fpath)
        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        title = fn.replace(".md", "")
        chunks = chunk_content(content)
        for i, chunk_text in enumerate(chunks):
            seq = i if len(chunks) > 1 else 0
            chunk_source = source if seq == 0 else f"{source}#{seq}"
            chunk_title = title if seq == 0 else f"{title} (part {seq})"
            digest = hashlib.md5((chunk_text + chunk_source).encode()).hexdigest()
            all_chunks.append({
                "title": chunk_title,
                "content": chunk_text,
                "source": chunk_source,
                "category": category,
                "seq": seq,
                "digest": digest,
                "tags": [category, title.split('-')[0] if '-' in title else title],
            })

    stats["chunks"] = len(all_chunks)
    print(f"     → {len(all_chunks)} 块 (最大 {MAX_CHUNK_SIZE}B/块)\n")

    batch = []
    t0 = time.time()

    for chunk in all_chunks:
        if not force and chunk["digest"] in existing_hashes:
            stats["skipped"] += 1
            continue

        try:
            embedding = get_embedding(chunk["content"])
            batch.append({
                "title": chunk["title"],
                "content": chunk["content"],
                "embedding": str(embedding),
                "category": chunk["category"],
                "tags": chunk["tags"],
                "freq": 0,
                "source": chunk["source"],
                "created_at": datetime.now(),
            })

            if len(batch) >= BATCH_SIZE:
                flush(dst, batch, force)
                stats["imported"] += len(batch)
                batch = []
                print(f"    → {stats['imported']}/{stats['chunks']} 块已写入...", end="\r")

        except Exception as e:
            stats["errors"] += 1
            print(f"\n  ❌ {chunk['source']} → {e}")

    if batch:
        flush(dst, batch, force)
        stats["imported"] += len(batch)

    stats["elapsed"] = time.time() - t0

    print(f"\n\n────────────────────────────────────────────────────")
    print(f"📊 礼物吸收报告")
    print(f"  文件:     {stats['files']}")
    print(f"  总块数:   {stats['chunks']}")
    print(f"  已导入:   {stats['imported']}")
    print(f"  跳过:     {stats['skipped']}")
    print(f"  错误:     {stats['errors']}")
    print(f"  耗时:     {stats['elapsed']:.1f}秒")
    print(f"────────────────────────────────────────────────────")

    dst.close()


def flush(dst, batch, force):
    cur = dst.cursor()
    for item in batch:
        try:
            if force:
                cur.execute("DELETE FROM knowledge_entries WHERE source = %s", (item["source"],))
            cur.execute(
                """INSERT INTO knowledge_entries
                   (title, content, embedding, category, tags, freq, source, created_at)
                   VALUES (%(title)s, %(content)s, %(embedding)s::vector,
                           %(category)s, ARRAY[%(tags)s]::text[], %(freq)s,
                           %(source)s, %(created_at)s)
                   ON CONFLICT DO NOTHING""",
                {**item, "tags": item["tags"]}
            )
        except Exception as e:
            print(f"\n  ⚠ DB写入错误: {item['source']} → {e}")
    dst.commit()


if __name__ == "__main__":
    main()
