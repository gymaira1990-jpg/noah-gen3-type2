#!/usr/bin/env python3
"""API预算预警 · budget.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 遵循 NOA-006 补充4
"""

import json
from pathlib import Path
from datetime import datetime

BUDGET_FILE = Path(__file__).parent / "data" / "api_budget.json"
MONTHLY_BUDGET = 500  # 元
WARN_THRESHOLD = 0.80
BLOCK_THRESHOLD = 0.95
COST_PER_1K_TOKENS = {"deepseek-v4-flash": 0.002, "deepseek-v4-pro": 0.01, "doubao": 0.003}


class Budget:
    def __init__(self):
        self.data = self._load()
        # 月初重置
        if self.data.get("month") != datetime.now().strftime("%Y-%m"):
            self.data = {"month": datetime.now().strftime("%Y-%m"),
                         "tokens": 0, "cost": 0.0, "calls": 0}
            self._save()

    def _load(self) -> dict:
        if BUDGET_FILE.exists():
            try:
                return json.loads(BUDGET_FILE.read_text())
            except Exception:
                pass
        return {"month": datetime.now().strftime("%Y-%m"), "tokens": 0, "cost": 0.0, "calls": 0}

    def _save(self):
        BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_FILE.write_text(json.dumps(self.data, ensure_ascii=False))

    def record(self, model: str, tokens: int):
        cost_per_k = COST_PER_1K_TOKENS.get(model, 0.002)
        cost = tokens / 1000 * cost_per_k
        self.data["tokens"] += tokens
        self.data["cost"] += cost
        self.data["calls"] += 1
        self._save()

    @property
    def ratio(self) -> float:
        return self.data["cost"] / MONTHLY_BUDGET

    @property
    def remaining(self) -> float:
        return MONTHLY_BUDGET - self.data["cost"]

    def check(self) -> dict:
        r = self.ratio
        if r >= BLOCK_THRESHOLD:
            return {"level": "block", "message":
                    f"⚠ API预算已用 {r:.0%}（¥{self.data['cost']:.0f}/¥{MONTHLY_BUDGET}）。"
                    f"已切换为仅本地模式。",
                    "allow_api": False}
        elif r >= WARN_THRESHOLD:
            return {"level": "warn", "message":
                    f"📊 本月API预算剩余约 ¥{self.remaining:.0f}（已用{r:.0%}）。"
                    f"建议减少非必要调用。",
                    "allow_api": True}
        return {"level": "ok", "allow_api": True, "message": ""}


budget = Budget()
