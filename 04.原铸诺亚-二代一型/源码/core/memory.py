#!/usr/bin/env python3
"""记忆模块 · memory.py

原铸诺亚的对话记忆存储。
本地文件存储（无外部依赖），用于秘书层的上下文管理。
"""

import json, os, time
from pathlib import Path

_DIALOGUE_DIR = Path.home() / "noah-prime" / "data" / "dialogues"
_DIALOGUE_DIR.mkdir(parents=True, exist_ok=True)


def save_dialogue(user_input: str, response: str, intent: str = "unknown") -> bool:
    """保存对话记录"""
    try:
        date_str = time.strftime("%Y-%m-%d")
        log_file = _DIALOGUE_DIR / f"{date_str}.jsonl"
        entry = {
            "timestamp": time.time(),
            "user": user_input[:200],
            "response": response[:500],
            "intent": intent,
        }
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def load_context(keywords: str = "", limit: int = 5) -> str:
    """加载最近相关对话作为上下文"""
    try:
        logs = sorted(_DIALOGUE_DIR.glob("*.jsonl"), reverse=True)
        recent = []
        for log_file in logs[:3]:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        recent.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        # 取最近的 N 条
        context = recent[-limit:]
        if not context:
            return ""
        lines = ["[最近对话]"]
        for entry in context:
            lines.append(f"用户: {entry['user'][:100]}")
            lines.append(f"诺亚: {entry['response'][:200]}")
        return "\n".join(lines)
    except Exception:
        return ""
