#!/usr/bin/env python3
"""NOAH-PRIME · 认证模块 · auth.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
简易Token认证 — 管理后台登录
"""

import hashlib
import time
import yaml
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config" / "server.yaml"

# 默认配置
_tokens = {}
_admin_password = "noah_admin_2026"
_token_expire = 86400  # 24h


def load_config():
    global _admin_password, _token_expire
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
        auth_cfg = cfg.get("auth", {})
        _admin_password = auth_cfg.get("admin_password", _admin_password)
        _token_expire = auth_cfg.get("token_expire_hours", 24) * 3600


load_config()


def generate_token(password: str) -> str | None:
    if password != _admin_password:
        return None
    token = hashlib.sha256(f"{password}{time.time()}".encode()).hexdigest()[:32]
    _tokens[token] = time.time() + _token_expire
    cleanup_expired()
    return token


def verify_token(token: str) -> bool:
    expire = _tokens.get(token)
    if not expire or time.time() > expire:
        return False
    return True


def cleanup_expired():
    now = time.time()
    expired = [t for t, e in _tokens.items() if now > e]
    for t in expired:
        del _tokens[t]
