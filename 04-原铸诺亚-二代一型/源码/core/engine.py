#!/usr/bin/env python3
"""LLM引擎 · engine.py

原铸诺亚的 LLM 调用层。
通过 httpx 直接调用 DeepSeek API。
"""

import json, httpx
from typing import Optional

import os

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

# 默认模型配置
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048


def _call_llm(messages: list,
              model: str = DEFAULT_MODEL,
              temperature: float = DEFAULT_TEMPERATURE,
              max_tokens: int = DEFAULT_MAX_TOKENS) -> Optional[str]:
    """调用 LLM

    Args:
        messages: [{"role": "system", "content": "..."},
                   {"role": "user", "content": "..."}]
        model: DeepSeek 模型名
        temperature: 温度 (0.0-1.0)
        max_tokens: 最大生成长度

    Returns:
        str | None: 模型回复文本
    """
    try:
        with httpx.Client(timeout=60) as c:
            r = c.post(DEEPSEEK_URL, json={
                "model": model,
                "messages": messages,
                "stream": False,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }, headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"})
            if r.status_code == 200:
                data = r.json()
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
    except Exception:
        pass
    return None


# ─── 快捷调用 ───

def chat(system: str, user: str, **kwargs) -> Optional[str]:
    """单轮对话快捷入口"""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return _call_llm(messages, **kwargs)


def json_mode(system: str, user: str, **kwargs) -> dict:
    """JSON 模式: 强制模型输出 JSON"""
    result = _call_llm(
        messages=[
            {"role": "system", "content": f"{system}\n必须输出JSON格式。"},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        **kwargs
    )
    if result:
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return {"error": "not_json", "raw": result[:200]}
    return {"error": "no_response"}
