"""DeepSeek Chat Client — 核心引擎

核心职责:
  1. 接收 DeepSeekChatParams → 构建请求 → 调用 API → 解析响应
  2. 支持流式与非流式两种模式
  3. 正确分离 body 与 extra_body 参数
  4. 错误重试（指数退避）
  5. 用量统计（含缓存命中）

关键修正（相对原 chat.py）:
  - thinking/reasoning_content 字段名修正
  - extra_body 路径修正（OpenAI SDK 要求）
  - 全参数覆盖
  - Anthropic 格式支持
"""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Generator
from .params import DeepSeekChatParams, DeepSeekChatResponse, StreamChunk
from .parser import parse_chat_response, parse_sse_chunk, merge_stream_chunks
from .errors import DeepSeekAPIError, ErrorClassifier, RetryHandler


class DeepSeekChatClient:
    """DeepSeek 对话补全客户端

    参数:
        api_key: DeepSeek API Key
        api_base: API 基础地址 (默认: https://api.deepseek.com)
        timeout: HTTP 超时秒数 (默认: 120)
        max_retries: 最大重试次数 (默认: 3)
        user_agent: User-Agent (默认: noah-core/0.2)
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.deepseek.com",
        timeout: int = 120,
        max_retries: int = 3,
        user_agent: str = "noah-core/0.2",
    ):
        self.api_key = api_key
        # 去除尾随 /v1 (兼容旧配置)
        self.api_base = api_base.rstrip("/")
        if self.api_base.endswith("/v1"):
            self.api_base = self.api_base[:-3]
        self.timeout = timeout
        self.retry_handler = RetryHandler(max_retries=max_retries)
        self.user_agent = user_agent

    # ─── 公开接口 ───

    def chat(self, params: DeepSeekChatParams) -> DeepSeekChatResponse:
        """非流式对话补全 — 带重试

        参数:
            params: 完整对话参数
        返回:
            DeepSeekChatResponse
        """
        def _do_chat() -> DeepSeekChatResponse:
            body = params.build_body()
            body["stream"] = False
            resp_data = self._request("/chat/completions", body)
            return parse_chat_response(resp_data)

        try:
            return self.retry_handler.execute(_do_chat)
        except DeepSeekAPIError as e:
            return DeepSeekChatResponse(
                error=e.message,
                error_code=e.code,
                retryable=e.retryable,
            )
        except Exception as e:
            return DeepSeekChatResponse(
                error=str(e),
                error_code=0,
                retryable=False,
            )

    def chat_stream(self, params: DeepSeekChatParams) -> Generator[StreamChunk, None, DeepSeekChatResponse]:
        """流式对话补全 — 产生 StreamChunk 生成器

        用法:
            chunks = []
            for chunk in client.chat_stream(params):
                if chunk.content:
                    print(chunk.content, end="")
                chunks.append(chunk)
            full_response = merge_stream_chunks(chunks)

        返回生成器，耗尽后通过 .value 获取完整响应。
        """
        body = params.build_body()
        body["stream"] = True

        try:
            req = self._build_request("/chat/completions", body)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                while True:
                    raw = resp.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    chunk = parse_sse_chunk(line)
                    if chunk is not None:
                        if chunk.finish_reason == "__done__":
                            break
                        yield chunk

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                err_data = json.loads(error_body)
            except json.JSONDecodeError:
                err_data = error_body
            api_err = ErrorClassifier.from_http(e.code, err_data)
            yield StreamChunk(
                finish_reason="error",
            )
            # 返回错误响应
            return DeepSeekChatResponse(
                error=api_err.message,
                error_code=api_err.code,
                retryable=api_err.retryable,
            )

        except Exception as e:
            yield StreamChunk(finish_reason="error")
            return DeepSeekChatResponse(
                error=str(e),
                error_code=0,
                retryable=False,
            )

        return DeepSeekChatResponse()  # 正常结束，调用方应使用 merge_stream_chunks

    def chat_fim(self, params: DeepSeekChatParams) -> DeepSeekChatResponse:
        """FIM 代码补全 (/beta/completions)"""
        def _do_fim() -> DeepSeekChatResponse:
            body = params.build_fim_body()
            resp_data = self._request("/beta/completions", body)
            return self._parse_fim_response(resp_data)

        try:
            return self.retry_handler.execute(_do_fim)
        except DeepSeekAPIError as e:
            return DeepSeekChatResponse(
                error=e.message,
                error_code=e.code,
                retryable=e.retryable,
            )
        except Exception as e:
            return DeepSeekChatResponse(error=str(e))

    # ─── 内部 ───

    def _build_request(self, path: str, body: dict) -> urllib.request.Request:
        """构建 HTTP 请求对象"""
        url = f"{self.api_base}{path}"
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return urllib.request.Request(url, data=data, headers=headers, method="POST")

    def _request(self, path: str, body: dict) -> dict:
        """执行 HTTP 请求并返回 JSON 响应"""
        req = self._build_request(path, body)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                err_data = json.loads(error_body)
            except json.JSONDecodeError:
                err_data = error_body
            raise ErrorClassifier.from_http(e.code, err_data) from e

    def _parse_fim_response(self, data: dict) -> DeepSeekChatResponse:
        """解析 FIM completions 响应"""
        if "error" in data:
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return DeepSeekChatResponse(error=msg)

        choices = data.get("choices", [{}])
        choice = choices[0] if choices else {}
        return DeepSeekChatResponse(
            text=choice.get("text"),
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", ""),
            id=data.get("id", ""),
            usage=DeepSeekUsage.from_api(data.get("usage")),
        )


# 为了向后兼容，从 parser 中 re-export
from .parser import merge_stream_chunks
from .params import DeepSeekUsage
