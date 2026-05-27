"""诺亚核心 · 对话 (chat completion) — 深度适配 DeepSeek API

⚠ 重构版: 委托给 core/deepseek/ 模块，修复 reasoning_content 字段名 +
   extra_body 路径 + 全参数支持 + 重试 + 错误分类 + 缓存统计。

旧接口保持兼容:
  chat_completion(model, messages, extra_params, stream) -> dict
"""

from __future__ import annotations
from .kernel import ModelConfig
from .deepseek.params import DeepSeekChatParams
from .deepseek.client import DeepSeekChatClient, merge_stream_chunks


def chat_completion(model: ModelConfig, messages: list[dict],
                    extra_params: dict | None = None, stream: bool = False) -> dict:
    """对话补全（兼容旧接口）

    内部委托给 DeepSeekChatClient 处理所有细节。

    Args:
        model: 模型配置 (ModelConfig)
        messages: 对话消息列表
        extra_params: 额外参数 (thinking, reasoning_effort, tools 等)
        stream: 是否流式输出

    Returns:
        {"text": str|None, "error": str|None, "thinking_text": str|None}
        注: 旧接口不返回完整 usage; 请使用新 DeepSeekChatClient 获取完整响应
    """
    # 构建 DeepSeek 参数
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
        thinking_param = extra_params.get("thinking")
        if isinstance(thinking_param, dict):
            thinking_type = thinking_param.get("type", "enabled")
        elif isinstance(thinking_param, str):
            thinking_type = thinking_param
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

    params = DeepSeekChatParams(
        messages=messages,
        model=model.model_id or model.name,
        thinking_type=thinking_type,
        reasoning_effort=reasoning_effort,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        tool_choice=tool_choice,
        response_format=response_format,
        stream=stream,
        top_p=top_p,
        stop=stop,
        user_id=user_id,
    )

    client = DeepSeekChatClient(
        api_key=model.api_key or "",
        api_base=model.api_base or "https://api.deepseek.com",
    )

    # 根据 provider 选择路径
    if model.provider == "ollama":
        return _ollama_chat(model, messages, stream, extra_params)

    # DeepSeek / OpenAI 兼容
    if stream:
        chunks = list(client.chat_stream(params))
        merged = merge_stream_chunks(chunks)
        return {
            "text": merged.text,
            "error": merged.error,
            "thinking_text": merged.reasoning_content,
        }

    result = client.chat(params)
    return {
        "text": result.text,
        "error": result.error,
        "thinking_text": result.reasoning_content,
        "usage": result.usage if hasattr(result, 'usage') else None,
        "finish_reason": result.finish_reason if hasattr(result, 'finish_reason') else None,
        "tool_calls": result.tool_calls if hasattr(result, 'tool_calls') else None,
    }


def _ollama_chat(model, messages, stream, extra_params):
    """Ollama 对话（保持不变）"""
    import json
    import urllib.request

    url = f"{model.api_base.rstrip('/')}/api/chat"
    body = {
        "model": model.model_id,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": model.temperature},
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp_data = json.loads(resp.read().decode())
        return {"text": resp_data.get("message", {}).get("content", ""),
                "error": None, "thinking_text": None}


# ─── 新接口（推荐使用） ───

def deepseek_chat(
    api_key: str = "",
    api_base: str = "https://api.deepseek.com",
    messages: list[dict] | None = None,
    model: str = "deepseek-v4-pro",
    **kwargs
) -> "DeepSeekChatResponse":
    """直接调用 DeepSeek 对话（新接口）

    用法:
        from core.chat import deepseek_chat
        result = deepseek_chat(
            api_key="sk-xxx",
            messages=[{"role": "user", "content": "Hello"}],
            model="deepseek-v4-pro",
            thinking_type="enabled",
            reasoning_effort="high",
        )
        print(result.text)
        if result.reasoning_content:
            print(f"思考: {result.reasoning_content}")
    """
    from .deepseek.params import DeepSeekChatParams

    params = DeepSeekChatParams(
        messages=messages or [],
        model=model,
        **{k: v for k, v in kwargs.items() if v is not None},
    )
    client = DeepSeekChatClient(api_key=api_key, api_base=api_base)
    return client.chat(params)
