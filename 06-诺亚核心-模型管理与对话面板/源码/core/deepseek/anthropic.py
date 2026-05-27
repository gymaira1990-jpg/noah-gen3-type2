"""DeepSeek Anthropic API 兼容层

Anthropic 格式端点: https://api.deepseek.com/anthropic

模型映射:
  claude-opus* → deepseek-v4-pro
  claude-haiku*, claude-sonnet* → deepseek-v4-flash
  不支持的模型名 → deepseek-v4-flash

兼容性:
  - text, thinking, tool_use, tool_result: ✅
  - image, document, redacted_thinking: ❌
  - MCP, code_execution: ❌
"""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Generator
from .params import DeepSeekChatParams, DeepSeekChatResponse, StreamChunk
from .parser import parse_chat_response, parse_sse_chunk, merge_stream_chunks
from .errors import DeepSeekAPIError, ErrorClassifier, RetryHandler


# ═══════════════════════════════════════
# 模型映射
# ═══════════════════════════════════════

ANTHROPIC_MODEL_MAP = {
    "opus": "deepseek-v4-pro",
    "haiku": "deepseek-v4-flash",
    "sonnet": "deepseek-v4-flash",
}

DEFAULT_ANTHROPIC_MODEL = "deepseek-v4-flash"


def map_anthropic_model(model: str) -> str:
    """将 Anthropic 模型名映射到 DeepSeek 模型名"""
    model_lower = model.lower()
    for key, ds_model in ANTHROPIC_MODEL_MAP.items():
        if key in model_lower:
            return ds_model
    return DEFAULT_ANTHROPIC_MODEL


# ═══════════════════════════════════════
# 消息格式转换
# ═══════════════════════════════════════

def anthropic_messages_to_openai(messages: list) -> list[dict]:
    """将 Anthropic 消息格式转换为 OpenAI 格式

    Anthropic 格式:
      [{"role": "user", "content": [{"type": "text", "text": "..."}]}]
    OpenAI 格式:
      [{"role": "user", "content": "..."}]
    """
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, str):
            result.append({"role": role, "content": content})
        elif isinstance(content, list):
            # 提取 text 内容，忽略 image/document 等不支持类型
            texts = []
            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    texts.append(block.get("text", ""))
                elif btype == "tool_use":
                    # 保留 tool_use 结构
                    result.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }],
                    })
                    continue
                elif btype == "tool_result":
                    result.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    })
                    continue
                elif btype == "thinking":
                    # thinking 块内容
                    texts.append(block.get("thinking", ""))
                # image/document: 跳过

            if texts:
                result.append({"role": role, "content": "\n".join(texts)})

    return result


# ═══════════════════════════════════════
# Anthropic 客户端
# ═══════════════════════════════════════

class DeepSeekAnthropicClient:
    """Anthropic API 格式 → DeepSeek 后端

    允许使用 Anthropic SDK 调用 DeepSeek 模型。
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.deepseek.com",
        timeout: int = 120,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        # 注意: 本类做格式转换→调用标准 OpenAI 端点, 不是 Anthropic 兼容端点
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.retry_handler = RetryHandler(max_retries=max_retries)

    def chat(
        self,
        messages: list,
        model: str = "deepseek-v4-pro",
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        top_p: float | None = None,
        stop_sequences: list[str] | None = None,
        stream: bool = False,
        thinking_type: str | None = None,
        effort: str | None = None,
    ) -> DeepSeekChatResponse:
        """Anthropic 格式对话补全

        参数:
            messages: Anthropic 格式消息列表
            model: 模型名（自动映射）
            system: system prompt
            max_tokens: 最大输出 token
            temperature: 温度 (0~2)
            top_p: 核采样
            stop_sequences: 停止序列
            stream: 是否流式
            thinking_type: "enabled" / "disabled"
            effort: "high" / "max"
        """
        ds_model = map_anthropic_model(model)

        # 转换消息格式
        oai_messages = anthropic_messages_to_openai(messages)
        if system:
            oai_messages.insert(0, {"role": "system", "content": system})

        # 构建 DeepSeek 参数
        ds_params = DeepSeekChatParams(
            messages=oai_messages,
            model=ds_model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stop=stop_sequences,
            stream=stream,
            thinking_type=thinking_type,
            reasoning_effort=effort,
        )

        # 用标准客户端调用
        client = DeepSeekChatClient(
            api_key=self.api_key,
            api_base=self.api_base,
            timeout=self.timeout,
        )

        if stream:
            return client.chat_stream(ds_params)  # type: ignore
        return client.chat(ds_params)


from .client import DeepSeekChatClient
