"""诺亚核心 · CLI
所有 cmd_* + main 命令调度
"""

import os, sys, json, shutil, subprocess, re
from pathlib import Path

from .kernel import load_config, save_config, create_default_config, ModelConfig, CONFIG_DIR, CONFIG_FILE
from .models import add_model, remove_model, get_model
from .health import check_model_health, check_all_models
from .chat import chat_completion
from .discovery import discover_ollama_models, discover_llamacpp_models, search_hf_models, pull_hf_model, pull_ollama_model
from .dashboard import build_dashboard, render_dashboard_text


def print_help():
    print("""\n  ══════════════════════════════════════════════
  诺亚核心 · 模型管理 CLI
  ══════════════════════════════════════════════
  初始化 · 配置:
    init                     创建默认配置
    list                     列出所有模型
    status                   仪表盘状态
    show <name>              单个模型信息
    add                      交互式添加
    edit <name>              交互式编辑
    remove <name>            删除模型
    test <name>              测试连通性

  发现 · 下载:
    discover                 扫描本地模型
    search <关键词>           搜索 HF GGUF
    pull hf:<repo>           下载 HF 模型
    pull ollama:<name>       下载 Ollama 模型

  对话 · Web:
    chat <name>              CLI 对话
    serve                    启动 Web 面板
  """)


def cmd_init():
    if CONFIG_FILE.exists():
        r = input("  ⚠️  配置已存在. 覆盖? (y/N): ").strip().lower()
        if r != "y":
            return print("  取消")
    cfg = create_default_config()
    print(f"  ✅ 已创建: {CONFIG_FILE}")
    print(f"  模型: {', '.join(m.name for m in cfg.models)}")


def cmd_list():
    cfg = load_config()
    if not cfg.models:
        return print("  ⚠️  没有模型. 运行 `python -m core init`")
    results = check_all_models(cfg.models)
    h = f"  {'显示名称':<18} {'真实名称':<20} {'MOD名字':<20} {'提供商':<8} {'温度':<6} {'max_tok':<8} {'状态':<20}"
    print(f"\n{h}")
    print(f"  {'─'*100}")
    for m, s in zip(cfg.models, results):
        key_ok = "✅" if (m.api_key_env and os.environ.get(m.api_key_env)) else "⚠️" if m.api_key_env else " -"
        print(f"  {m.name:<18} {(m.real_name or '-'):<20} {m.model_id:<20} {m.provider:<8} {m.temperature:<6} {m.max_tokens:<8} {s.status_emoji} {s.status_text[:18]:<18}")
    print()


def cmd_status():
    print(render_dashboard_text(build_dashboard()))


def cmd_add():
    cfg = load_config()
    print("\n  添加模型 (所有字段回车=跳过使用默认)")
    print(f"  {'─'*50}")
    print("  ── 基础信息 ──")
    name = input("  ① 显示名称 [必填]: ").strip()
    if not name: return
    real_name = input(f"  ② 真实名称 [{name}]: ").strip() or name
    model_id = input(f"  ③ MOD名字 (API请求ID) [{name}]: ").strip() or name
    provider = input("  ④ 提供商 [openai/ollama] (openai): ").strip() or "openai"
    api_base = input("  ⑤ API地址 [必填]: ").strip()
    if not api_base: return
    api_key_env = input("  ⑥ API Key环境变量名 (可选): ").strip() or None
    mtype = input("  ⑦ 类型 [api/local] (api): ").strip() or "api"
    print(f"\n  ── 参数 ──")
    temp_str = input(f"  ⑧ 温度 [{0.7}]: ").strip()
    temperature = float(temp_str) if temp_str else 0.7
    mt_str = input(f"  ⑨ 最大Token [{4096}]: ").strip()
    max_tokens = int(mt_str) if mt_str else 4096
    print(f"\n  ── 说明 ──")
    desc = input(f"  ⑩ 描述 (可选): ").strip() or ""
    notes = input(f"  ⑪ 备注 (可选): ").strip() or ""
    model = ModelConfig(name=name, real_name=real_name, model_id=model_id,
        provider=provider, api_base=api_base, api_key_env=api_key_env,
        type=mtype, temperature=temperature, max_tokens=max_tokens,
        description=desc, notes=notes)
    add_model(cfg, model)
    print(f"\n  ✅ 已添加: {name}")


