# ← 移植自 noah-embryo · 已脱敏 · NOAH-PRIME
#!/usr/bin/env python3
"""
小诺亚·降噪脑 — 上下文去噪 + 记忆压缩 + 向量化导入 L2

三件事:
  1. 去噪: 过滤重复/填充/低价值信息
  2. 压缩: 提取摘要+关键点+决策+实体
  3. 向量化导入 L2: 切片 → qwen3-embedding → 写入 PostgreSQL pgvector

架构位置:
  L1(lightweight.db) → 降噪脑(去噪→压缩→向量化) → L2(PostgreSQL pgvector)

用法:
  from brain_denoising import DenoisingBrain
  denoiser = DenoisingBrain()
  # 压缩
  result = denoiser.compress(文本)
  # 导入L2
  result = denoiser.ingest_to_l2(key, text)  # 单条
  denoiser.ingest_pending(limit=10)           # 批量
"""

import json, re, hashlib, subprocess, sqlite3
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from pg_conn import connect


# ─── 路径 ──────────────────────────────────────────

LIGHT_DB = Path.home() / "noah-prime" / "data" / "lightweight.db"
EMBED_MODEL = "qwen3-embedding:0.6b"
OLLAMA_URL = "http://localhost:11435"
CLEAN_ENV = {k: v for k, v in __import__('os').environ.items() if not k.lower().endswith("_proxy")}


# ─── 压缩等级 ──────────────────────────────────────────

class CompressLevel:
    LIGHT = "轻"    # 去噪，保留大部分
    MEDIUM = "中"   # 压缩50-70%
    STRONG = "强"   # 仅摘要，压缩80-90%


# ─── 去噪规则 ──────────────────────────────────────────

NOISE_PATTERNS = [
    (r'(?:好的|明白了|收到|了解|ok|明白)\s*(?:好的|明白了|收到|了解|ok|明白)', '重复确认'),
    (r'(?:那个|这个|然后|就是|反正|其实|那个那个)', '填充词'),
    (r'[!！]{3,}', '重复标点'),
    (r'[?？]{3,}', '重复标点'),
    (r'[~～]{3,}', '重复标点'),
    (r'(?:谢谢|感谢|谢谢谢谢|多谢|感恩)\s*(?:谢谢|感谢|谢谢谢谢|多谢|感恩)', '重复礼貌'),
    (r'\[system\]|\[info\]|\[debug\]|\[log\]', '系统标记'),
]

HIGH_VALUE_PATTERNS = [
    r'(?:决定|确认|同意|批准|采用|选择|就按|就这么|改|修|创|删)',
    r'(?:地址|IP|端口|密码|密钥|token|key|id|账号|用户)',
    r'(?:架构|设计|方案|架构图|流程图|协议|接口|API)',
    r'(?:bug|错误|问题|故障|异常|崩溃|超时|失败|error|fail|timeout)',
]


@dataclass
class CompressedMemory:
    original_length: int
    compressed_length: int
    level: str
    summary: str
    key_points: list
    entities: list
    decisions: list
    action_items: list
    emotional_tone: str
    vectorized: bool = False
    chunks: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def compression_ratio(self) -> float:
        return 1 - (self.compressed_length / max(self.original_length, 1))


