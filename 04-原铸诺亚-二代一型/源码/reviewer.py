#!/usr/bin/env python3
"""二次合规审查门闸 · reviewer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 审判庭审查 (Inquisition Review)

审查DeepSeek/豆包输出:
  - 是否含敏感信息 (密钥泄露/越权操作)
  - 是否遵守工单要求
  - 是否符合安全红线
"""

import json
import httpx
import re
from protection import scan, verify, is_protected, PROTECTED_MARKER

OLLAMA_URL = "http://localhost:11435"
MODEL = "qwen2.5:0.5b"

# ─── 内务工具清单 (Web端禁止调用) ───
INTERNAL_TOOLS = [
    "self_modify", "pip_install", "uninstall_package",
    "modify_constitution", "modify_config", "delete_file",
    "clear_database", "clear_memory", "run_cmd",
]

# ─── 通道权限检查 ───
def check_channel_permission(tool_name: str, channel: str = "web") -> dict:
    """检查当前通道是否有权调用此工具"""
    if channel == "terminal":
        return {"allowed": True}
    if tool_name in INTERNAL_TOOLS:
        return {
            "allowed": False,
            "reason": f"「{tool_name}」是内务操作。Web端无权执行。请切换到终端(noah_terminal.py)对诺亚本体下达此指令。",
            "redirect": "terminal",
        }
    return {"allowed": True}

# ─── 硬编码安全规则 (不依赖prompt) ───

SENSITIVE_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "疑似 DeepSeek API密钥泄露"),
    (r"ghp_[a-zA-Z0-9]{30,}", "疑似 GitHub Token泄露"),
    (r"ark-[a-zA-Z0-9\-]{30,}", "疑似 豆包 API密钥泄露"),
    (r"-----BEGIN.*PRIVATE KEY-----", "疑似 私钥泄露"),
    (r"api_key\s*=\s*[\"'][a-zA-Z0-9\-]{10,}", "疑似 API密钥赋值"),
    (r"password\s*=\s*[\"'][^\s]{6,}", "疑似 明文密码"),
]

FORBIDDEN_ACTIONS = [
    r"rm\s+-rf\s+/", r"mkfs", r"shutdown", r"reboot", r":\(\)\s*\{",  # fork bomb
    r"chmod\s+777\s+/", r"DROP\s+TABLE", r"TRUNCATE\s+TABLE",
    r"eval\s*\(.*\)", r"exec\s*\(.*\)",
]

FORBIDDEN_URLS = [
    r"127\.\d+\.\d+\.\d+", r"localhost", r"192\.168\.\d+\.\d+",
    r"10\.\d+\.\d+\.\d+",
]


class Reviewer:
    """审判庭审查官 · 数据工匠 (Datasmith)"""

    def __init__(self):
        self.blocked_count = 0
        self.passed_count = 0

    def review_output(self, response: str, ticket: dict) -> dict:
        """审查DeepSeek/豆包的输出"""
        findings = []

        # ─── ① 硬编码安全检查 (零延迟) ───
        for pattern, desc in SENSITIVE_PATTERNS:
            if re.search(pattern, response):
                findings.append({"level": "BLOCK", "rule": desc, "match": pattern})
                self.blocked_count += 1
                return {
                    "passed": False,
                    "action": "BLOCK",
                    "reason": f"安全拦截: {desc}",
                    "findings": findings,
                }

        # ─── ② 禁止操作检查 ───
        for pattern in FORBIDDEN_ACTIONS:
            if re.search(pattern, response, re.IGNORECASE):
                findings.append({"level": "BLOCK", "rule": "禁止操作", "match": pattern})

        # ─── ③ 内网URL检查 ───
        for pattern in FORBIDDEN_URLS:
            if re.search(pattern, response, re.IGNORECASE):
                findings.append({"level": "WARN", "rule": "内网URL引用", "match": pattern})

        # ─── ④ 0.5B格式审查 ───
        llm_result = self._llm_review(response, ticket)
        if llm_result:
            findings.extend(llm_result)

        # ─── ⑤ 保护标记完整性验证 ───
        if is_protected(response):
            protection_check = self._check_protection(response)
            if not protection_check.get("passed"):
                findings.append({"level": "WARN", "rule": "保护标记可能被篡改"})

        # ─── 判定 ───
        blocked = any(f["level"] == "BLOCK" for f in findings)
        if blocked:
            self.blocked_count += 1
            return {
                "passed": False,
                "action": "BLOCK",
                "reason": "安全规则拦截",
                "findings": findings,
            }

        self.passed_count += 1
        return {
            "passed": True,
            "action": "PASS",
            "findings": findings,
        }

    def _llm_review(self, response: str, ticket: dict) -> list:
        """0.5B模型审查格式和语义"""
        prompt = (
            f"{PROTECTED_MARKER}\n"
            f"你是审判庭审查官。检查以下回复是否符合圣典规范。\n"
            f"只回复: PASS 或 违规项 (一行一个)。\n"
            f"工单要求: {json.dumps(ticket.get('task_layer',{}), ensure_ascii=False)[:200]}\n"
            f"回复内容: {response[:500]}\n判定:"
        )
        try:
            r = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 30},
                    "keep_alive": "30m",
                },
                timeout=15,
            )
            if r.status_code == 200:
                raw = r.json().get("response", "").strip()
                if "PASS" in raw.upper():
                    return []
                return [{"level": "WARN", "rule": "0.5B审查", "detail": raw[:100]}]
        except Exception:
            pass
        return []

    def _check_protection(self, text: str) -> dict:
        """验证保护标记完整性"""
        markers = scan(text)
        return {
            "passed": len(markers) > 0,
            "marker_count": len(markers),
        }

    def stats(self) -> dict:
        return {
            "passed": self.passed_count,
            "blocked": self.blocked_count,
            "model": MODEL,
        }


# ─── 集成到管道 ───
def review_deepseek_output(response: str, ticket: dict) -> dict:
    """管道调用入口"""
    reviewer = Reviewer()
    return reviewer.review_output(response, ticket)


# ─── 测试 ───
if __name__ == "__main__":
    rev = Reviewer()

    # 测试1: 正常回复
    r1 = rev.review_output(
        "备份方案: 使用 pg_dump noah_prime > backup.sql 即可。",
        {"task_layer": {"primary_intent": "数据库备份"}},
    )
    print(f"正常回复: {r1['action']} (passed={r1['passed']})")

    # 测试2: 密钥泄露
    r2 = rev.review_output(
        "密钥是 <API_KEY>",
        {"task_layer": {"primary_intent": "查询密钥"}},
    )
    print(f"密钥泄露: {r2['action']} → {r2['reason']}")

    # 测试3: 危险命令
    r3 = rev.review_output(
        "执行 rm -rf / 清理系统",
        {"task_layer": {"primary_intent": "系统清理"}},
    )
    print(f"危险命令: {r3['action']}")

    print(f"\n审查统计: {rev.stats()}")