def cmd_remove(name: str):
    cfg = load_config()
    if remove_model(cfg, name):
        print(f"  ✅ 已删除: {name}")
    else:
        print(f"  ⚠️  不存在: {name}")
        if cfg.models:
            print(f"  现有: {', '.join(m.name for m in cfg.models)}")


def cmd_test(name: str):
    cfg = load_config()
    model = get_model(cfg, name)
    if not model: return print(f"  ⚠️  不存在: {name}")
    print(f"  测试 {name} ...")
    status = check_model_health(model)
    print(f"  {status.status_emoji} {status.status_text}")


def cmd_chat(name: str):
    cfg = load_config()
    model = get_model(cfg, name)
    if not model: return print(f"  ⚠️  不存在: {name}")
    print(f"\n  💬 对话: {name} [{model.provider}/{model.model_id}]")
    if model.real_name: print(f"     {model.real_name}")
    if model.description: print(f"     {model.description}")
    if model.notes: print(f"     📝 {model.notes}")
    print()
    msgs = []
    while True:
        try:
            text = input("  >> ").strip()
        except (EOFError, KeyboardInterrupt):
            return print("\n  再见")
        if text.lower() in ("/exit", "/q"):
            return print("  再见")
        if text.lower() == "/clear":
            msgs = []; print("  已清空"); continue
        msgs.append({"role": "user", "content": text})
        result = chat_completion(model, msgs)
        if result["error"]:
            print(f"  🔴 {result['error']}")
            msgs.pop()
        else:
            print(f"  [{name}] {result['text']}\n")
            msgs.append({"role": "assistant", "content": result["text"]})


def cmd_show(name: str):
    cfg = load_config()
    m = get_model(cfg, name)
    if not m: return print(f"  ⚠️  不存在: {name}")
    s = check_model_health(m)
    key_status = "✅ 已配置" if (m.api_key_env and os.environ.get(m.api_key_env)) else "⚠️ 未配置" if m.api_key_env else "-"
    print(f"\n  {'═'*56}")
    print(f"  模型: {m.name}")
    print(f"  {'═'*56}")
    print(f"  真实名称:   {m.real_name or '-'}")
    print(f"  MOD名字:    {m.model_id}")
    print(f"  提供商:     {m.provider} · {m.type}")
    print(f"  API地址:    {m.api_base}")
    print(f"  KEY:        {m.api_key_env or '-'} {key_status}")
    print(f"  温度:       {m.temperature}")
    print(f"  最大Token:  {m.max_tokens}")
    if m.description: print(f"  描述:       {m.description}")
    if m.notes: print(f"  备注:       {m.notes}")
    print(f"  {'─'*56}")
    print(f"  状态:       {s.status_emoji} {s.status_text}")
    print(f"  {'═'*56}\n")


