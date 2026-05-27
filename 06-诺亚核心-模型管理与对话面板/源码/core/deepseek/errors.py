"""DeepSeek 错误分类与重试机制"""

from __future__ import annotations
import time
import random
from typing import Callable, TypeVar

T = TypeVar("T")


# ═══════════════════════════════════════
# 错误分类
# ═══════════════════════════════════════

class DeepSeekAPIError(Exception):
    """DeepSeek API 返回的错误"""
    def __init__(self, code: int, message: str, detail: str = ""):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(f"[{code}] {message}: {detail}")

    @property
    def retryable(self) -> bool:
        return ErrorClassifier.is_retryable(self.code)


class ErrorClassifier:
    """错误码分类表 — 精确映射 DeepSeek 官方错误码文档"""

    CLASSIFICATION = {
        400: ("格式错误", False, "请求体格式错误，请根据错误信息修改"),
        401: ("认证失败", False, "API Key 错误或缺失"),
        402: ("余额不足", False, "账号余额不足，请充值"),
        422: ("参数错误", False, "请求体参数错误，请根据提示修改"),
        429: ("速率限制", True, "请求速率达到上限，等待后重试"),
        500: ("服务器故障", True, "服务器内部故障，等待后重试"),
        503: ("服务器繁忙", True, "服务器负载过高，稍后重试"),
    }

    RETRYABLE_CODES = {429, 500, 503}

    FINISH_REASON_MAP = {
        "stop": "模型自然停止生成或遇到 stop 序列",
        "length": "输出达到上下文或 max_tokens 限制",
        "content_filter": "输出内容被过滤策略拦截",
        "tool_calls": "模型发起工具调用",
        "insufficient_system_resource": "后端推理资源不足，生成被打断",
    }

    @classmethod
    def classify(cls, code: int) -> tuple[str, bool, str]:
        """返回 (简短描述, 是否可重试, 建议)"""
        return cls.CLASSIFICATION.get(code, ("未知错误", False, "请查阅 DeepSeek 错误码文档"))

    @classmethod
    def is_retryable(cls, code: int) -> bool:
        return code in cls.RETRYABLE_CODES

    @classmethod
    def describe_finish_reason(cls, reason: str) -> str:
        return cls.FINISH_REASON_MAP.get(reason, f"未知 finish_reason: {reason}")

    @classmethod
    def from_http(cls, status_code: int, body: dict | str = "") -> DeepSeekAPIError:
        """从 HTTP 响应构建 DeepSeekAPIError"""
        if isinstance(body, dict):
            msg = body.get("error", {}).get("message", body.get("message", ""))
            detail = str(body)
        else:
            msg = str(body)
            detail = body
        name, retryable, hint = cls.classify(status_code)
        full_msg = f"{name}: {msg or hint}"
        return DeepSeekAPIError(status_code, full_msg, detail)


# ═══════════════════════════════════════
# 指数退避重试
# ═══════════════════════════════════════

class RetryHandler:
    """带指数退避 + 抖动（jitter）的重试器

    策略:
      - 基础延迟: base_delay (秒)
      - 最大延迟: max_delay (秒)
      - 指数因子: 2x
      - 抖动: ±50% 随机
      - 仅对 retryable 错误重试
    """

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def execute(self, func: Callable[[], T]) -> T:
        """执行函数，失败时按策略重试"""
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except DeepSeekAPIError as e:
                last_error = e
                if not e.retryable or attempt >= self.max_retries:
                    raise
                delay = self._calc_delay(attempt)
                time.sleep(delay)
            except Exception as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise
                delay = self._calc_delay(attempt)
                time.sleep(delay)
        raise last_error  # type: ignore

    def _calc_delay(self, attempt: int) -> float:
        """指数退避 + 抖动"""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter = delay * (0.5 + random.random() * 0.5)  # ±25% 抖动
        return min(jitter, self.max_delay)
