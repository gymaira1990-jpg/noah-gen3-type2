#!/usr/bin/env python3
"""
Phase 1-3: Hermes 技能知识注入
读取 ~/.hermes/skills/ 下所有 SKILL.md，分块嵌入后写入 noah_prime knowledge_entries.

分块策略:
  - ≤8KB: 单条目
  - >8KB: 按 ## 标题分块，每块 ≤6KB（对齐检索粒度）
"""

import os, sys, re, time, json, hashlib
from datetime import datetime
import psycopg2
import requests

# ─── 配置 ──────────────────────────────────────────
OLLAMA_URL = "http://localhost:11435/api/embed"
EMBED_MODEL = "qwen3-embedding:0.6b"
DST_DSN = "dbname=noah_prime host=/var/run/postgresql"
SKILL_ROOT = os.path.expanduser("~/.hermes/skills/")
BATCH_SIZE = 15
MAX_CHUNK_SIZE = 6000  # 每块最大字节数

stats = {
    "skills_found": 0, "chunks_total": 0,
    "imported": 0, "skipped": 0, "errors": 0,
    "elapsed": 0,
}


def get_embedding(text):
    resp = requests.post(OLLAMA_URL, json={
        "model": EMBED_MODEL,
        "input": text[:8192],
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def get_existing_hashes(dst):
    """获取目标库已有条目的 content 哈希集合"""
    cur = dst.cursor()
    cur.execute("SELECT md5(content || COALESCE(source,'')) FROM knowledge_entries")
    return set(r[0] for r in cur.fetchall())


def chunk_skill(name, content, max_size=MAX_CHUNK_SIZE):
    """
    按 ## 标题分块，每块 ≤ max_size。
    返回 [(title, content, seq_number), ...]
    """
    if len(content) <= max_size:
        return [(name, content, 0)]

    chunks = []
    # 按 ## 标题分割（保留标题行）
    parts = re.split(r'^(?=## )', content, flags=re.MULTILINE)
    
    current_chunk = ""
    current_title = name
    seq = 0

    for part in parts:
        if not part.strip():
            continue

        # 提取此部分的标题
        title_match = re.match(r'^## (.+)', part)
        part_title = title_match.group(1).strip() if title_match else name

        # 如果当前块+新部分 > max_size，先存当前块
        if len(current_chunk) + len(part) > max_size and current_chunk:
            chunks.append((f"{name} → {current_title}", current_chunk.strip(), seq))
            seq += 1
            current_chunk = part
            current_title = part_title
        else:
            if current_chunk:
                current_chunk += "\n\n" + part
            else:
                current_chunk = part
            current_title = part_title

    if current_chunk.strip():
        chunks.append((f"{name} → {current_title}", current_chunk.strip(), seq))

    return chunks


def walk_skills():
    """扫描所有 SKILL.md"""
    skills = []
    for dirpath, dirnames, fnames in os.walk(SKILL_ROOT):
        for fn in fnames:
            if fn == "SKILL.md":
                rel = os.path.relpath(dirpath, SKILL_ROOT)
                parts = rel.split('/')
                category = parts[0] if len(parts) >= 2 else parts[0]
                name = parts[1] if len(parts) >= 2 else parts[0]
                with open(os.path.join(dirpath, fn), "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                skills.append((name, category, content))
    skills.sort(key=lambda x: x[0])
    return skills


def main():
    print("╔══════════════════════════════════════╗")
    print("║   Hermes 技能知识注入 · Phase 1-3   ║")
    print("║   26 skills → noah_prime            ║")
    print("╚══════════════════════════════════════╝")

    force = "--force" in sys.argv

    dst = psycopg2.connect(DST_DSN)
    existing_hashes = get_existing_hashes(dst)
    print(f"  📦 目标库已有 {len(existing_hashes)} 条目哈希")

    skills = walk_skills()
    stats["skills_found"] = len(skills)

    # 预分块
    all_chunks = []
    for name, category, content in skills:
        chunks = chunk_skill(name, content)
        for title, chunk_content, seq in chunks:
            source = f"skill:{name}"
            if seq > 0:
                source = f"skill:{name}#{seq}"

            digest = hashlib.md5((chunk_content + source).encode()).hexdigest()
            all_chunks.append({
                "name": name,
                "category": category,
                "title": title,
                "content": chunk_content,
                "source": source,
                "seq": seq,
                "digest": digest,
            })

    stats["chunks_total"] = len(all_chunks)
    print(f"  📖 扫描 {len(skills)} 技能 → {len(all_chunks)} 块")
    print(f"  模式: {'强制覆盖' if force else '增量追加'} 🟢\n")

    # 嵌入+写入
    batch = []
    t0 = time.time()

    for chunk in all_chunks:
        # 去重
        if not force and chunk["digest"] in existing_hashes:
            stats["skipped"] += 1
            continue

        try:
            embedding = get_embedding(chunk["content"])

            # 生成 tags
            tags_raw = [chunk["name"], chunk["category"]]
            if chunk["seq"] > 0:
                tags_raw.append(f"part-{chunk['seq']}")

            batch.append({
                "title": chunk["title"],
                "content": chunk["content"],
                "embedding": str(embedding),
                "category": chunk["category"],
                "tags": tags_raw,
                "freq": 0,
                "source": chunk["source"],
                "created_at": datetime.now(),
            })

            if len(batch) >= BATCH_SIZE:
                flush(dst, batch, force)
                stats["imported"] += len(batch)
                batch = []
                print(f"    → {stats['imported']}/{stats['chunks_total']} 块已写入...", end="\r")

        except Exception as e:
            stats["errors"] += 1
            print(f"\n  ❌ {chunk['source']} → {e}")

    if batch:
        flush(dst, batch, force)
        stats["imported"] += len(batch)

    stats["elapsed"] = time.time() - t0

    print(f"\n\n────────────────────────────────────────────────────")
    print(f"📊 注入报告")
    print(f"  技能:      {stats['skills_found']}")
    print(f"  总块数:    {stats['chunks_total']}")
    print(f"  已导入:    {stats['imported']}")
    print(f"  跳过(已存在): {stats['skipped']}")
    print(f"  错误:      {stats['errors']}")
    print(f"  耗时:      {stats['elapsed']:.1f}秒")
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