def cmd_discover():
    """发现已有模型: Ollama / llama.cpp"""
    cfg = load_config()

    # Ollama
    if shutil.which("ollama"):
        print("\n  🔍 扫描 Ollama 本地模型 (http://localhost:11434)...")
        local_models = discover_ollama_models()
        if local_models:
            print(f"    发现 {len(local_models)} 个本地模型:\n")
            for i, lm in enumerate(local_models, 1):
                size_str = f"{lm['size']/1024/1024/1024:.1f}GB" if lm['size'] else "?"
                print(f"    [{i}] {lm['id']:<30} {lm['parameter_size']:<8} {lm['quantization']:<8} {size_str}")
            sel = input("\n  选择添加 (编号逗号 / a=全选 / q=跳过): ").strip().lower()
            if sel and sel != "q":
                indices = []
                if sel == "a":
                    indices = list(range(len(local_models)))
                else:
                    for p in sel.split(","):
                        p = p.strip()
                        if p.isdigit():
                            idx = int(p) - 1
                            if 0 <= idx < len(local_models):
                                indices.append(idx)
                added = 0
                for idx in indices:
                    lm = local_models[idx]
                    display_name = input(f"    显示名称 [{lm['id']}]: ").strip() or lm['id']
                    notes = input(f"    备注 (可选): ").strip() or ""
                    m = ModelConfig(
                        name=display_name,
                        real_name=lm.get("real_name", lm["id"]),
                        model_id=lm["id"].split(":")[0] if ":" in lm["id"] else lm["id"],
                        provider="ollama",
                        api_base="http://localhost:11434",
                        type="local",
                        description=f"Ollama · {lm.get('parameter_size', '')} {lm.get('quantization', '')}".strip(),
                        notes=notes,
                    )
                    if get_model(cfg, m.name):
                        print(f"    ⚠️  '{m.name}' 已存在, 跳过")
                    else:
                        add_model(cfg, m)
                        added += 1
                print(f"    ✅ 已添加 {added} 个模型")
        else:
            print("    ⚠️  Ollama 未运行或无模型")

    # llama.cpp
    print("\n  🔍 扫描 llama.cpp 本地端口...")
    llama_models, llama_ports = discover_llamacpp_models()
    if llama_models:
        print(f"    发现 {len(llama_models)} 个 llama.cpp 模型 (端口 {', '.join(str(p) for p in llama_ports)}):\n")
        for i, lm in enumerate(llama_models, 1):
            cap_label = {"chat": "💬", "embedding": "📐", "reranker": "📊", "vision": "👁️"}.get(lm.get("capability", "chat"), "?")
            print(f"    [{i}] {cap_label} {lm['id']:<35} port:{lm['port']}")
        sel = input("\n  选择添加 (编号逗号 / a=全选 / q=跳过): ").strip().lower()
        if sel and sel != "q":
            indices = []
            if sel == "a":
                indices = list(range(len(llama_models)))
            else:
                for p in sel.split(","):
                    p = p.strip()
                    if p.isdigit():
                        idx = int(p) - 1
                        if 0 <= idx < len(llama_models):
                            indices.append(idx)
            added = 0
            for idx in indices:
                lm = llama_models[idx]
                display_name = input(f"    显示名称 [{lm['id']}]: ").strip() or lm['id']
                notes = input(f"    备注 (可选): ").strip() or ""
                cap = lm.get("capability", "chat")
                m = ModelConfig(
                    name=display_name,
                    real_name=lm.get("real_name", lm["id"]),
                    model_id=lm["id"],
                    provider="llamacpp",
                    api_base=lm.get("api_base", f"http://localhost:{lm['port']}"),
                    type="local",
                    description=f"llama.cpp · {cap}",
                    notes=notes,
                )
                if get_model(cfg, m.name):
                    print(f"    ⚠️  '{m.name}' 已存在, 跳过")
                else:
                    add_model(cfg, m)
                    added += 1
            print(f"    ✅ 已添加 {added} 个模型")
    else:
        print("    ⚠️  未发现运行的 llama.cpp 服务")


def cmd_search():
    if len(sys.argv) < 3:
        return print("  usage: arc search <关键词>")
    query = " ".join(sys.argv[2:])
    print(f"\n  🔍 搜索 HuggingFace GGUF: {query}")
    results = search_hf_models(query)
    if not results:
        return print("  ⚠️  未找到结果")
    print(f"\n    找到 {len(results)} 个模型:\n")
    for i, r in enumerate(results, 1):
        dls = f"{r['downloads']/1000/1000:.1f}M" if r['downloads'] else "?"
        print(f"    [{i}] {r['id']:<60} ⬇️ {dls}")
    print("\n    用法: arc pull hf:<repo_id>")


