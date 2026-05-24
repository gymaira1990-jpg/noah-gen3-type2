#!/usr/bin/env python3
"""
Phase 0-1: PG管道同步
noah_local → noah_prime 全量迁移
gcat 用户直连两库，psycopg2 原生处理 schema 差异

Schema差异:
  exact_info:  noah_local tags=text[] → noah_prime tags=text
  knowledge_entries: noah_local(13列) → noah_prime(9列)

用法:
  python3 <noah_home>/scripts/sync_from_noah_local.py [--force]
"""
import sys, time, hashlib, json
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import register_adapter, AsIs

# ─── 配置 ──────────────────────────────────────────
SRC_DSN = "dbname=noah_local host=/var/run/postgresql"
DST_DSN = "dbname=noah_prime host=/var/run/postgresql"
BATCH_SIZE = 200

stats = {
    "ke_migrated": 0, "ke_skipped": 0, "ke_errors": 0,
    "ei_migrated": 0, "ei_skipped": 0, "ei_errors": 0,
    "started": None, "ended": None,
}

def get_existing_digests(dst):
    """获取目标库已有 knowledge_entries 的 content+source 哈希"""
    cur = dst.cursor()
    cur.execute("SELECT md5(content || COALESCE(source,'')) FROM knowledge_entries")
    return set(r[0] for r in cur.fetchall())

def get_existing_keys(dst, table, key_col="key"):
    """获取目标库 exact_info 已有 keys"""
    cur = dst.cursor()
    cur.execute(f"SELECT {key_col} FROM {table}")
    return set(r[0] for r in cur.fetchall())

def migrate_knowledge_entries(src, dst, force=False):
    """迁移 knowledge_entries"""
    cur_src = src.cursor(cursor_factory=RealDictCursor)
    cur_dst = dst.cursor()

    if force:
        cur_dst.execute("TRUNCATE knowledge_entries RESTART IDENTITY CASCADE")
        dst.commit()
        print("  [强制模式] 已清空目标表")

    cur_src.execute("SELECT count(*) FROM knowledge_entries")
    total = cur_src.fetchone()["count"]
    print(f"  📖 源库: {total} 条")

    existing = get_existing_digests(dst)
    print(f"  📦 目标库已有: {len(existing)} 条")

    cur_src.execute("""
        SELECT id, title, content, embedding, category, tags, source, created_at
        FROM knowledge_entries
        ORDER BY id
    """)

    batch = []
    migrated = 0
    skipped = 0

    def flush():
        nonlocal batch
        if not batch:
            return
        cur_dst.executemany(
            """INSERT INTO knowledge_entries
               (title, content, embedding, category, tags, freq, source, created_at)
               VALUES (%(title)s, %(content)s, %(embedding)s, %(category)s,
                       %(tags)s, 5, %(source)s, %(created_at)s)
               ON CONFLICT DO NOTHING""",
            batch
        )
        batch = []

    for row in cur_src:
        # 使用和 SQL md5(content || COALESCE(source,'')) 一致的计算方式
        dedup = hashlib.md5((row["content"] + (row["source"] or "")).encode()).hexdigest()
        if dedup in existing:
            skipped += 1
            continue

        # tags: text[] → text[] (原生保持)
        tags = row["tags"] if isinstance(row["tags"], (list, tuple)) else []

        batch.append({
            "title": row["title"] or "",
            "content": row["content"],
            "embedding": row["embedding"],   # vector type preserved by psycopg2
            "category": row["category"] or "general",
            "tags": tags,
            "source": row["source"] or "",
            "created_at": row["created_at"] or datetime.now(),
        })
        migrated += 1

        if len(batch) >= BATCH_SIZE:
            flush()
            dst.commit()
            print(f"    → {migrated} 条已写入...", end="\r")

    flush()
    dst.commit()

    stats["ke_migrated"] = migrated
    stats["ke_skipped"] = skipped
    print(f"\n  ✅ knowledge_entries: {migrated} 迁移 | {skipped} 跳过")

