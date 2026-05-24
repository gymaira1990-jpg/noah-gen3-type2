"""工具注册表 — 扫描/加载/健康检查 YAML 定义的工具"""
import os, json, subprocess, time, pathlib
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None

TOOL_HOME = os.getenv("TOOL_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_DIR = pathlib.Path(TOOL_HOME) / "registry"
HEALTH_CACHE = {}   # name → {status, latency, timestamp}
HEALTH_TTL = 120    # 秒内缓存健康状态

ALIVE = "alive"
DEGRADED = "degraded"
DEAD = "dead"
UNKNOWN = "unknown"


def scan() -> dict:
    """扫描所有注册的 YAML 文件，返回 {name: tool_def}"""
    tools = {}
    if not REGISTRY_DIR.exists():
        return tools
    for yaml_file in sorted(REGISTRY_DIR.glob("**/*.yaml")):
        name = yaml_file.stem
        try:
            with open(yaml_file) as f:
                if yaml:
                    data = yaml.safe_load(f)
                else:
                    return {"_error": "PyYAML 未安装: pip install pyyaml"}
            if data and isinstance(data, dict):
                data["_path"] = str(yaml_file)
                tools[name] = data
        except Exception as e:
            print(f"⚠️ 加载 {yaml_file.name} 失败: {e}")
    return tools


def load(name: str) -> Optional[dict]:
    """加载单个工具定义"""
    for yaml_file in REGISTRY_DIR.glob("**/*.yaml"):
        if yaml_file.stem == name:
            try:
                with open(yaml_file) as f:
                    return yaml.safe_load(f) if yaml else None
            except Exception:
                return None
    return None


def health_check(tool: dict, force: bool = False) -> dict:
    """检查单个工具健康状态。返回 {status, latency, detail}"""
    name = tool.get("name", "?")
    cached = HEALTH_CACHE.get(name)
    if cached and not force and (time.time() - cached["timestamp"]) < HEALTH_TTL:
        return cached

    health_def = tool.get("health", {})
    if not health_def:
        result = {"status": UNKNOWN, "latency": 0, "detail": "无健康检查配置"}
        HEALTH_CACHE[name] = {**result, "timestamp": time.time()}
        return result

    start = time.time()
    try:
        cmd = health_def.get("command", "")
        if not cmd:
            result = {"status": UNKNOWN, "latency": 0, "detail": "health.command 为空"}
        else:
            timeout = health_def.get("timeout", 10)
            shell = health_def.get("shell", False)
            proc = subprocess.run(
                cmd if shell else cmd.split(),
                capture_output=True, timeout=timeout, text=True,
                shell=shell
            )
            elapsed = time.time() - start
            if proc.returncode != 0:
                result = {"status": DEAD, "latency": elapsed,
                          "detail": f"exit={proc.returncode}: {proc.stderr[:100]}"}
            else:
                # 检查 expect 规则
                expect = health_def.get("expect", {})
                if expect:
                    try:
                        data = json.loads(proc.stdout)
                        field = expect.get("field", "")
                        expected_val = expect.get("value")
                        if field:
                            actual = data.get(field)
                            if expected_val is not None and actual != expected_val:
                                result = {"status": DEGRADED, "latency": elapsed,
                                          "detail": f"{field}={actual},预期={expected_val}"}
                            else:
                                result = {"status": ALIVE, "latency": elapsed,
                                          "detail": f"{field}={actual}"}
                        else:
                            result = {"status": ALIVE, "latency": elapsed, "detail": "ok"}
                    except (json.JSONDecodeError, TypeError):
                        result = {"status": ALIVE, "latency": elapsed, "detail": "ok"}
                else:
                    result = {"status": ALIVE, "latency": elapsed, "detail": "ok"}
    except subprocess.TimeoutExpired:
        result = {"status": DEAD, "latency": time.time() - start, "detail": "超时"}
    except FileNotFoundError:
        result = {"status": DEAD, "latency": time.time() - start, "detail": "命令不存在"}
    except Exception as e:
        result = {"status": DEAD, "latency": time.time() - start, "detail": str(e)[:100]}

    HEALTH_CACHE[name] = {**result, "timestamp": time.time()}
    return result


def health_all(force: bool = False) -> dict:
    """全量健康检查"""
    tools = scan()
    result = {}
    for name, tool in sorted(tools.items()):
        result[name] = health_check(tool, force=force)
    return result


def tools_by_capability(capability: str) -> list:
    """按能力查找可用工具"""
    tools = scan()
    matches = []
    for name, tool in tools.items():
        caps = tool.get("capabilities", [])
        if capability in caps:
            h = health_check(tool)
            matches.append({"name": name, "tool": tool, "health": h})
    order = {ALIVE: 0, DEGRADED: 1, UNKNOWN: 2, DEAD: 3}
    matches.sort(key=lambda m: order.get(m["health"]["status"], 99))
    return matches


def best_tool(capability: str) -> Optional[dict]:
    """找某能力的最佳可用工具"""
    matches = tools_by_capability(capability)
    for m in matches:
        if m["health"]["status"] == ALIVE:
            return m
    return matches[0] if matches else None


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        t = scan()
        for n, d in t.items():
            print(f"  {n:20s}  [{d.get('type','?')}]  {d.get('description','')[:50]}")
        print(f"总计: {len(t)} 工具")
    elif cmd == "health":
        h = health_all(force="--force" in sys.argv)
        for n, r in h.items():
            icon = {"alive": "🟢", "degraded": "🟡", "dead": "🔴", "unknown": "⚪"}
            print(f"  {icon.get(r['status'],'?')} {n:20s}  {r['latency']:.2f}s  {r['detail'][:50]}")
    elif cmd == "best":
        cap = sys.argv[2] if len(sys.argv) > 2 else "web_search"
        b = best_tool(cap)
        if b:
            print(f"最佳: {b['name']}  ({b['health']['status']})")
        else:
            print(f"无工具提供能力: {cap}")
