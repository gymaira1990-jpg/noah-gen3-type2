"""诺亚核心 · 内核 (kernel)
ModelConfig/Config 数据模型 + YAML 配置读写
"""
from __future__ import annotations
import os
import json
import time
import urllib.request
import sys
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict

# ─── 路径 ───
CONFIG_DIR = Path(os.environ.get("NOAH_CORE_HOME", str(Path.home() / ".noah-core")))
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# ─── 数据模型 ───

@dataclass
class ModelConfig:
    name: str
    provider: str
    api_base: str
    api_key_env: Optional[str] = None
    model_id: str = ""
    real_name: str = ""
    description: str = ""
    notes: str = ""
    type: str = "api"
    temperature: float = 0.7
    max_tokens: int = 4096

    def __post_init__(self):
        if not self.model_id:
            self.model_id = self.name
        if not self.real_name:
            self.real_name = self.model_id

    @property
    def api_key(self) -> Optional[str]:
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Config:
    models: list[ModelConfig] = field(default_factory=list)
    server: dict = field(default_factory=lambda: {
        "host": "127.0.0.1",
        "port": 8110,
        "debug": False,
    })


# ─── 配置读写 ───

def load_config() -> Config:
    if not CONFIG_FILE.exists():
        return Config()
    import yaml
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    models = [ModelConfig(**m) for m in data.get("models", [])]
    cfg = Config(models=models)
    if "server" in data:
        cfg.server.update(data["server"])
    return cfg


def save_config(cfg: Config):
    import yaml
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {"server": cfg.server, "models": [m.to_dict() for m in cfg.models]}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def create_default_config() -> Config:
    cfg = Config(models=[
        ModelConfig(
            name="deepseek-chat",
            real_name="DeepSeek V4 Flash",
            provider="openai",
            api_base="https://api.deepseek.com/v1",
            api_key_env="LLM_API_KEY",
            model_id="deepseek-chat",
            description="DeepSeek V4 Flash — 主力推理模型",
            type="api",
        ),
        ModelConfig(
            name="deepseek-pro",
            real_name="DeepSeek V4 Pro",
            provider="openai",
            api_base="https://api.deepseek.com/v1",
            api_key_env="LLM_API_KEY",
            model_id="deepseek-v4-pro",
            description="DeepSeek V4 Pro — 复杂任务",
            type="api",
        ),
    ])
    save_config(cfg)
    return cfg
