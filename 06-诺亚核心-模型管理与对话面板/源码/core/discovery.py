"""诺亚核心 · 模型发现/搜索/下载"""
import os, json, urllib.request
from pathlib import Path
from typing import Optional
def fetch_models_from_api(api_base: str, api_key_env: Optional[str] = None) -> list[dict]:
    """扫 OpenAI 兼容端点的 /models"""
    try:
        url = f"{api_base.rstrip('/')}/models"
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(api_key_env) if api_key_env else None
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        models = data.get("data", [])
        return [{"id": m["id"], "owned_by": m.get("owned_by", "unknown"),
                  "real_name": m["id"]} for m in models]
    except Exception:
        return []


def discover_ollama_models(api_base: str = "http://localhost:11434") -> list[dict]:
    """扫 Ollama /api/tags"""
    try:
        url = f"{api_base.rstrip('/')}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        results = []
        for m in data.get("models", []):
            name = m.get("name", "")
            details = m.get("details", {})
            results.append({
                "id": name,
                "real_name": name.split(":")[0],
                "parameter_size": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", ""),
                "family": details.get("family", ""),
                "size": m.get("size", 0),
            })
        return results
    except Exception:
        return []


def discover_llamacpp_models() -> tuple[list[dict], list[int]]:
    """扫常见的 llama.cpp 端口"""
    import re, subprocess
    ports = [8080, 8081, 11433, 11434, 11435, 11436, 11437]
    results = []
    scanned = []
    for port in ports:
        try:
            url = f"http://localhost:{port}/v1/models"
            req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
            models = data.get("data", []) or data.get("models", [])
            if models:
                for m in models:
                    mid = m.get("id") or m.get("name", "")
                    if mid:
                        name_lower = mid.lower()
                        if "embedding" in name_lower or "embed" in name_lower:
                            capability = "embedding"
                        elif "reranker" in name_lower or "rerank" in name_lower or "bge" in name_lower:
                            capability = "reranker"
                        else:
                            has_vision = False
                            try:
                                r = subprocess.run(
                                    ["ss", "-tlnp", f"sport = :{port}"],
                                    capture_output=True, text=True, timeout=5
                                )
                                m2 = re.search(r'pid=(\d+)', r.stdout)
                                if m2:
                                    pid = m2.group(1)
                                    p = open(f"/proc/{pid}/cmdline").read()
                                    if "--mmproj" in p:
                                        has_vision = True
                            except Exception:
                                pass
                            capability = "vision" if has_vision else "chat"
                        results.append({
                            "id": mid, "real_name": mid, "port": port,
                            "api_base": f"http://localhost:{port}",
                            "capability": capability, "size": "",
                        })
                scanned.append(port)
        except Exception:
            continue
    return results, scanned


def search_hf_models(query: str, limit: int = 10) -> list[dict]:
    """搜 HuggingFace GGUF 模型"""
    import urllib.parse
    mirror = os.environ.get("HF_MIRROR", "")
    bases = ["https://huggingface.co", "https://hf-mirror.com"]
    if mirror:
        bases = ["https://hf-mirror.com"]
    for base in bases:
        try:
            q = urllib.parse.quote(query)
            url = f"{base}/api/models?search={q}&filter=gguf&sort=downloads&direction=-1&limit={limit}"
            req = urllib.request.Request(url, headers={"User-Agent": "arc/0.1"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            results = []
            for m in data:
                mid = m.get("id", "")
                results.append({
                    "id": mid,
                    "real_name": mid.split("/")[-1] if "/" in mid else mid,
                    "downloads": m.get("downloads", 0),
                    "likes": m.get("likes", 0),
                    "pipeline_tag": m.get("pipeline_tag", ""),
                })
            return results
        except Exception:
            continue
    return []


def pull_hf_model(repo_id: str) -> dict:
    """从 HuggingFace 下载模型"""
    import shutil, subprocess
    CONFIG_DIR = Path.home() / ".noah-core"
    if shutil.which("huggingface-cli"):
        try:
            result = subprocess.run(
                ["huggingface-cli", "download", repo_id, "--local-dir",
                 str(CONFIG_DIR / "models" / repo_id.replace("/", "_"))],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode == 0:
                return {"success": True, "path": str(CONFIG_DIR / "models" / repo_id.replace("/", "_"))}
            return {"success": False, "error": result.stderr[:200]}
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {"success": False, "error": "请安装 huggingface-cli: pip install huggingface-hub",
                "url": f"https://huggingface.co/{repo_id}"}


def pull_ollama_model(model_name: str) -> dict:
    """通过 ollama pull 下载模型"""
    import shutil, subprocess
    if not shutil.which("ollama"):
        return {"success": False, "error": "ollama 未安装"}
    try:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            return {"success": True, "path": f"ollama:{model_name}"}
        return {"success": False, "error": result.stderr[:200]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def pull_ollama_model_wrapper(model_name: str) -> dict:
    """包装函数（兼容旧代码）"""
    return pull_ollama_model(model_name)
