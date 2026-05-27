"""DeepSeek 响应解析 — 流式（SSE）+ 非流式

关键修正:
  - delta.reasoning_content 而非 delta.thinking  ← 原 chat.py 的错误
  - non-streaming 响应中 msg.reasoning_content 而非 msg.thinking
  - finish_reason: insufficient_system_resource 处理
  - stream_options.include_usage 支持
"""

from __future__ import annotations
import json
from typing import Generator
from .params import DeepSeekChatResponse, DeepSeekUsage, StreamChunk


# ═══════════════════════════════════════
# 非流式响应解析
# ═══════════════════════════════════════

def parse_chat_response(data: dict) -> DeepSeekChatResponse:
    """解析非流式 /chat/completions 响应

    直接从 API JSON 响应构建标准响应对象。
    """
    if "error" in data:
        err = data["error"]
        code = err.get("code", 500) if isinstance(err, dict) else 500
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        return DeepSeekChatResponse(
            error=msg,
            error_code=code,
            retryable=(code in (429, 500, 503)),
        )

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    # ─── 核心字段 ───
    text = message.get("content") or None
    reasoning_content = message.get("reasoning_content") or None  # ⚠ 非 thinking ⚠
    finish_reason = choice.get("finish_reason", "stop")

    # ─── 工具调用 ───
    tool_calls_raw = message.get("tool_calls")
    tool_calls = None
    if tool_calls_raw:
        tool_calls = []
        for tc in tool_calls_raw:
            func = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id"),
                "type": tc.get("type", "function"),
                "function": {
                    "name": func.get("name"),
                    "arguments": func.get("arguments"),
                },
            })

    # ─── 日志概率 ───
    logprobs = choice.get("logprobs")

    return DeepSeekChatResponse(
        text=text,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        model=data.get("model", ""),
        id=data.get("id", ""),
        usage=DeepSeekUsage.from_api(data.get("usage")),
        logprobs=logprobs,
    )


# ═══════════════════════════════════════
# 流式响应解析（SSE）
# ═══════════════════════════════════════

def parse_sse_chunk(raw_line: str) -> StreamChunk | None:
    """解析单行 SSE 数据

    格式: "data: {...}" 或 "data: [DONE]"
    返回 StreamChunk 或 None（空行/心跳）
    """
    line = raw_line.strip()
    if not line:
        return None                         # 空行（保活心跳）

    if not line.startswith("data: "):
        return None                         # :keep-alive 注释

    payload = line[6:].strip()
    if payload == "[DONE]":
        return StreamChunk(finish_reason="__done__")  # 流结束标记

    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return None

    choices = chunk.get("choices", [])
    if not choices:
        # usage-only chunk (stream_options.include_usage)
        usage_data = chunk.get("usage")
        return StreamChunk(
            usage=DeepSeekUsage.from_api(usage_data) if usage_data else None,
            model=chunk.get("model", ""),
            id=chunk.get("id", ""),
        )

    choice = choices[0]
    delta = choice.get("delta", {})

    # ─── 核心字段 ⚠ ⚠ ⚠ ───
    content = delta.get("content", "")
    reasoning_content = delta.get("reasoning_content", "")  # ⚠ 非 thinking ⚠
    finish_reason = choice.get("finish_reason")

    # ─── 工具调用（流式） ───
    tool_calls_delta = delta.get("tool_calls")
    tool_calls = None
    if tool_calls_delta and isinstance(tool_calls_delta, list):
        tool_calls = []
        for tc in tool_calls_delta:
            func = tc.get("function", {})
            tool_calls.append({
                "id": tc.get("id", ""),
                "type": tc.get("type", "function"),
                "index": tc.get("index", 0),
                "function": {
                    "name": func.get("name", ""),
                    "arguments": func.get("arguments", ""),
                },
            })

    # ─── 最后 chunk 可能带 usage ───
    usage_data = chunk.get("usage") if finish_reason else None

    return StreamChunk(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=DeepSeekUsage.from_api(usage_data) if usage_data else None,
        model=chunk.get("model", ""),
        id=chunk.get("id", ""),
    )


def parse_sse_stream(lines: Generator[str, None, None]) -> Generator[StreamChunk, None, None]:
    """解析 SSE 流，逐行产生 StreamChunk

    用法:
        for chunk in parse_sse_stream(response_lines):
            if chunk.content: print(chunk.content, end="")
    """
    for line in lines:
        chunk = parse_sse_chunk(line)
        if chunk is not None:
            yield chunk


def merge_stream_chunks(chunks: list[StreamChunk]) -> DeepSeekChatResponse:
    """将流式 chunks 合并为完整响应

    用于非流式 API 调用者获取完整结果。
    """
    full_text = ""
    full_reasoning = ""
    last_usage = None

    for c in chunks:
        if c.content:
            full_text += c.content
        if c.reasoning_content:
            full_reasoning += c.reasoning_content
        if c.usage:
            last_usage = c.usage

    # 获取最后的 finish_reason（非 __done__）
    finish = "stop"
    for c in reversed(chunks):
        if c.finish_reason and c.finish_reason != "__done__":
            finish = c.finish_reason
            break

    return DeepSeekChatResponse(
        text=full_text or None,
        reasoning_content=full_reasoning or None,
        finish_reason=finish,
        usage=last_usage or DeepSeekUsage(),
    )
