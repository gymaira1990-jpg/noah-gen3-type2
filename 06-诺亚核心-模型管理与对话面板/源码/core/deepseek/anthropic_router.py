"""DeepSeek Anthropic 格式兼容 — 路由层

Anthropic 端点: /api/deepseek/anthropic/...

模型映射:
  claude-opus* → deepseek-v4-pro
  claude-haiku/sonnet* → deepseek-v4-flash
"""

from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from ..kernel import load_config
from ..models import get_model
from .anthropic import (
    DeepSeekAnthropicClient,
    anthropic_messages_to_openai,
    map_anthropic_model,
    DEFAULT_ANTHROPIC_MODEL,
)

anthropic_router = APIRouter(prefix="/api/deepseek/anthropic", tags=["deepseek-anthropic"])


def _get_deepseek_key() -> str:
    """从配置中获取第一个可用 DeepSeek 模型的 API key"""
    cfg = load_config()
    for m in cfg.models:
        if "deepseek" in m.name.lower() and m.api_key:
            return m.api_key
    return ""


@anthropic_router.post("/messages")
async def anthropic_messages(body: dict = Body(...)):
    """Anthropic Messages API 兼容端点

    接收 Anthropic 格式请求，转换为 DeepSeek 格式处理。
    """
    model = body.get("model", DEFAULT_ANTHROPIC_MODEL)
    messages = body.get("messages", [])
    system = body.get("system")
    max_tokens = body.get("max_tokens", 4096)
    temperature = body.get("temperature")
    top_p = body.get("top_p")
    stop_sequences = body.get("stop_sequences")
    stream = body.get("stream", False)

    # 思考模式
    thinking = body.get("thinking")
    thinking_type = None
    effort = None
    if isinstance(thinking, dict):
        thinking_type = "enabled"
    output_config = body.get("output_config", {})
    effort = output_config.get("effort")

    # 转换消息
    oai_messages = anthropic_messages_to_openai(messages)
    if system:
        oai_messages.insert(0, {"role": "system", "content": system})

    # 获取 API key
    api_key = _get_deepseek_key()

    # 调用 DeepSeek
    client = DeepSeekAnthropicClient(api_key=api_key)
    result = client.chat(
        messages=messages,
        model=model,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop_sequences=stop_sequences,
        stream=stream,
        thinking_type=thinking_type,
        effort=effort,
    )

    if result.error:
        return JSONResponse(
            status_code=result.error_code or 500,
            content={"error": {"message": result.error}},
        )

    return {
        "id": result.id or "",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": result.text or ""}
        ],
        "model": model,
        "usage": {
            "input_tokens": result.usage.prompt_tokens,
            "output_tokens": result.usage.completion_tokens,
        },
    }
