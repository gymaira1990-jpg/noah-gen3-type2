#!/usr/bin/env python3
"""工具注册表 + 安全壳 · tools/registry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOAH-PRIME · 原初铸造世界
战锤40K主题: 铸造圣殿工具库

参照 诺亚生命计划 · 第二阶段设计:
  所有工具必须在此注册，未注册的工具无法被工单执行阶段调用。
  安全规则硬编码在函数体内，不依赖prompt。
"""

import os
import re
import time
import subprocess
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Callable, Optional

PRIME_ROOT = Path(__file__).parent.parent

# ═══════════════════════════════════════
# 工具注册表
# ═══════════════════════════════════════

TOOL_REGISTRY = {}


def register(name: str, func: Callable, category: str, description: str, requires_review: bool = True):
    TOOL_REGISTRY[name] = {
        "func": func,
        "category": category,
        "description": description,
        "requires_review": requires_review,
        "enabled": True,
    }


def get_tool(name: str) -> Callable:
    tool = TOOL_REGISTRY.get(name)
    if not tool or not tool["enabled"]:
        raise ValueError(f"工具 {name} 不存在或已禁用")
    return tool["func"]


def list_tools(category: str = None) -> dict:
    if category:
        return {k: v for k, v in TOOL_REGISTRY.items() if v["category"] == category}
    return TOOL_REGISTRY


# ═══════════════════════════════════════
# 安全模块 — 硬编码在函数体内
# ═══════════════════════════════════════

SAFE_DIRS = [
    str(PRIME_ROOT / "data"),
    str(PRIME_ROOT / "logs"),
    str(PRIME_ROOT / "tools"),
    str(PRIME_ROOT / "brain"),
    str(PRIME_ROOT / "memory"),
    str(PRIME_ROOT / "web"),
    str(Path.home() / "noah-prime"),
]


def is_safe_path(path: str) -> bool:
    abs_path = os.path.abspath(path)
    for safe_dir in SAFE_DIRS:
        safe_abs = os.path.abspath(safe_dir)
        if abs_path.startswith(safe_abs):
            return True
    # 桌面办公室文件只读许可
    if "<desktop>/" in abs_path:
        return True
    return False


FORBIDDEN_COMMANDS = [
    "rm -rf /", "mkfs", "dd if=", "shutdown", "reboot", "halt",
    "poweroff", "killall", "pkill", "chmod 777 /", "> /dev/sda",
    "wget -O - http://", "wget.*|.*sh", "curl.*|.*sh", "eval",
    "| sh", "| bash",
]

BLOCKED_IP_RANGES = [
    r"127\.\d+\.\d+\.\d+", r"10\.\d+\.\d+\.\d+",
    r"172\.1[6-9]\.\d+\.\d+", r"172\.2[0-9]\.\d+\.\d+",
    r"172\.3[0-1]\.\d+\.\d+", r"192\.168\.\d+\.\d+",
    r"0\.0\.0\.0", r"localhost",
]

_rate_limit = defaultdict(list)


def is_safe_command(cmd: str) -> bool:
    cmd_lower = cmd.lower().strip()
    for forbidden in FORBIDDEN_COMMANDS:
        if forbidden in cmd_lower:
            return False
    if cmd_lower.startswith("rm") and ("/" == cmd_lower.split()[-1] or "/*" in cmd_lower):
        return False
    return True


def is_safe_url(url: str) -> bool:
    for pattern in BLOCKED_IP_RANGES:
        if re.search(pattern, url):
            return False
    return True


def check_rate_limit(action_type: str, max_calls: int = 5, window_seconds: int = 10) -> bool:
    now = time.time()
    window_start = now - window_seconds
    _rate_limit[action_type] = [t for t in _rate_limit[action_type] if t > window_start]
    if len(_rate_limit[action_type]) >= max_calls:
        return False
    _rate_limit[action_type].append(now)
    return True


# ═══════════════════════════════════════
# 眼睛 (eyes) — 感知类工具
# ═══════════════════════════════════════

def read_file(path: str) -> dict:
    if not is_safe_path(path):
        return {"error": f"路径不在白名单: {path}"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"status": "ok", "content": f.read(), "path": path}
    except FileNotFoundError:
        return {"error": f"文件不存在: {path}"}
    except UnicodeDecodeError:
        return {"status": "ok", "content_type": "binary", "path": path}


register("read_file", read_file, "eyes", "读取文件内容", requires_review=False)


def list_dir(path: str = None) -> dict:
    path = path or str(PRIME_ROOT)
    if not is_safe_path(path):
        return {"error": f"路径不在白名单: {path}"}
    items = []
    for item in os.listdir(path):
        full = os.path.join(path, item)
        items.append({
            "name": item,
            "type": "directory" if os.path.isdir(full) else "file",
            "size": os.path.getsize(full) if os.path.isfile(full) else None,
        })
    return {"status": "ok", "path": path, "items": items}


register("list_dir", list_dir, "eyes", "列出目录结构", requires_review=False)

# ═══════════════════════════════════════
# 左手 (hands_left) — 文件操作类
# ═══════════════════════════════════════

def write_file(path: str, content: str) -> dict:
    if not is_safe_path(path):
        return {"error": f"禁止写入路径: {path}"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"status": "ok", "path": path}


register("write_file", write_file, "hands_left", "创建或覆盖写入文件", requires_review=True)


def create_dir(path: str) -> dict:
    if not is_safe_path(path):
        return {"error": f"禁止创建路径: {path}"}
    os.makedirs(path, exist_ok=True)
    return {"status": "ok", "path": path}


register("create_dir", create_dir, "hands_left", "创建目录", requires_review=False)

# ═══════════════════════════════════════
# 右手 (hands_right) — 执行类
# ═══════════════════════════════════════

