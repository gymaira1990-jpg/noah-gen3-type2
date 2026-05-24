#!/usr/bin/env python3
"""情境处理引擎 · context_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · NOA-008 补充1
自动识别项目归属、新建/延续判断、情境路由
"""

import json
import httpx
from pathlib import Path
from datetime import datetime

PRIME_ROOT = Path(__file__).parent
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = "sk-your-deepseek-api-key"


class ContextEngine:
    """情境引擎——你只管说话，它自动判断上下文"""

    def __init__(self):
        self.active_project: str | None = None
        self.project_list: list = self._scan_projects()

    def _scan_projects(self) -> list:
        """扫描已有项目"""
        projects = []
        proj_dir = PRIME_ROOT / "data" / "projects"
        if proj_dir.exists():
            for d in proj_dir.iterdir():
                if d.is_dir() and (d / "project.toml").exists():
                    projects.append({
                        "name": d.name,
                        "path": str(d),
                        "last_active": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    })
        return projects

    def analyze(self, user_input: str) -> dict:
        """分析输入，返回情境判断"""
        self.project_list = self._scan_projects()

        # 规则层: 明确指向
        for proj in self.project_list:
            name = proj["name"]
            if name in user_input or name.replace("-", "") in user_input.replace(" ", ""):
                return {
                    "context": "continue_project",
                    "project": name,
                    "confidence": 0.95,
                    "message": f"继续「{name}」",
                }

        # 新建意图检测 (规则)
        create_words = ["新建", "创建", "开始写", "新项目", "开一个", "帮我建"]
        if any(w in user_input for w in create_words):
            return {
                "context": "new_project",
                "project": None,
                "confidence": 0.85,
                "message": "检测到新建项目意图",
            }

        # 闲聊检测
        chat_words = ["好累", "哈哈", "嗯", "哦", "谢谢", "今天", "天气", "晚安", "早安"]
        if len(user_input) < 15 and any(w in user_input for w in chat_words):
            return {
                "context": "chat",
                "project": None,
                "confidence": 0.80,
                "message": "闲聊模式",
            }

        # 语义层: 4B理解"那个备份脚本"指代哪个项目
        if self.project_list and len(user_input) > 5:
            result = self._semantic_match_4b(user_input)
            if result and result.get("confidence", 0) >= 0.50:
                return result

        return {
            "context": "new_conversation",
            "project": None,
            "confidence": 0.50,
            "message": "新对话",
        }

    def _semantic_match_4b(self, user_input: str) -> dict:
        """4B模型语义匹配——理解无项目名的模糊指代"""
        if not self.project_list:
            return None

        projects_desc = "\n".join(
            f"- {p['name']} (关键词: {p['name'].replace('_',' ').replace('-',' ')}, 类型:{'创作' if 'novel' in p.get('name','') else '技术'})"
            for p in self.project_list[:5]
        )
        prompt = (
            f"用户说: {user_input[:200]}\n"
            f"已有项目(注意根据语义判断，不要求精确匹配项目名):\n{projects_desc}\n"
            f"请根据语义判断用户是否在指代已有项目。例如'那个备份'可能指代名含backup的项目。\n"
            f"输出严格JSON: "
            f'{{"match": true/false, "project_name": "匹配到的项目名或null", '
            f'"confidence": 0.0-1.0}}\n只输出JSON:'
        )
        try:
            r = httpx.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": 120,
                    "temperature": 0.2,
                },
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                raw = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                start = raw.find("{")
                end = raw.rfind("}") + 1
                if start >= 0:
                    data = json.loads(raw[start:end])
                    if data.get("match") and data.get("project_name"):
                        return {
                            "context": "continue_project",
                            "project": data["project_name"],
                            "confidence": data.get("confidence", 0.55),
                            "message": f"语义匹配「{data['project_name']}」",
                        }
        except Exception:
            pass
        return None

    def create_project(self, name: str, ptype: str = "general") -> dict:
        """自动创建项目"""
        proj_dir = PRIME_ROOT / "data" / "projects" / name
        proj_dir.mkdir(parents=True, exist_ok=True)

        import toml
        config = {
            "name": name,
            "type": ptype,
            "created_at": datetime.now().isoformat(),
            "status": "active",
        }
        with open(proj_dir / "project.toml", "w") as f:
            toml.dump(config, f)

        (proj_dir / "context.json").write_text("{}")
        (proj_dir / "rules.md").write_text(
            f"# {name}\n\n项目类型: {ptype}\n创建时间: {datetime.now().strftime('%Y-%m-%d')}\n"
        )

        self.active_project = name
        self.project_list = self._scan_projects()
        return {"status": "created", "name": name, "type": ptype, "path": str(proj_dir)}


# 全局实例
ctx = ContextEngine()
