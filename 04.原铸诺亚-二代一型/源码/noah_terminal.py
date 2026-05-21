#!/usr/bin/env python3
"""诺亚·原初 · 终端管理员通道
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
虫族母巢 · 诺亚本体
只有铸造官(GCAT)能通过此通道与诺亚核心直接对话。
拥有全部权限——包括修改诺亚自身代码和配置。

启动: python3 noah_terminal.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import os
from pathlib import Path

PRIME_ROOT = Path(__file__).parent
sys.path.insert(0, str(PRIME_ROOT))

# 密钥加载
try:
    from vault.loader import load_all
    load_all()
except Exception:
    pass

from noah_pipeline import NoahPipeline
from persona import PersonaFilter
from context_engine import ctx
from init_system import run_all_checks, print_report


class TerminalSession:
    """诺亚本体 · 管理员对话会话"""

    def __init__(self):
        self.pipeline = NoahPipeline(channel="terminal")
        self.persona = PersonaFilter("magos")  # 铸造大贤者风格
        self.running = True
        self.mode = "admin"  # 管理员模式·全部权限
        print("=" * 52)
        print("  ⚙ 诺亚·原初 · 核心终端")
        print("  虫族母巢 · 管理员通道")
        print("=" * 52)
        print()
        print("  铸造官，你已直连诺亚本体。")
        print("  在此模式下，诺亚拥有完整权限——")
        print("  可修改代码、更新配置、自我迭代。")
        print()
        print("  输入 'exit' 退出  |  'status' 状态  |  'help' 帮助")
        print("-" * 52)

    def run(self):
        while self.running:
            try:
                user_input = input("\n⚙ 铸造官> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n  诺亚本体进入休眠。万机之神见证。")
                break

            if not user_input:
                continue

            # 特殊命令
            if user_input.lower() in ("exit", "quit", "退出"):
                print("  诺亚本体进入休眠。")
                break

            if user_input.lower() == "status":
                self._show_status()
                continue

            if user_input.lower() == "help":
                self._show_help()
                continue

            if user_input.lower().startswith("self "):
                self._self_modify(user_input[5:])
                continue

            # 正常对话
            self._process(user_input)

    def _process(self, text: str):
        print("  ⚙ 诺亚思考中...")
        try:
            result = self.pipeline.process(text)
            reply = self.persona.apply(result.get("reply", "铸造圣殿静默"))
            print(f"\n  {reply}")
            if result.get("tokens_used"):
                print(f"  [Token: {result['tokens_used']} | 状态: {result.get('state','?')}]")
        except Exception as e:
            print(f"\n  ❌ 管道异常: {e}")

    def _show_status(self):
        results = run_all_checks()
        print_report(results)

    def _show_help(self):
        print("""
  终端命令:
    exit / quit    退出
    status         系统自检
    help           帮助
    self <指令>     自我迭代(修改诺亚自身代码)

  你可以说的话:
    "帮我在noah_pipeline.py里加一个日志打印"
    "把constitution.yaml的threshold改成0.9"
    "创建一个新的工具函数"
    "检查系统健康状态"
    "备份数据库"
    "同步到远征堡垒"

  Web端做不到的事(终端可以做):
    ✅ 修改诺亚自身代码
    ✅ 更新系统配置
    ✅ 升级模型
    ✅ 执行self_modify
    ✅ 修改constitution.yaml
    ✅ 安装/卸载Python包
""")

    def _self_modify(self, instruction: str):
        print(f"  ⚙ 收到自我迭代指令: {instruction}")
        print("  ◆ 此操作将修改诺亚自身代码。")
        confirm = input("  确认执行? (输入 '确认' 继续): ").strip()
        if confirm != "确认":
            print("  已取消。")
            return
        print("  ⚙ 启动迭代流程...")
        self._process(f"你是诺亚本体。请用self_modify工具执行以下操作: {instruction}")


if __name__ == "__main__":
    session = TerminalSession()
    session.run()
