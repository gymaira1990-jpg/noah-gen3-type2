#!/usr/bin/env python3
"""
Phase 0-2: 档案馆导入管线
知识档案馆 + 项目档案馆 → noah_prime knowledge_entries
增量追加，幂等接入。

用法:
  python3 scripts/archive_import.py [--force]
  --force: 重新导入已存在的条目（覆盖）
"""

import os, sys, json, time, hashlib
from datetime import datetime
import psycopg2
import requests

# ─── 配置 ──────────────────────────────────────────
OLLAMA_URL = "http://localhost:11435/api/embed"
EMBED_MODEL = "qwen3-embedding:0.6b"
DST_DSN = "dbname=noah_prime host=/var/run/postgresql"
ARCHIVE_ROOT = os.path.expanduser("~/noah-档案馆/")
BATCH_SIZE = 20

# 目标目录（按导入顺序）
TARGET_DIRS = [
    "知识档案馆",
    "项目档案馆",
]

# 文件扩展名
EXTS = (".md", ".txt", ".json")


stats = {
    "imported": 0, "skipped": 0, "errors": 0,
    "bytes": 0, "elapsed": 0, "files_found": 0,
}


def get_embedding(text):
    """调用 qwen3-embedding 生成 1024 维向量"""
    resp = requests.post(OLLAMA_URL, json={
        "model": EMBED_MODEL,
        "input": text[:8192],  # 安全截断
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["embeddings"][0]


def get_existing_sources(dst):
    """获取目标库已有 source 路径集合"""
    cur = dst.cursor()
    cur.execute("SELECT source, created_at, md5(content || COALESCE(source,'')) FROM knowledge_entries WHERE source != ''")
    return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


def classify_category(rel_path):
    """根据路径自动分类"""
    if rel_path.startswith("知识档案馆/"):
        return "knowledge"
    if rel_path.startswith("项目档案馆/"):
        return "project"
    return "general"


def generate_title(rel_path):
    """从路径生成标题"""
    basename = os.path.splitext(os.path.basename(rel_path))[0]
    # 清理常见前缀
    title = basename.replace("-", " ").replace("_", " ").strip()
    return title[:200] if title else rel_path


def walk_files():
    """扫描档案馆，返回 (rel_path, abs_path, size, mtime) 列表"""
    files = []
    for target_dir in TARGET_DIRS:
        dpath = os.path.join(ARCHIVE_ROOT, target_dir)
        if not os.path.isdir(dpath):
            print(f"  ⚠ 目录不存在: {dpath}")
            continue
        for dirpath, dirnames, fnames in os.walk(dpath):
            for fn in sorted(fnames):
                if not fn.endswith(EXTS):
                    continue
                fpath = os.path.join(dirpath, fn)
                rel = os.path.relpath(fpath, ARCHIVE_ROOT)
                size = os.path.getsize(fpath)
                mtime = os.path.getmtime(fpath)
                files.append((rel, fpath, size, mtime))
    files.sort(key=lambda x: x[0])
    return files


def main():
    print("╔══════════════════════════════════════╗")
    print("║   档案馆导入管线 · 知识+项目        ║")
    print("║   noah-档案馆 → noah_prime          ║")
    print("╚══════════════════════════════════════╝")

    force = "--force" in sys.argv

    # 连接目标库
    dst = psycopg2.connect(DST_DSN)
    existing = get_existing_sources(dst)
    print(f"  📦 目标库已有 {len(existing)} 条来源记录")

    # 扫描文件
    files = walk_files()
    stats["files_found"] = len(files)
    print(f"  📖 扫描到 {len(files)} 个文本文件")
    print(f"  模式: {'强制覆盖' if force else '增量追加'} 🟢\n")

    # 逐文件处理
    batch = []
    t0 = time.time()

    for rel, fpath, size, mtime in files:
        rel_clean = rel.lstrip("/")
        stats["bytes"] += size

        # 跳过已存在（非强制模式）
        if not force and rel_clean in existing:
            stats["skipped"] += 1
            continue

        try:
            # 读取内容
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            if not content.strip():
                stats["skipped"] += 1
                continue

            # 生成嵌入
            embedding = get_embedding(content)

            # 计算哈希
            digest = hashlib.md5((content + (rel_clean or "")).encode()).hexdigest()

            # 避免重复（Python 侧去重）
            if not force and digest in {v[1] for v in existing.values()}:
                stats["skipped"] += 1
                continue

            category = classify_category(rel_clean)
            title = generate_title(rel_clean)
            now = datetime.now()

            batch.append({
                "title": title,
                "content": content,
                "embedding": str(embedding),  # pgvector 接受字符串数组格式
                "category": category,
                "tags": [],
                "freq": 0,
                "source": rel_clean,
                "created_at": now,
            })

            if len(batch) >= BATCH_SIZE:
                flush(dst, batch, force)
                stats["imported"] += len(batch)
                batch = []
                print(f"    → {stats['imported']} 条已写入...", end="\r")

        except Exception as e:
            stats["errors"] += 1
            print(f"\n  ❌ 错误: {rel_clean} → {e}")

    # 刷剩余批次
    if batch:
        flush(dst, batch, force)
        stats["imported"] += len(batch)

    stats["elapsed"] = time.time() - t0

    # 统计
    print(f"\n\n────────────────────────────────────────────────────")
    print(f"📊 导入报告")
    print(f"  扫描文件:  {stats['files_found']}")
    print(f"  已导入:    {stats['imported']}")
    print(f"  跳过(已存在): {stats['skipped']}")
    print(f"  错误:      {stats['errors']}")
    print(f"  总大小:    {stats['bytes']/1024:.1f}KB")
    print(f"  耗时:      {stats['elapsed']:.1f}秒")
    if stats["imported"] > 0:
        print(f"  速度:      {stats['bytes']/stats['elapsed']/1024:.1f}KB/秒")
    print(f"────────────────────────────────────────────────────")

    dst.close()


def flush(dst, batch, force):
    """批量写入 PG"""
    cur = dst.cursor()
    for item in batch:
        try:
            if force:
                # 强制模式：先删后插
                cur.execute(
                    "DELETE FROM knowledge_entries WHERE source = %s",
                    (item["source"],)
                )
            cur.execute(
                """INSERT INTO knowledge_entries
                   (title, content, embedding, category, tags, freq, source, created_at)
                   VALUES (%(title)s, %(content)s, %(embedding)s::vector,
                           %(category)s, %(tags)s, %(freq)s, %(source)s, %(created_at)s)
                   ON CONFLICT DO NOTHING""",
                item
            )
        except Exception as e:
            print(f"\n  ⚠ DB写入错误: {item['source']} → {e}")
    dst.commit()


if __name__ == "__main__":
    main()