class DenoisingBrain:
    """降噪脑 — 去噪 + 压缩 + 向量化导入 L2"""

    def __init__(self):
        self.light_db = LIGHT_DB

    # ═══════════════════════════════════════════
    # 去噪 + 压缩（原有）
    # ═══════════════════════════════════════════

    def denoise(self, text: str) -> str:
        cleaned = text
        for pattern, _ in NOISE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned)
        cleaned = re.sub(r'\n{4,}', '\n\n\n', cleaned)
        cleaned = re.sub(r' {3,}', '  ', cleaned)
        return cleaned.strip()

    def extract_key_points(self, text: str, max_points: int = 5) -> list:
        points = []
        for line in text.split('\n'):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            if re.match(r'^[#*\-•·>\d+.]', line):
                points.append(line[:100])
                continue
            for pattern in HIGH_VALUE_PATTERNS:
                if re.search(pattern, line):
                    points.append(line[:100])
                    break
        return points[:max_points]

    def extract_entities(self, text: str) -> list:
        entities = set()
        for match in re.finditer(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text):
            entities.add(match.group())
        for match in re.finditer(r'\b(?:PROJ-|TFC-|WO-|EVO-|NC-|AC-|IG-)\d*\b', text):
            entities.add(match.group())
        for match in re.finditer(r'\bgithub\.com/[\w-]+/[\w-]+\b', text):
            entities.add(match.group())
        return list(entities)

    def extract_decisions(self, text: str) -> list:
        decisions = []
        markers = ['决定', '确认', '同意', '就按', '采用', '选', '结论', '拍板', '定']
        for line in text.split('\n'):
            for m in markers:
                if m in line:
                    decisions.append(line.strip()[:120])
                    break
        return decisions[:5]

    def extract_action_items(self, text: str) -> list:
        items = []
        for line in text.split('\n'):
            if re.match(r'^\s*[-*]\s*\[ \]', line):
                items.append(line.strip()[5:100])
            elif re.match(r'^\s*(?:待办|todo|TODO|下一步|接下来)', line, re.I):
                items.append(line.strip()[:100])
        return items[:5]

    def detect_tone(self, text: str) -> str:
        pos = ['好', '棒', '开心', '满意', '赞', 'nice', 'great']
        neg = ['烦', '累', '糟', '生气', '失望', 'bad', 'error']
        urg = ['急', '快', '立刻', '马上', '紧急', 'urgent', 'critical']
        tl = text.lower()
        pc = sum(1 for w in pos if w in tl)
        nc = sum(1 for w in neg if w in tl)
        uc = sum(1 for w in urg if w in tl)
        if uc >= 2: return "紧急"
        if pc > nc: return "积极"
        if nc > pc: return "消极"
        return "中性"

    def compress(self, text: str, level: str = "中") -> CompressedMemory:
        original_length = len(text)
        cleaned = self.denoise(text)
        key_points = self.extract_key_points(cleaned, 10 if level == "轻" else 5 if level == "中" else 3)

        if level == "轻":
            compressed = cleaned
        elif level == "强":
            decisions = self.extract_decisions(cleaned)
            compressed = " | ".join(key_points + decisions)
        else:
            lines = cleaned.split('\n')
            compressed = '\n'.join(lines[:max(3, len(lines) // 3)])

        summary_lines = [l for l in cleaned.split('\n') if l.strip() and len(l) > 15]
        summary = summary_lines[0][:200] if summary_lines else cleaned[:200]

        return CompressedMemory(
            original_length=original_length,
            compressed_length=len(compressed),
            level=level,
            summary=summary,
            key_points=key_points,
            entities=self.extract_entities(cleaned),
            decisions=self.extract_decisions(cleaned),
            action_items=self.extract_action_items(cleaned),
            emotional_tone=self.detect_tone(cleaned),
        )

    # ═══════════════════════════════════════════
    # 向量化导入 L2（新增 — 降噪脑的核心职责）
    # ═══════════════════════════════════════════

    def _get_embedding(self, text: str) -> list:
        """Ollama qwen3-embedding, 1024维"""
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "30",
                 "-d", json.dumps({"model": EMBED_MODEL, "prompt": text[:800]}),
                 f"{OLLAMA_URL}/api/embeddings"],
                capture_output=True, text=True, timeout=35, env=CLEAN_ENV,
            )
            if r.returncode == 0 and r.stdout.strip():
                emb = json.loads(r.stdout).get("embedding", [])
                if emb and len(emb) == 1024:
                    return emb
        except:
            pass
        return [0.0] * 1024

    def _chunk_text(self, text: str, title: str, max_chars=800) -> list:
        """语义切片"""
        if len(text) <= max_chars:
            return [{"title": title, "content": text[:800]}]
        paras = re.split(r'\n\n+', text)
        chunks, cur = [], ""
        for p in paras:
            p = p.strip()
            if not p:
                continue
            if len(cur) + len(p) < max_chars:
                cur += "\n\n" + p if cur else p
            else:
                if cur:
                    chunks.append({"title": title, "content": cur[:800]})
                cur = p
        if cur:
            chunks.append({"title": title, "content": cur[:800]})
        return chunks

    def ingest_to_l2(self, l1_key: str, text: str, title_hint: str = "") -> dict:
        """
        单条: 去噪→切片→嵌入→写入本地 PG knowledge_entries
        返回: {chunks, ok, error}
        """
        # 跳过灵魂规则（免压缩区）
        if l1_key.startswith("soul:") or "soul,protected" in text[:100]:
            return {"chunks": 0, "ok": True, "skip": "soul_protected"}

        # 1. 去噪
        cleaned = self.denoise(text)

        # 2. 取标题
        title = title_hint or l1_key.replace("doc-知识:", "").replace(":text", "")[:60]

        # 3. 切片
        chunks = self._chunk_text(cleaned, title)

        # 4. 嵌入 + 写入 PG
        with connect() as conn:
            cur = conn.cursor()
            inserted = 0
            for i, chunk in enumerate(chunks):
                vec = self._get_embedding(chunk["content"])
                try:
                    cur.execute(
                        "INSERT INTO knowledge_entries (title, content, source, category, embedding) "
                        "VALUES (%s, %s, %s, %s, %s::vector) "
                        "ON CONFLICT DO NOTHING",
                        (chunk["title"][:100], chunk["content"], f"L1:{l1_key}", "knowledge", vec)
                    )
                    inserted += 1
                except Exception as e:
                    print(f"  ⚠ PG写入失败 chunk[{i}]: {e}")
            conn.commit()
            cur.close()

        return {"chunks": inserted, "ok": True}

    def ingest_pending(self, limit: int = 5) -> dict:
        """
        批量: 扫描 L1 待向量化条目 → 逐条 ingest_to_l2 → 标记完成
        """
        conn = sqlite3.connect(str(self.light_db))
        cur = conn.execute(
            "SELECT key, value, tags FROM lightweight_memory "
            "WHERE category = '知识' AND tags LIKE '%pending_vectorize%' "
            "AND tags NOT LIKE '%vectorized%' LIMIT ?", (limit,)
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return {"status": "empty", "message": "无待导入条目"}

        results = []
        total_chunks = 0
        for key, val, tags in rows:
            try:
                r = self.ingest_to_l2(key, val)
                total_chunks += r["chunks"]

                # 标记 completed
                conn2 = sqlite3.connect(str(self.light_db))
                new_tags = tags.replace("pending_vectorize", "vectorized")
                conn2.execute(
                    "UPDATE lightweight_memory SET tags = ?, updated_at = datetime('now') WHERE key = ?",
                    (new_tags, key)
                )
                conn2.commit()
                conn2.close()

                results.append({"key": key, "chunks": r["chunks"], "status": "ok"})
            except Exception as e:
                results.append({"key": key, "error": str(e), "status": "error"})

        return {
            "status": "ok",
            "processed": len(results),
            "total_chunks": total_chunks,
            "results": results,
        }


# ─── 测试入口 ──────────────────────────────────────────

if __name__ == "__main__":
    d = DenoisingBrain()

    print("=" * 56)
    print("  🧹 小诺亚·降噪脑 测试")
    print("=" * 56)

    test_text = """好的好的好的，明白了明白了。
那个那个，我觉得可以用三个方案来解决：
1. 方案A: 直接迁移数据
2. 方案B: 增量同步
3. 方案C: 重新建库
决定采用方案B，风险最小成本适中可回滚。
待办: 写迁移脚本，测试同步，用户确认后执行。"""

    # 压缩测试
    for level in ["轻", "中", "强"]:
        r = d.compress(test_text, level)
        print(f"\n[{level}] {r.compression_ratio:.0%} | 情绪:{r.emotional_tone} | 待办:{r.action_items}")

    # 向量化导入测试（只预览，不实际连接）
    print("\n── 向量化导入 L2 ──")
    pending = d.ingest_pending(limit=0)  # limit=0 只预览
    print(f"  待导入: {pending}")
    print(f"  真正执行: python3 -c 'from brain_denoising import DenoisingBrain; d=DenoisingBrain(); d.ingest_pending(5)'")
