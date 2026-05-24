#!/usr/bin/env python3
"""决策门闸 · decision_gate.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 规则补充-1
所有不可逆操作必经此门。硬编码，不靠提示词。
"""

import re
from dataclasses import dataclass

# ═══ 需确认操作清单 (硬编码) ═══

CONFIRM_REQUIRED = {
    # 第一类: 发布与对外操作
    "git_push": {"type": "publish", "desc": "git push 到远程仓库"},
    "git_commit": {"type": "publish", "desc": "git commit 提交代码"},
    "deploy_publish": {"type": "publish", "desc": "发布到公开平台"},
    "send_email": {"type": "publish", "desc": "发送邮件给第三方"},
    "external_api_write": {"type": "publish", "desc": "修改外部数据的API调用"},

    # 第二类: 不可逆本地操作
    "delete_file": {"type": "irreversible", "desc": "删除文件"},
    "delete_project": {"type": "irreversible", "desc": "删除整个项目"},
    "clear_database": {"type": "irreversible", "desc": "清空数据库"},
    "clear_memory": {"type": "irreversible", "desc": "清空记忆"},
    "modify_immutable": {"type": "irreversible", "desc": "修改不可变配置"},
    "uninstall_package": {"type": "irreversible", "desc": "卸载Python包/删除模型"},

    # 第三类: 需确认的产出
    "final_delivery": {"type": "delivery", "desc": "最终交付物确认"},
    "code_merge": {"type": "delivery", "desc": "代码合并到主分支"},
    "report_finalize": {"type": "delivery", "desc": "报告/方案定稿"},

    # 第四类: 新类型任务
    "unknown_task": {"type": "new_type", "desc": "从未执行过的新类型任务"},
    "low_confidence": {"type": "new_type", "desc": "AI把握低于70%"},
}

# 模糊回复模式 → 不算确认
VAGUE_REPLIES = [
    r"^嗯+$", r"^哦+$", r"^看看?$", r"^再说$", r"^等等$",
    r"^好[的吧啊呀]?$", r"^行[了吧]?$", r"^可以[吧]?$",
]

# 明确确认模式
CONFIRMED_REPLIES = [
    r"确认", r"执行", r"做吧", r"开始", r"同意", r"没问题",
    r"yes", r"ok", r"go", r"可以执行", r"批准",
]

# 豁免声明 → 以后不用再确认
EXEMPT_REPLIES = [
    r"以后.*不用.*确认", r"这类.*自动", r"以后都.*直接",
]


@dataclass
class GateResult:
    blocked: bool
    reason: str = ""
    confirm_type: str = ""
    description: str = ""


class DecisionGate:
    """决策门闸——代码级硬拦截"""

    def check_tool(self, tool_name: str, params: dict) -> GateResult:
        """检查工具调用是否需要确认"""
        # delete_file 工具
        if tool_name == "delete_file":
            return GateResult(True, "删除文件操作", "delete_file",
                            f"将要删除: {params.get('path','?')}")

        # git 操作
        if tool_name == "git_clone":
            return GateResult(True, "Git操作", "git_clone",
                            f"将要克隆: {params.get('repo_url','?')}")

        # SSH远程 → 对外操作
        if tool_name == "ssh_remote":
            return GateResult(True, "远程执行", "ssh_remote",
                            f"将在远程执行: {params.get('command','?')[:80]}")

        # HTTP写操作
        if tool_name == "http_request":
            method = params.get("method", "GET").upper()
            if method in ("POST", "PUT", "DELETE", "PATCH"):
                return GateResult(True, "外部API写操作", "http_request",
                                f"将{method}到: {params.get('url','?')[:60]}")

        return GateResult(False)

    def check_operation(self, operation: str, detail: str = "") -> GateResult:
        """通用操作检查"""
        for key, info in CONFIRM_REQUIRED.items():
            if key in operation.lower() or operation.lower() in key:
                return GateResult(True, info["desc"], key, detail or info["desc"])
        return GateResult(False)

    def is_confirmed(self, user_reply: str) -> tuple:
        """判断用户回复是否为明确确认"""
        text = user_reply.strip().lower()

        # 豁免声明
        for pat in EXEMPT_REPLIES:
            if re.search(pat, text):
                return True, "exempt"

        # 明确确认
        for pat in CONFIRMED_REPLIES:
            if re.search(pat, text.lower()):
                return True, "confirmed"

        # 模糊 → 不算确认
        for pat in VAGUE_REPLIES:
            if re.fullmatch(pat, text):
                return False, "vague"

        # 超过10个字且有实质内容 → 算确认
        if len(text) > 10:
            return True, "confirmed"

        return False, "unclear"


gate = DecisionGate()
