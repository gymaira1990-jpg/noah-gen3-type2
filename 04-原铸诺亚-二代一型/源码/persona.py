#!/usr/bin/env python3
"""人格滤镜引擎 · persona.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 圣典语调 (Codex Tone)

从 persona.yaml 加载风格配置，为回复应用前缀/后缀/长度限制
"""

import yaml
import random
from pathlib import Path

PRIME_ROOT = Path(__file__).parent
PERSONA_FILE = PRIME_ROOT / "persona.yaml"


class PersonaFilter:
    """圣典语调滤镜"""

    def __init__(self, profile_name: str = None):
        with open(PERSONA_FILE) as f:
            cfg = yaml.safe_load(f)
        self.config = cfg["persona"]
        self.profiles = self.config["profiles"]
        self.active = self.profiles.get(
            profile_name or self.config["active_profile"],
            self.profiles["tech_partner"],
        )

    def switch(self, profile_name: str):
        """切换人格"""
        if profile_name in self.profiles:
            self.active = self.profiles[profile_name]
            return True
        return False

    def apply(self, text: str) -> str:
        """应用风格滤镜"""
        p = self.active

        # 前缀
        if p.get("prefix"):
            text = p["prefix"] + text

        # 后缀
        if p.get("suffix") and random.random() < 0.7:  # 70%概率加后缀
            text = text.rstrip() + p["suffix"]

        # 长度限制
        max_chars = p.get("max_reply_chars", 2000)
        if len(text) > max_chars:
            text = text[:max_chars - 3] + "..."

        return text

    def list_profiles(self) -> list:
        return [
            {"id": k, "name": v.get("name", k), "tone": v.get("tone", "")}
            for k, v in self.profiles.items()
        ]


# ─── 测试 ───
if __name__ == "__main__":
    pf = PersonaFilter()
    print("当前人格:", pf.active["name"])
    print("可用人格:", [p["name"] for p in pf.list_profiles()])

    test = "数据库备份方案: 使用 pg_dump noah_prime > backup.sql 即可。"
    for name in ["tech_partner", "creative_buddy", "magos", "datasmith"]:
        pf.switch(name)
        print(f"\n{name}: {pf.apply(test)}")
