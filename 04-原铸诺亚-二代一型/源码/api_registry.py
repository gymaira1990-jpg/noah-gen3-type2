#!/usr/bin/env python3
"""API自适应注册表 · api_registry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 自我进化模块
给你一个API名字和密钥·诺亚自动收集模型信息
"""

import json
import httpx
from pathlib import Path
from datetime import datetime

PRIME_ROOT = Path(__file__).parent
REGISTRY_FILE = PRIME_ROOT / "data" / "api_registry.json"

# ─── 已知API (预填充) ───
KNOWN_APIS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "models_endpoint": "/models",
        "chat_endpoint": "/chat/completions",
        "can_query_balance": True,
        "balance_endpoint": "https://api.deepseek.com/user/balance",
        "models": {
            "deepseek-v4-flash": {"max_context": 128000, "max_output": 8192, "input_price_per_1k": 0.001, "output_price_per_1k": 0.004},
            "deepseek-v4-pro": {"max_context": 128000, "max_output": 8192, "input_price_per_1k": 0.005, "output_price_per_1k": 0.020},
        },
        "verified_at": "2026-05-09",
    },
    "doubao": {
        "name": "豆包(火山引擎)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models_endpoint": None,  # 豆包不支持列出模型
        "chat_endpoint": "/chat/completions",
        "can_query_balance": False,
        "models": {
            "doubao-seed-2-0-lite-260215": {"max_context": 128000, "max_output": 4096, "input_price_per_1k": 0.0008, "output_price_per_1k": 0.002},
            "doubao-seed-2-0-mini-260215": {"max_context": 128000, "max_output": 4096, "input_price_per_1k": 0.0004, "output_price_per_1k": 0.001},
        },
        "verified_at": "2026-05-09",
    },
}


class ApiRegistry:
    """API注册表——自进化"""

    def __init__(self):
        self.apis = self._load()

    def _load(self) -> dict:
        if REGISTRY_FILE.exists():
            try:
                return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass
        return KNOWN_APIS

    def _save(self):
        REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(json.dumps(self.apis, ensure_ascii=False, indent=2))

    def register(self, name: str, api_key: str, base_url: str) -> dict:
        """注册新API——自动查询模型列表和余额"""
        result = {"name": name, "status": "registered", "models_found": 0}

        # 尝试查询模型列表
        try:
            r = httpx.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
            if r.status_code == 200:
                data = r.json()
                models = {}
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    if mid:
                        models[mid] = {"max_context": 128000, "max_output": 8192}
                result["models_found"] = len(models)
                result["models"] = list(models.keys())[:10]

                self.apis[name] = {
                    "name": name, "base_url": base_url,
                    "models": models,
                    "can_query_models": True,
                    "verified_at": datetime.now().isoformat(),
                }
        except Exception:
            result["note"] = "无法查询模型列表·需手动配置"
            self.apis[name] = {
                "name": name, "base_url": base_url,
                "models": {}, "can_query_models": False,
                "verified_at": datetime.now().isoformat(),
            }

        self._save()
        return result

    def query_balance(self, name: str, api_key: str) -> dict:
        """查询API余额"""
        api = self.apis.get(name, {})
        if not api.get("can_query_balance"):
            return {"status": "unsupported", "note": f"{name}不支持API查询余额"}

        try:
            r = httpx.get(
                api.get("balance_endpoint", ""),
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                return {"status": "ok", "balance": data}
        except Exception as e:
            return {"status": "error", "note": str(e)[:100]}

        return {"status": "unknown"}

    def get_model_info(self, model_name: str) -> dict:
        """获取模型信息"""
        for api_name, api in self.apis.items():
            if model_name in api.get("models", {}):
                return {**api["models"][model_name], "provider": api_name, "base_url": api["base_url"]}
        return {}

    def list_all(self) -> dict:
        return {
            "providers": len(self.apis),
            "total_models": sum(len(a.get("models", {})) for a in self.apis.values()),
            "apis": {k: {"name": v["name"], "models": list(v.get("models", {}).keys()),
                         "can_query_balance": v.get("can_query_balance", False)}
                     for k, v in self.apis.items()},
        }


registry = ApiRegistry()