def migrate_exact_info(src, dst, force=False):
    """迁移 exact_info — 处理 tags text[]→text 转换"""
    cur_src = src.cursor(cursor_factory=RealDictCursor)
    cur_dst = dst.cursor()

    if force:
        cur_dst.execute("TRUNCATE exact_info CASCADE")
        dst.commit()
        print("  [强制模式] 已清空目标表")

    cur_src.execute("SELECT count(*) FROM exact_info")
    total = cur_src.fetchone()["count"]
    print(f"  📖 源库: {total} 条")

    existing = get_existing_keys(dst, "exact_info", "key")
    print(f"  📦 目标库已有: {len(existing)} 条")

    cur_src.execute("""
        SELECT key, value, category, tags, updated_at
        FROM exact_info
        ORDER BY key
    """)

    batch = []
    migrated = 0
    skipped = 0

    def flush():
        nonlocal batch
        if not batch:
            return
        cur_dst.executemany(
            """INSERT INTO exact_info (key, value, category, tags, created_at, updated_at)
               VALUES (%(key)s, %(value)s, %(category)s, %(tags)s,
                       NOW(), %(updated_at)s)
               ON CONFLICT (key) DO UPDATE SET
                   value = EXCLUDED.value,
                   category = EXCLUDED.category,
                   tags = EXCLUDED.tags,
                   updated_at = EXCLUDED.updated_at""",
            batch
        )
        batch = []

    for row in cur_src:
        if row["key"] in existing:
            skipped += 1
            continue

        # 类型转换：text[] → text (空格拼接)
        tags_raw = row["tags"]
        if isinstance(tags_raw, (list, tuple)):
            tags_str = " ".join(t.strip() for t in tags_raw if t.strip())
        elif tags_raw is None:
            tags_str = ""
        else:
            tags_str = str(tags_raw)

        batch.append({
            "key": row["key"],
            "value": row["value"] or "",
            "category": row["category"] or "soul",
            "tags": tags_str,
            "updated_at": row["updated_at"] or datetime.now(),
        })
        migrated += 1

        if len(batch) >= BATCH_SIZE:
            flush()
            dst.commit()
            print(f"    → {migrated} 条已写入...", end="\r")

    flush()
    dst.commit()

    stats["ei_migrated"] = migrated
    stats["ei_skipped"] = skipped
    print(f"\n  ✅ exact_info: {migrated} 迁移 | {skipped} 跳过")

def ensure_indexes(dst):
    """确保 HNSW 向量索引存在（autocommit 模式）"""
    cur = dst.cursor()
    cur.execute("""
        SELECT 1 FROM pg_indexes
        WHERE tablename='knowledge_entries' AND indexname='idx_knowledge_hnsw'
    """)
    if not cur.fetchone():
        print("  🔧 创建 HNSW 向量索引...")
        dst.commit()  # commit any pending transaction
        dst.set_session(autocommit=True)
        cur.execute("""
            CREATE INDEX CONCURRENTLY idx_knowledge_hnsw
            ON knowledge_entries USING hnsw (embedding vector_cosine_ops)
            WITH (m=16, ef_construction=200)
        """)
        print("  ✅ HNSW 索引创建完成")
    else:
        print("  ✅ HNSW 索引已存在")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="noah_local → noah_prime 数据同步")
    parser.add_argument("--force", action="store_true", help="清空目标表再写入")
    args = parser.parse_args()

    stats["started"] = time.time()

    print("╔══════════════════════════════════════╗")
    print("║   PG管道同步 · 诺亚原铸注入           ║")
    print("║   noah_local → noah_prime            ║")
    print("╚══════════════════════════════════════╝")
    print(f"  模式: {'强制覆盖 ⚠️' if args.force else '增量追加 🟢'}")

    src = psycopg2.connect(SRC_DSN)
    dst = psycopg2.connect(DST_DSN)

    try:
        migrate_knowledge_entries(src, dst, args.force)
        migrate_exact_info(src, dst, args.force)
        ensure_indexes(dst)

        stats["ended"] = time.time()
        elapsed = stats["ended"] - stats["started"]

        print("\n" + "─" * 52)
        print("📊 同步报告")
        print(f"  knowledge_entries: {stats['ke_migrated']} 迁移 | {stats['ke_skipped']} 跳过 | {stats['ke_errors']} 错误")
        print(f"  exact_info:        {stats['ei_migrated']} 迁移 | {stats['ei_skipped']} 跳过 | {stats['ei_errors']} 错误")
        print(f"  总耗时: {elapsed:.1f}秒")
        print("─" * 52)
    except Exception as e:
        dst.rollback()
        print(f"\n❌ 同步失败: {e}", file=sys.stderr)
        raise
    finally:
        src.close()
        dst.close()

if __name__ == "__main__":
    main()
