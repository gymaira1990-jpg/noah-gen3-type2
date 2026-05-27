"""DeepSeek FastAPI 路由 — 完整对话 API 端点

提供:
  POST /api/deepseek/chat        — 非流式对话
  POST /api/deepseek/chat/stream — 流式对话 (SSE)
  GET  /api/deepseek/models      — 可用模型列表
  POST /api/deepseek/fim         — FIM 代码补全
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import JSONResponse, StreamingResponse
import json

from ..kernel import load_config
from ..models import get_model
from .params import DeepSeekChatParams, DeepSeekChatResponse, DeepSeekUsage
from .client import DeepSeekChatClient, merge_stream_chunks
from .errors import ErrorClassifier

router = APIRouter(prefix="/api/deepseek", tags=["deepseek"])


# ═══════════════════════════════════════
# 辅助: 从配置构建客户端
# ═══════════════════════════════════════

def _build_client(model_name: str) -> tuple[DeepSeekChatClient, str]:
    """从配置加载模型，构建客户端

    支持短名别名:
      pro   → deepseek-pro
      flash → deepseek-v4-flash

    返回: (client, resolved_model_id)
    如果模型不存在或未配置，使用默认配置。
    """
    cfg = load_config()
    model = get_model(cfg, model_name)

    # 短名别名: 精确匹配失败时尝试后缀匹配
    if not model:
        for m in cfg.models:
            if m.name.endswith(f"-{model_name}") or m.name == f"deepseek-{model_name}":
                model = m
                break

    if model:
        api_key = model.api_key or ""
        api_base = model.api_base or "https://api.deepseek.com"
        model_id = model.model_id or model.name
    else:
        # 使用默认配置
        api_key = ""
        api_base = "https://api.deepseek.com"
        model_id = model_name

    client = DeepSeekChatClient(api_key=api_key, api_base=api_base)
    return client, model_id


def _params_from_body(body: dict, model_id: str) -> DeepSeekChatParams:
    """从请求体构建 DeepSeekChatParams"""
    thinking_type = body.get("thinking_type") or body.get("thinking")
    reasoning_effort = body.get("reasoning_effort")
    # reasoning_effort 仅在思考模式下有意义, 非思考模式强制不传
    if not thinking_type or thinking_type == "disabled":
        reasoning_effort = None
    return DeepSeekChatParams(
        messages=body.get("messages", []),
        model=model_id,
        thinking_type=thinking_type,
        reasoning_effort=reasoning_effort,
        temperature=body.get("temperature"),
        top_p=body.get("top_p"),
        max_tokens=body.get("max_tokens"),
        stop=body.get("stop"),
        response_format=body.get("response_format"),
        tools=body.get("tools"),
        tool_choice=body.get("tool_choice"),
        stream=False,  # 非流式路由
        stream_options=body.get("stream_options"),
        logprobs=body.get("logprobs"),
        top_logprobs=body.get("top_logprobs"),
        user_id=body.get("user_id"),
    )


# ═══════════════════════════════════════
# 路由: 非流式对话
# ═══════════════════════════════════════

@router.post("/chat/{name}")
async def deepseek_chat(name: str, body: dict = Body(...)):
    """非流式 DeepSeek 对话补全

    请求体支持所有 DeepSeekChatParams 字段。
    响应包含 reasoning_content, usage 含缓存统计。
    """
    client, model_id = _build_client(name)
    params = _params_from_body(body, model_id)

    result = client.chat(params)

    if result.error:
        return JSONResponse(
            status_code=result.error_code or 500,
            content={
                "error": {
                    "message": result.error,
                    "code": result.error_code,
                    "retryable": result.retryable,
                }
            },
        )

    return _build_response(result)


@router.post("/chat/stream/{name}")
async def deepseek_chat_stream(name: str, body: dict = Body(...)):
    """流式 DeepSeek 对话补全 (SSE)

    返回 SSE 流，每行格式: data: {chunk}
    最后: data: [DONE]
    """
    client, model_id = _build_client(name)
    params = _params_from_body(body, model_id)
    params.stream = True

    async def event_stream():
        chunks = []
        for chunk in client.chat_stream(params):
            chunks.append(chunk)
            if chunk.content or chunk.reasoning_content:
                payload = {"choices": [{"delta": {}}]}
                if chunk.content:
                    payload["choices"][0]["delta"]["content"] = chunk.content
                if chunk.reasoning_content:
                    payload["choices"][0]["delta"]["reasoning_content"] = chunk.reasoning_content
                if chunk.finish_reason:
                    payload["choices"][0]["finish_reason"] = chunk.finish_reason
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # 最后 usage 信息
        merged = merge_stream_chunks(chunks)
        if merged.usage.total_tokens > 0:
            usage_payload = {"choices": [], "usage": _usage_to_dict(merged.usage)}
            yield f"data: {json.dumps(usage_payload, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════
# 路由: FIM 代码补全
# ═══════════════════════════════════════

@router.post("/fim/{name}")
async def deepseek_fim(name: str, body: dict = Body(...)):
    """FIM 代码补全

    请求体:
      prompt: str (必填)
      suffix: str (可选)
      max_tokens: int
      temperature: float
    """
    client, model_id = _build_client(name)

    params = DeepSeekChatParams(
        messages=body.get("messages", []),
        model=model_id,
        temperature=body.get("temperature"),
        max_tokens=body.get("max_tokens"),
        stop=body.get("stop"),
        stream=False,
    )

    result = client.chat_fim(params)
    if result.error:
        return JSONResponse(
            status_code=result.error_code or 500,
            content={"error": {"message": result.error}},
        )

    return {
        "choices": [{"text": result.text, "finish_reason": result.finish_reason}],
        "usage": _usage_to_dict(result.usage),
    }


# ═══════════════════════════════════════
# 路由: 模型列表
# ═══════════════════════════════════════

@router.get("/models")
async def list_deepseek_models():
    """返回可用的 DeepSeek 模型列表

    从配置中筛选 DeepSeek 模型返回。
    """
    cfg = load_config()
    models = [m for m in cfg.models if "deepseek" in m.name.lower()
              or "deepseek" in m.model_id.lower()
              or "deepseek" in m.api_base.lower()]

    return {
        "object": "list",
        "data": [
            {
                "id": m.model_id or m.name,
                "object": "model",
                "name": m.real_name or m.name,
                "provider": m.provider,
                "api_base": m.api_base,
                "description": m.description,
            }
            for m in models
        ]
    }


# ═══════════════════════════════════════
# 辅助
# ═══════════════════════════════════════

def _build_response(result: DeepSeekChatResponse) -> dict:
    """构建标准响应格式"""
    message = {"role": "assistant"}
    if result.text is not None:
        message["content"] = result.text
    else:
        message["content"] = ""
    if result.reasoning_content:
        message["reasoning_content"] = result.reasoning_content
    if result.tool_calls:
        message["tool_calls"] = result.tool_calls

    choice = {
        "index": 0,
        "message": message,
        "finish_reason": result.finish_reason,
    }

    response = {
        "id": result.id or "",
        "object": "chat.completion",
        "choices": [choice],
        "model": result.model,
        "usage": _usage_to_dict(result.usage),
    }

    if result.logprobs:
        choice["logprobs"] = result.logprobs

    return response


def _usage_to_dict(usage: DeepSeekUsage) -> dict:
    """转换用量为 API 格式"""
    result = {
        "completion_tokens": usage.completion_tokens,
        "prompt_tokens": usage.prompt_tokens,
        "total_tokens": usage.total_tokens,
    }
    # 缓存统计（仅在有时）
    if usage.prompt_cache_hit_tokens > 0 or usage.prompt_cache_miss_tokens > 0:
        result["prompt_cache_hit_tokens"] = usage.prompt_cache_hit_tokens
        result["prompt_cache_miss_tokens"] = usage.prompt_cache_miss_tokens
    # 思维链统计
    if usage.reasoning_tokens > 0:
        result["completion_tokens_details"] = {
            "reasoning_tokens": usage.reasoning_tokens
        }
    return result
