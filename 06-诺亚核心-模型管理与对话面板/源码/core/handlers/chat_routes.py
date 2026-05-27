"""对话 API router — 全参数透传 + 流式 SSE + Tool Calls"""

from __future__ import annotations
import asyncio
import json
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse
from ..kernel import load_config
from ..models import get_model
from ..chat import chat_completion
from ..deepseek.params import DeepSeekChatParams
from ..deepseek.client import DeepSeekChatClient

router = APIRouter(prefix="/api", tags=["chat"])


def _parse_extra(body: dict) -> dict:
    """从请求体提取 DeepSeek 特有参数"""
    extra = {}
    for key in ("thinking", "reasoning_effort", "tools", "tool_choice",
                "response_format", "temperature", "max_tokens", "stream",
                "top_p", "stop", "user_id"):
        if key in body:
            extra[key] = body[key]
    return extra


@router.post("/chat/{name}")
async def api_chat(name: str, body: dict = Body(...)):
    cfg = load_config()
    model = get_model(cfg, name)
    if not model:
        raise HTTPException(404, f"模型 '{name}' 不存在")
    msgs = body.get("messages", [])
    if not msgs:
        raise HTTPException(400, "messages 不能为空")

    extra_params = _parse_extra(body)
    result = chat_completion(model, msgs, extra_params)
    if result["error"]:
        return JSONResponse({
            "error": {"message": result["error"]},
            "choices": []
        }, status_code=500)

    msg = {"role": "assistant", "content": result.get("text") or ""}
    tc = result.get("thinking_text") or result.get("reasoning_content")
    if tc:
        msg["reasoning_content"] = tc
    tc_list = result.get("tool_calls")
    if tc_list:
        msg["tool_calls"] = tc_list

    resp = {"choices": [{"message": msg, "finish_reason": result.get("finish_reason")}],
            "model": model.model_id or model.name}
    usage = result.get("usage")
    if usage:
        resp["usage"] = usage
    return resp


async def _stream_chunks(client, params):
    """实时流式收集 — 用 asyncio.Queue 桥接同步生成器，每收到一个 chunk 立刻 yield"""
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def _collect():
        try:
            for chunk in client.chat_stream(params):
                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, ("error", str(e)))

    task = asyncio.get_running_loop().run_in_executor(None, _collect)

    while True:
        kind, data = await queue.get()
        if kind == "done":
            break
        elif kind == "error":
            yield ("error", data)
            break
        else:
            yield ("chunk", data)

    await task


@router.post("/chat/{name}/stream")
async def api_chat_stream(name: str, body: dict = Body(...)):
    """流式 SSE 端点 — 实时输出 content + reasoning_content"""
    cfg = load_config()
    model = get_model(cfg, name)
    if not model:
        raise HTTPException(404, f"模型 '{name}' 不存在")
    msgs = body.get("messages", [])
    if not msgs:
        raise HTTPException(400, "messages 不能为空")

    extra_params = _parse_extra(body)
    extra_params["stream"] = True

    # 构建参数
    thinking_type = None
    reasoning_effort = None
    tools = None
    tool_choice = None
    response_format = None
    temperature = model.temperature
    max_tokens = model.max_tokens
    top_p = None
    stop = None
    user_id = None

    if extra_params:
        tp = extra_params.get("thinking")
        if isinstance(tp, dict):
            thinking_type = tp.get("type", "enabled")
        elif tp:
            thinking_type = tp
        reasoning_effort = extra_params.get("reasoning_effort")
        tools = extra_params.get("tools")
        tool_choice = extra_params.get("tool_choice")
        response_format = extra_params.get("response_format")
        if "temperature" in extra_params:
            temperature = extra_params["temperature"]
        if "max_tokens" in extra_params:
            max_tokens = extra_params["max_tokens"]
        top_p = extra_params.get("top_p")
        stop = extra_params.get("stop")
        user_id = extra_params.get("user_id")

    if model.provider == "ollama":
        raise HTTPException(400, "Ollama 暂不支持流式")

    params = DeepSeekChatParams(
        messages=msgs,
        model=model.model_id or model.name,
        thinking_type=thinking_type,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        response_format=response_format,
        stream=True,
        top_p=top_p,
        stop=stop,
        user_id=user_id,
    )

    client = DeepSeekChatClient(
        api_key=model.api_key or "",
        api_base=model.api_base or "https://api.deepseek.com",
    )

    async def event_stream():
        try:
            async for kind, data in _stream_chunks(client, params):
                if kind == "error":
                    yield f"data: {json.dumps({'error': data})}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                if kind == "done":
                    yield "data: [DONE]\n\n"
                    return

                chunk = data
                msg = {
                    "choices": [{
                        "delta": {},
                        "index": 0,
                        "finish_reason": None,
                    }]
                }
                if chunk.content:
                    msg["choices"][0]["delta"]["content"] = chunk.content
                if chunk.reasoning_content:
                    msg["choices"][0]["delta"]["reasoning_content"] = chunk.reasoning_content
                if chunk.finish_reason:
                    msg["choices"][0]["finish_reason"] = chunk.finish_reason

                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

                if chunk.finish_reason:
                    extra = {}
                    if chunk.model:
                        extra["model"] = chunk.model
                    if chunk.usage:
                        extra["usage"] = asdict(chunk.usage)
                    if extra:
                        yield f"data: {json.dumps(extra, ensure_ascii=False)}\n\n"
                else:
                    # 无 finish_reason → 持续流式输出
                    pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
