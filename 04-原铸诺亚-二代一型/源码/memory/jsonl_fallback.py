#!/usr/bin/env python3
"""jsonl原始对话回查 · memory/jsonl_fallback.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 双轨记忆第二轨
当PG向量检索失败时，回退到原始聊天记录(jsonl)
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

PRIME_ROOT = Path(__file__).parent.parent


def search_chat_logs(query: str, days_back: int = 7, top_k: int = 5) -> list:
    """回查按日期分割的jsonl对话文件——向量检索失败时的兜底"""
    results = []
    chat_dir = PRIME_ROOT / "logs" / "chat"
    if not chat_dir.exists():
        return results

    for offset in range(days_back):
        date_str = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        logfile = chat_dir / f"{date_str}.jsonl"
        if not logfile.exists():
            continue

        try:
            with open(logfile, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    user_text = entry.get("user", "")
                    noah_text = entry.get("noah", "")

                    # 模糊关键词匹配
                    q = query.lower()
                    if q in user_text.lower() or q in noah_text.lower():
                        results.append({
                            "id": entry.get("ticket_id", f"jsonl_{date_str}"),
                            "content": f"[用户] {user_text[:200]} | [诺亚] {noah_text[:200]}",
                            "category": "dialogue",
                            "tags": ["jsonl_fallback"],
                            "similarity": 0.0,
                            "source": f"jsonl://{date_str}",
                        })
                if len(results) >= top_k:
                    break
        except Exception:
            continue

    return results[:top_k]


# ─── 测试 ───
if __name__ == "__main__":
    results = search_chat_logs("备份", days_back=7, top_k=3)
    print(f"jsonl回查 '备份': {len(results)}条")
    for r in results:
        print(f"  [{r['source']}] {r['content'][:80]}")
