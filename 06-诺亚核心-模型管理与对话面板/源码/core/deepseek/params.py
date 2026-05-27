"""DeepSeek 全量参数/响应模型 — 精确映射官方文档"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════
# 请求参数模型
# ═══════════════════════════════════════

@dataclass
class DeepSeekChatParams:
    """/chat/completions 全量参数，精确映射 DeepSeek 官方规格

    字段命名规则: API 参数名 = 字段名，转换在 _build_body() 中处理。
    """

    # ─── 必填 ───
    messages: list[dict]               # 对话消息列表 (≥1)
    model: str = "deepseek-v4-pro"     # deepseek-v4-flash / deepseek-v4-pro

    # ─── 思考模式 ⚠ 关键修正 ⚠ ───
    # thinking.type 走 extra_body，不能用 thinking 参数直接传
    thinking_type: str | None = None          # "enabled" / "disabled" → extra_body
    reasoning_effort: str | None = None       # "high" / "max" — 思考强度

    # ─── 采样参数 ───
    temperature: float | None = None          # 0~2, 思考模式下不生效
    top_p: float | None = None                # 0~1, 思考模式下不生效
    max_tokens: int | None = None
    stop: str | list[str] | None = None       # 最多16个

    # ─── JSON 输出 ───
    response_format: str | None = None        # None / "json_object"

    # ─── 工具调用 ───
    tools: list[dict] | None = None            # 最多128个 function
    tool_choice: str | dict | None = None     # "none" / "auto" / "required" / {"type":"function",...}

    # ─── 流式 ───
    stream: bool = False
    stream_options: dict | None = None         # {"include_usage": true}

    # ─── 对数概率 ───
    logprobs: bool | None = None
    top_logprobs: int | None = None            # ≤20

    # ─── 用户隔离 ───
    user_id: str | None = None                # [a-zA-Z0-9\\-_]+, ≤512 → extra_body

    # ─── Beta 功能 ───
    # 对话前缀续写: messages 最后一条 role=assistant, prefix=True
    # FIM 补全走 /beta/completions (见 create_completion 方法)

    # ─── 兼容 deprecated ───
    # presence_penalty / frequency_penalty: 已弃用，传入不报错但无效

    def build_body(self) -> dict:
        """构建发给 API 的请求体，正确分离 extra_body 参数"""
        body: dict = {
            "model": self.model,
            "messages": self.messages,
            "stream": self.stream,
        }

        # 直接 body 参数
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.stop is not None:
            body["stop"] = self.stop
        if self.response_format is not None:
            if isinstance(self.response_format, dict):
                body["response_format"] = self.response_format
            else:
                body["response_format"] = {"type": self.response_format}
        if self.tools is not None:
            body["tools"] = self.tools
        if self.tool_choice is not None:
            body["tool_choice"] = self.tool_choice
        if self.stream_options is not None:
            body["stream_options"] = self.stream_options
        if self.logprobs is not None:
            body["logprobs"] = self.logprobs
        if self.top_logprobs is not None:
            body["top_logprobs"] = self.top_logprobs

        # ─── 思考模式 / user_id ───
        # 注: 直调 HTTP 时 thinking/user_id 直接放 body
        #     使用 OpenAI SDK 时需通过 extra_body，本 client 走直调路径
        if self.thinking_type is not None:
            body["thinking"] = {"type": self.thinking_type}
        # reasoning_effort 仅对思考模式有效, disable 时冲突
        if self.reasoning_effort is not None and self.thinking_type != "disabled":
            body["reasoning_effort"] = self.reasoning_effort
        if self.user_id is not None:
            body["user_id"] = self.user_id

        return body

    def build_fim_body(self) -> dict:
        """构建 FIM /beta/completions 请求体

        注意: FIM 使用 completions API 而非 chat/completions
        """
        body: dict = {
            "model": self.model,
            "prompt": self._get_prompt(),
        }
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.top_p is not None:
            body["top_p"] = self.top_p
        if self.stop is not None:
            body["stop"] = self.stop
        if self.stream:
            body["stream"] = True
        suffix = self._get_suffix()
        if suffix:
            body["suffix"] = suffix
        return body

    def _get_prompt(self) -> str:
        """从 messages 中提取 FIM prompt（最后一条 user 消息）"""
        for msg in reversed(self.messages):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _get_suffix(self) -> str | None:
        """从 messages 中提取 FIM suffix（如果有 assistant 前缀消息）"""
        # FIM suffix 通过最后一条 assistant 消息的 content 提供
        for msg in reversed(self.messages):
            if msg.get("role") == "assistant" and msg.get("prefix"):
                return None  # 前缀续写不走 FIM suffix
        return None


# ═══════════════════════════════════════
# 响应模型
# ═══════════════════════════════════════

@dataclass
class DeepSeekUsage:
    """Token 用量 — 含缓存命中统计"""
    completion_tokens: int = 0
    prompt_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0       # completion_tokens_details.reasoning_tokens

    @classmethod
    def from_api(cls, usage: dict | None) -> DeepSeekUsage:
        if not usage:
            return cls()
        details = usage.get("completion_tokens_details", {}) or {}
        return cls(
            completion_tokens=usage.get("completion_tokens", 0),
            prompt_tokens=usage.get("prompt_tokens", 0),
            prompt_cache_hit_tokens=usage.get("prompt_cache_hit_tokens", 0),
            prompt_cache_miss_tokens=usage.get("prompt_cache_miss_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            reasoning_tokens=details.get("reasoning_tokens", 0),
        )


@dataclass
class DeepSeekChatResponse:
    """标准化的对话补全响应

    核心字段:
       text — 模型回复
       reasoning_content — 思维链内容 (仅思考模式)
       tool_calls — 工具调用列表 (仅工具调用)
       finish_reason — 停止原因
       usage — Token 用量 (含缓存)
    """
    text: str | None = None
    reasoning_content: str | None = None      # ⚠ 字段名: reasoning_content, 非 thinking
    tool_calls: list[dict] | None = None
    finish_reason: str = "stop"               # stop/length/content_filter/tool_calls/insufficient_system_resource
    model: str = ""
    id: str = ""
    usage: DeepSeekUsage = field(default_factory=DeepSeekUsage)
    logprobs: dict | None = None
    error: str | None = None
    error_code: int | None = None
    retryable: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def is_thinking(self) -> bool:
        return bool(self.reasoning_content)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_insufficient_resource(self) -> bool:
        return self.finish_reason == "insufficient_system_resource"


@dataclass
class StreamChunk:
    """流式响应的一个 chunk"""
    content: str = ""
    reasoning_content: str = ""        # ⚠ 字段名修正
    tool_calls: list[dict] | None = None
    finish_reason: str | None = None
    usage: DeepSeekUsage | None = None
    model: str = ""
    id: str = ""

    @property
    def is_done(self) -> bool:
        return self.finish_reason is not None

    @property
    def has_content(self) -> bool:
        return bool(self.content) or bool(self.reasoning_content)
