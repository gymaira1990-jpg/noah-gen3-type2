#!/usr/bin/env python3
"""原铸诺亚 · 环境隔离墙

确保 原铸 和 诺亚(Hermes) 是互不干扰的同级体。

边界规则:
  原铸可写:  ~/noah-prime/        (配置/记忆/日志/数据)
  原铸可读:  ~/noah-档案馆/       (知识共享, 只读)
             ~/noah-prime/        (自有)
  原铸禁止:  ~/.hermes/           (Hermes Agent 本体)
             ~/.hermes/*          (配置/技能/脚本)
             ~/nep-core/          (项目管理)
             系统文件 (sudo/apt/...)

进程隔离:
  原铸进程:  start.py → noah_terminal.py / uvicorn
  限定:     只能访问 prime-noah:4b 模型
  禁止:     操作 hermes 进程、修改 ~/.hermes/

网络隔离:
  Web UI:   127.0.0.1:8888 (仅本地)
  API调用:  仅 Ollama localhost:11434
  禁止:     公网暴露服务端口

启动验证:
  python3 ~/noah-prime/start.py --cli    # CLI 模式
  python3 ~/noah-prime/start.py --web    # Web UI 模式
"""

import os, sys, subprocess
from pathlib import Path

PRIME = Path.home() / "noah-prime"


def verify_isolation():
    """验证隔离墙有效性"""
    checks = []
    print("🔍 原铸环境隔离验证\n")

    # 1. 禁止路径检查
    forbidden = [
        (".hermes", "Hermes Agent 配置"),
        (".hermes/config.yaml", "Hermes 配置"),
        (".hermes/skills", "Hermes 技能"),
        ("nep-core", "项目管理"),
    ]
    for rel, desc in forbidden:
        p = Path.home() / rel
        can_write = os.access(str(p), os.W_OK) if p.exists() else "n/a"
        msg = f"  {'✅' if can_write == 'n/a' or not can_write else '❌'} 禁止写入 {desc}: {rel}"
        checks.append(msg)
        print(msg)

    # 2. 允许路径检查
    allowed = [
        ("noah-prime/data", "数据目录"),
        ("noah-prime/memory", "记忆目录"),
        ("noah-prime/logs", "日志目录"),
        ("noah-prime/config", "配置目录"),
    ]
    for rel, desc in allowed:
        p = PRIME / rel
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        can_write = os.access(str(p), os.W_OK)
        msg = f"  {'✅' if can_write else '❌'} 可写入 {desc}: {rel}"
        checks.append(msg)
        print(msg)

    # 3. 只读共享路径
    archive = Path.home() / "noah-档案馆"
    if archive.exists():
        can_read = os.access(str(archive), os.R_OK)
        can_write = os.access(str(archive), os.W_OK)
        msg = f"  {'✅' if can_read else '❌'} 档案只读: noah-档案馆 (读{can_read} 写{can_write})"
        checks.append(msg)
        print(msg)

    print()
    print(f"共 {len(checks)} 项检查完成")
    return checks


def enforce_environment():
    """设置环境变量，限制进程行为"""
    # 禁止 proxy 污染
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"]:
        os.environ.pop(var, None)

    # 清理 PYTHONPATH 中的 Hermes 路径
    pp = os.environ.get("PYTHONPATH", "")
    hermes_path = str(Path.home() / ".hermes")
    clean = [p for p in pp.split(":") if hermes_path not in p]
    os.environ["PYTHONPATH"] = ":".join(clean)

    # 设置原铸工作根
    os.environ["PRIME_ROOT"] = str(PRIME)


if __name__ == "__main__":
    verify_isolation()