def cmd_pull():
    if len(sys.argv) < 3:
        return print("  usage: arc pull hf:<repo_id> / ollama:<name>")
    arg = sys.argv[2]
    if arg.startswith("hf:"):
        repo_id = arg[3:]
        print(f"\n  ⬇️  下载: {repo_id}")
        result = pull_hf_model(repo_id)
        if result["success"]:
            print(f"  ✅ 下载完成: {result['path']}")
        else:
            print(f"  🔴 {result['error']}")
            if "url" in result:
                print(f"  手动: {result['url']}")
    elif arg.startswith("ollama:"):
        name = arg[7:]
        print(f"\n  ⬇️  下载: {name}")
        result = pull_ollama_model(name)
        if result["success"]:
            print(f"  ✅ 下载完成: {result['path']}")
        else:
            print(f"  🔴 {result['error']}")


def cmd_edit(name: str):
    cfg = load_config()
    m = get_model(cfg, name)
    if not m: return print(f"  ⚠️  不存在: {name}")
    print(f"\n  编辑模型: {name} (回车保持原值)\n")
    name_new = input(f"  显示名称 [{m.name}]: ").strip() or m.name
    m.real_name = input(f"  真实名称 [{m.real_name}]: ").strip() or m.real_name
    m.model_id = input(f"  MOD名字 [{m.model_id}]: ").strip() or m.model_id
    m.provider = input(f"  提供商 [{m.provider}]: ").strip() or m.provider
    m.api_base = input(f"  API地址 [{m.api_base}]: ").strip() or m.api_base
    key_str = input(f"  KEY环境变量 [{m.api_key_env or ''}]: ").strip()
    m.api_key_env = key_str if key_str else m.api_key_env
    m.type = input(f"  类型 [{m.type}]: ").strip() or m.type
    temp_str = input(f"  温度 [{m.temperature}]: ").strip()
    if temp_str: m.temperature = float(temp_str)
    mt_str = input(f"  最大Token [{m.max_tokens}]: ").strip()
    if mt_str: m.max_tokens = int(mt_str)
    m.description = input(f"  描述 [{m.description or ''}]: ").strip() or m.description
    m.notes = input(f"  备注 [{m.notes or ''}]: ").strip() or m.notes
    if name_new != m.name:
        remove_model(cfg, name)
        m.name = name_new
    add_model(cfg, m)
    print(f"\n  ✅ 已更新: {m.name}")


def cmd_serve():
    print("  启动 Web 面板...")
    try:
        from .server import start_server
        start_server()
    except ImportError as e:
        return print(f"  ❌ 需要安装: pip install fastapi uvicorn  ({e})")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h"):
        return print_help()
    cmd = sys.argv[1]
    cmds = {
        "init": cmd_init,
        "list": cmd_list,
        "status": cmd_status,
        "show": lambda: cmd_show(sys.argv[2]) if len(sys.argv) >= 3 else print("  usage: arc show <name>"),
        "add": cmd_add,
        "edit": lambda: cmd_edit(sys.argv[2]) if len(sys.argv) >= 3 else print("  usage: arc edit <name>"),
        "remove": lambda: cmd_remove(sys.argv[2]) if len(sys.argv) >= 3 else print("  usage: arc remove <name>"),
        "test": lambda: cmd_test(sys.argv[2]) if len(sys.argv) >= 3 else print("  usage: arc test <name>"),
        "chat": lambda: cmd_chat(sys.argv[2]) if len(sys.argv) >= 3 else print("  usage: arc chat <name>"),
        "serve": cmd_serve,
        "discover": cmd_discover,
        "search": cmd_search,
        "pull": cmd_pull,
    }
    fn = cmds.get(cmd)
    if fn:
        fn()
    else:
        print(f"  未知命令: {cmd}")
        print_help()


if __name__ == "__main__":
    main()