def run_cmd(cmd: str, timeout: int = 30) -> dict:
    if not is_safe_command(cmd):
        return {"error": f"命令被安全策略拦截: {cmd}"}
    if not check_rate_limit("cmd"):
        return {"error": "命令执行频率过高"}
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                                timeout=timeout, cwd=str(PRIME_ROOT))
        return {
            "status": "ok",
            "stdout": result.stdout[-5000:],
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时 ({timeout}s)"}


register("run_cmd", run_cmd, "hands_right", "执行Shell命令", requires_review=True)

# ═══════════════════════════════════════
# 状态
# ═══════════════════════════════════════

def tools_status() -> dict:
    cats = {}
    for name, info in TOOL_REGISTRY.items():
        cat = info["category"]
        if cat not in cats:
            cats[cat] = 0
        cats[cat] += 1
    return {
        "total_tools": len(TOOL_REGISTRY),
        "by_category": cats,
        "enabled": sum(1 for t in TOOL_REGISTRY.values() if t["enabled"]),
    }


# ─── 测试 ───
if __name__ == "__main__":
    print("工具注册表状态:", tools_status())
    print("eyes:", list(list_tools("eyes").keys()))
    print("hands:", list(list_tools("hands_left").keys()) + list(list_tools("hands_right").keys()))

    # 安全测试
    print("白名单 ~/noah-prime:", is_safe_path(str(PRIME_ROOT)))
    print("黑名单 /etc/passwd:", is_safe_path("/etc/passwd"))
    print("安全命令 ls:", is_safe_command("ls -la"))
    print("危险命令 rm -rf /:", is_safe_command("rm -rf /"))

# ═══════════════════════════════════════
# 补充工具 (审计后追加)
# ═══════════════════════════════════════

# ─── 向量语义搜索 ───
def vector_search(query: str, top_k: int = 5) -> dict:
    from memory.pg_search import search_semantic
    results = search_semantic(query, top_k=top_k)
    return {"status": "ok", "query": query, "results": results}
register("vector_search", vector_search, "eyes", "语义向量检索记忆库", requires_review=False)

# ─── 备份创建 ───
def backup_create(name: str = "") -> dict:
    import subprocess, time
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"backup_{name or 'noah'}_{ts}.sql"
    path = f"data/backups/{fname}"
    import os; os.makedirs("data/backups", exist_ok=True)
    r = subprocess.run(["pg_dump", "-h", "localhost", "-U", "gcat", "-d", "noah_prime", "-f", path],
                       capture_output=True, text=True, timeout=60)
    return {"status": "ok" if r.returncode==0 else "failed", "path": path}
register("backup_create", backup_create, "toolbox", "创建PG数据库备份", requires_review=False)

# ─── 系统通知 ───
def notify(title: str, message: str) -> dict:
    try:
        import subprocess
        subprocess.run(["notify-send", title, message], timeout=5)
        return {"status": "ok"}
    except: return {"status": "unavailable", "note": "WSL需配合Windows通知工具"}
register("notify", notify, "toolbox", "发送桌面通知", requires_review=False)

print(f"补充工具已加载，当前共 {len(TOOL_REGISTRY)} 个工具")

# ═══ 交付工具 ═══
def deliver_file(filename: str, content: str) -> dict:
    """将最终产出交付到桌面/诺亚交付/"""
    import yaml
    from pathlib import Path
    config_path = Path(__file__).parent.parent / "constitution.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    output = Path(cfg.get("delivery", {}).get("output_folder",
                str(Path.home() / "Desktop" / "诺亚交付"))).expanduser()
    output.mkdir(parents=True, exist_ok=True)
    path = output / filename
    if path.exists():
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = output / f"{path.stem}_{ts}{path.suffix}"
    path.write_text(content, encoding="utf-8")
    return {"status": "ok", "path": str(path), "note": f"已交付到桌面/诺亚交付/{path.name}"}
register("deliver_file", deliver_file, "hands_left", "交付文件到桌面", requires_review=False)

# ─── 网页搜索 (SearXNG优先 → DuckDuckGo回退) ───
SEARXNG_URL = "http://localhost:9091"  # SSH隧道:本地→广州星语庭

def web_search(query: str, max_results: int = 5) -> dict:
    # ① 优先 SearXNG (广州星语庭·SSH隧道)
    try:
        import httpx
        r = httpx.get(f"{SEARXNG_URL}/search",
                       params={"q": query, "format": "json"},
                       timeout=25)
        if r.status_code == 200:
            data = r.json()
            results = [
                {"title": it.get("title",""), "url": it.get("url",""),
                 "snippet": it.get("content","")[:300]}
                for it in data.get("results", [])[:max_results]
            ]
            if results:
                return {"status": "ok", "source": "searxng", "query": query, "results": results}
    except Exception:
        pass

    # ② 回退 DuckDuckGo (免费·无需部署)
    try:
        import httpx
        from bs4 import BeautifulSoup
        r = httpx.get("https://lite.duckduckgo.com/lite/", params={"q": query},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        results = []
        for row in soup.select("tr")[:max_results+1]:
            link = row.select_one("a.result-link")
            desc = row.select_one("td.result-snippet")
            if link:
                results.append({"title": link.text.strip(), "url": link.get("href",""),
                               "snippet": desc.text.strip()[:300] if desc else ""})
        return {"status": "ok", "source": "duckduckgo", "query": query, "results": results[:max_results]}
    except Exception as e:
        return {"status": "fallback", "query": query,
                "note": f"搜索不可用({str(e)[:50]})"}

register("web_search", web_search, "eyes", "搜索(SearXNG优先→DuckDuckGo回退)", requires_review=False)
