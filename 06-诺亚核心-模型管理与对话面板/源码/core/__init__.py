"""诺亚核心 — 兼容入口
re-export 所有核心函数，保持 from core import xxx 可用
"""

# ─── kernel ───
from .kernel import (
    ModelConfig, Config,
    load_config, save_config, create_default_config,
    CONFIG_DIR, CONFIG_FILE,
)

# ─── models ───
from .models import add_model, remove_model, get_model

# ─── health ───
from .health import ModelStatus, check_model_health, check_all_models

# ─── chat ───
from .chat import chat_completion, deepseek_chat

# ─── deepseek ───
from . import deepseek   # 新模块: core.deepseek.xxx

# ─── discovery ───
from .discovery import (
    fetch_models_from_api, discover_ollama_models,
    discover_llamacpp_models, search_hf_models,
    pull_hf_model, pull_ollama_model,
)

# ─── dashboard ───
from .dashboard import DashboardData, build_dashboard, render_dashboard_text

# ─── CLI ───
from .cli import main as cli_main

# ─── Server ───
from .server import create_app, start_server

__version__ = "0.2.1"
