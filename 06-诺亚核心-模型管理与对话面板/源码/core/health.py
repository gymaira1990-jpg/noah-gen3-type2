"""诺亚核心 · 模型健康检查"""
import os, time, json, urllib.request
from dataclasses import dataclass, field
from typing import Optional
from .kernel import ModelConfig

@dataclass
class ModelStatus:
    name: str
    online: bool
    latency_ms: float = 0
    error: str = ""
    provider: str = ""
    model_id: str = ""
    description: str = ""
    type: str = "api"

    @property
    def status_emoji(self) -> str:
        return "🟢" if self.online else "🔴"

    @property
    def status_text(self) -> str:
        if self.online:
            return f"在线 ({self.latency_ms:.0f}ms)"
        if self.error:
            return f"离线: {self.error[:40]}"
        return "未知"


def check_model_health(model: ModelConfig) -> ModelStatus:
    status = ModelStatus(
        name=model.name, online=False,
        provider=model.provider, model_id=model.model_id,
        description=model.description, type=model.type,
    )
    start = time.time()
    try:
        if model.provider == "ollama":
            url = f"{model.api_base.rstrip('/')}/api/tags"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                for m in data.get("models", []):
                    if m.get("name", "").startswith(model.model_id):
                        status.online = True
                        break
                if not status.online:
                    status.online = True
                    status.error = f"模型 {model.model_id} 未下载"

        elif model.provider in ("openai", "llamacpp", "local"):
            url = f"{model.api_base.rstrip('/')}/models"
            headers = {"Content-Type": "application/json"}
            key = model.api_key
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if "data" in data:
                    status.online = True

        status.latency_ms = (time.time() - start) * 1000

    except urllib.error.HTTPError as e:
        status.error = f"HTTP {e.code}: {e.reason}"
        status.latency_ms = (time.time() - start) * 1000
    except urllib.error.URLError as e:
        status.error = f"连接失败: {e.reason}"
        status.latency_ms = (time.time() - start) * 1000
    except Exception as e:
        status.error = str(e)
        status.latency_ms = (time.time() - start) * 1000
    return status


def check_all_models(cfg_models: list[ModelConfig]) -> list[ModelStatus]:
    return [check_model_health(m) for m in cfg_models]
