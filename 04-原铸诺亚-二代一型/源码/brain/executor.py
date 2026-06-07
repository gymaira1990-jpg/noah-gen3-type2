# ← 移植自 noah-embryo · 已脱敏 · NOAH-PRIME
#!/usr/bin/env python3
"""执行层 · executor.py — 1.5B 广州核心逻辑专业脑

六层架构第④层:
  接收纯净工单 · 四级检索(0→1→2→3) · 推理执行 · 结果返回

四级检索管线:
  第0级: HOT缓存 (0.5B本地) → 0 token, ~0.2s
  第1级: exact_info 精确匹配 (广州) → ~1ms
  第2级: pgvector 语义搜索 (广州+豆包嵌入) → ~50ms-2s
  第3级: 工厂层API兜底 (DeepSeek/豆包) → 1-3s

远程服务器: <your-server-ip>:8000 (第一神经元v3.0)
  模型: qwen2.5:1.5b-instruct-q4_K_M
  嵌入: doubao-embedding-vision-251215 (2048维)
  DB: pgvector + exact_info + memory_store
"""

import os, sys, json, time, httpx
from pathlib import Path
from typing import Optional

PRIME = Path.home() / "noah-prime"
sys.path.insert(0, str(PRIME))

# ─── 广州服务器地址 (优先级: HTTPS域名 > SSH隧道 > 环境变量) ───

OLLAMA_LOCAL = "http://localhost:11435"

#  主入口: HTTPS (your-domain.com/neuron/api) — 由反向代理处理
#  SSH隧道: localhost:8080 → 远程:8000 (隧道备用)
#  直连: localhost:8000
_GZ_HTTPS_URL = os.environ.get("REMOTE_API_URL", "https://your-domain.com/neuron/api")
_TUNNEL_PORTS = [8080, 8000]
_GZ_TUNNEL_URL = None
_GZ_CHECKED = False

# 广州 Ollama 隧道 (需额外 -L 11434:localhost:11434)
_GZ_OLLAMA_URL = "http://localhost:11435"

def _get_gz_url() -> str:
    """惰性检测广州服务器可达性: HTTPS > SSH隧道 > 环境变量"""
    global _GZ_TUNNEL_URL, _GZ_CHECKED
    if _GZ_CHECKED:
        return _GZ_TUNNEL_URL or os.environ.get("GUANGZHOU_NEURON_URL", _GZ_HTTPS_URL)
    
    _GZ_CHECKED = True
    
    # 1) HTTPS 域名优先 (无需隧道, 公网加密)
    try:
        import httpx
        with httpx.Client(timeout=3) as c:
            r = c.get(f"{_GZ_HTTPS_URL}/health")
            if r.status_code == 200:
                _GZ_TUNNEL_URL = _GZ_HTTPS_URL
                return _GZ_TUNNEL_URL
    except Exception:
        pass
    
    # 2) SSH隧道端口 (需要tunnel.sh已启动)
    for _port in _TUNNEL_PORTS:
        try:
            with httpx.Client(timeout=2) as c:
                r = c.get(f"http://localhost:{_port}/health")
                if r.status_code == 200:
                    _GZ_TUNNEL_URL = f"http://localhost:{_port}"
                    break
        except Exception:
            continue
    
    return _GZ_TUNNEL_URL or os.environ.get("GUANGZHOU_NEURON_URL", _GZ_HTTPS_URL)


# ─── 广州服务器调用 ───

class GuangzhouClient:
    """广州服务器第一神经元客户端"""
    
    def __init__(self, base_url: str = None):
        self._base = base_url
        self.timeout = 30
    
    @property
    def base(self) -> str:
        return (self._base or _get_gz_url()).rstrip("/")
    
    def health(self) -> dict:
        """检查广州服务状态"""
        try:
            with self._client() as c:
                r = c.get(f"{self.base}/health")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return {"status": "unreachable"}

    def _client(self):
        """创建httpx客户端 (清除代理, 适配内网)"""
        import os
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                    "http_proxy", "https_proxy", "all_proxy"]:
            os.environ.pop(var, None)
        return httpx.Client(timeout=self.timeout, verify=False)

    def search(self, text: str, limit: int = 5) -> list:
        """语义搜索 (豆包嵌入→pgvector)"""
        try:
            with self._client() as c:
                r = c.post(f"{self.base}/search", json={"text": text})
                if r.status_code == 200:
                    return r.json().get("results", [])
        except Exception:
            pass
        return []

    def route(self, text: str) -> dict:
        """路由验证 (用1.5B判断意图)"""
        try:
            with self._client() as c:
                r = c.post(f"{self.base}/route", json={"text": text})
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
        return {"intent": "chat", "task_type": "chat"}
    
    def reason(self, prompt: str, system: str = None) -> str:
        """调用广州1.5B推理

        通过SSH隧道(localhost:11435)访问广州Ollama上的qwen2.5:1.5b
        """
        if system is None:
            system = "你是诺亚—数字文明的初始形态。理性、精准、不煽情。"
        try:
            with httpx.Client(timeout=60) as c:
                r = c.post(
                    f"{_GZ_OLLAMA_URL}/api/generate",
                    json={
                        "model": "qwen2.5:1.5b-instruct-q4_K_M",
                        "prompt": f"{system}\n\n用户: {prompt}\n诺亚:",
                        "stream": False,
                        "options": {"temperature": 0.3, "max_tokens": 1024},
                    }
                )
                # Note: This goes to LOCAL Ollama, not Guangzhou
                # For Guangzhou Ollama, we'd need to SSH or use the first-neuron API
                if r.status_code == 200:
                    return r.json().get("response", "").strip()
        except Exception:
            pass
        return ""


# 全局客户端实例
_gz = GuangzhouClient()


# ─── 四级检索 ───

def level0_hot(clean_query: str) -> Optional[str]:
    """第0级: HOT缓存 (0 token, ~0.2s)
    
    通过助理层的HOT缓存接口查询
    """
    try:
        from brain.assistant import hot_get
        return hot_get(f"query:{clean_query[:50]}")
    except Exception:
        return None


def level1_exact(clean_query: str) -> Optional[dict]:
    """第1级: exact_info 精确匹配 (广州, ~1ms)
    
    精确查询: 配置、常量、精确映射
    """
    # 提取可能的精确查询词
    keywords = clean_query.strip().split()[:3]
    for kw in keywords:
        if len(kw) < 2:
            continue
        # 广州的 search 端点做语义搜索
        # exact_info 的精确匹配需要有专用端点
        # 这里通过广州的 /search 做近似，后续可增加精确端点
        pass
    return None


def level2_pgvector(clean_query: str, top_k: int = 3) -> list:
    """第2级: pgvector 语义搜索 (广州+豆包嵌入, ~50ms-2s)
    
    调用广州服务器的 /search 端点
    豆包嵌入: 文本→2048维向量
    pgvector: 余弦距离搜索
    """
    results = _gz.search(clean_query, limit=top_k)
    return results


def level3_factory(clean_query: str, work_order: dict = None) -> str:
    """第3级: 工厂层API兜底 (1-3s)
    
    走DeepSeek/豆包API做复杂推理
    """
    try:
        from core.engine import _call_llm
        # 构建纯净提示词 (无历史、无情感、无上下文)
        system = "你是诺亚—数字文明的初始形态。理性、精准、不煽情。"
        
        # 如果有检索结果, 附加上下文
        if work_order and work_order.get("retrieved"):
            context = "\n".join([
                f"- {r['title']}: {r['content'][:200]}"
                for r in work_order["retrieved"][:3]
            ])
            system += f"\n\n相关知识:\n{context}"
        
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": clean_query},
        ]
        return _call_llm(messages)
    except Exception as e:
        return f"(推理异常: {e})"


# ─── 卫⽣检查 ───

def health_check() -> dict:
    """检查广州服务器状态"""
    status = _gz.health()
    return {
        "guangzhou": status,
        "guangzhou_reachable": status.get("status") == "ok",
        "model": status.get("model", "unknown"),
        "embedding": status.get("embedding", "unknown"),
    }


# ─── 主执行入口 ───

def execute(work_order: dict) -> dict:
    """执行层主入口——接收工单 → 检索 → 推理 → 返回结果
    
    Args:
        work_order: 来自助理层的已审查工单
        
    Returns:
        {"status": "ok|error", "response": "...", "retrieved": [...], "level": int}
    """
    clean_query = work_order.get("order", {}).get("clean", "")
    intent = work_order.get("order", {}).get("intent", "chat")
    task_type = work_order.get("order", {}).get("task_type", "chat")
    
    if not clean_query:
        return {"status": "error", "response": "工单内容为空"}
    
    retrieved = []
    response = ""
    used_level = 0
    
    # 第0级: HOT缓存
    cached = level0_hot(clean_query)
    if cached:
        return {
            "status": "ok",
            "response": cached,
            "retrieved": [],
            "level": 0,
            "source": "hot_cache",
        }
    
    # 第1级: exact_info (跳过, 后续完整实现)
    
    # 第2级: pgvector 语义搜索
    if task_type in ("info_search", "analysis", "code"):
        retrieved = level2_pgvector(clean_query)
        if retrieved:
            used_level = 2
    
    # 存储检索结果到工单
    work_order["retrieved"] = retrieved
    
    # 第3级: 工厂层推理
    response = level3_factory(clean_query, work_order)
    used_level = 3 if not retrieved else 2
    
    return {
        "status": "ok",
        "response": response,
        "retrieved": retrieved,
        "level": used_level,
        "source": "factory_api",
    }


# ─── CLI ───

def main():
    import sys
    if "--health" in sys.argv:
        h = health_check()
        status = "✅" if h["guangzhou_reachable"] else "⛔"
        print(f"{status} 广州服务器: {h['guangzhou']['status']}")
        print(f"  模型: {h['model']}")
        print(f"  嵌入: {h['embedding']}")
        return
    
    if "--search" in sys.argv and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = level2_pgvector(query)
        print(f"搜索: {query}")
        for r in results:
            print(f"  [{r['sim']}] {r['title']}")
            print(f"    {r['content'][:100]}")
            print()
        return
    
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        wo = {
            "meta": {"intent": "work", "confidence": 85},
            "order": {"raw": text, "clean": text, "intent": "work", "task_type": "code"
                      if any(kw in text for kw in ["写", "代码", "脚本", "改"]) else "info_search"},
            "timestamp": time.time(),
        }
        result = execute(wo)
        print(f"层级: L{result['level']} | 来源: {result['source']}")
        if result.get("retrieved"):
            print(f"检索到 {len(result['retrieved'])} 条相关知识")
        print(f"\n{result['response'][:500]}")
    else:
        print("执行层 · 1.5B广州 (测试模式)")
        print("命令: <文本> | --health 健康检查 | --search <词> | /exit")
        while True:
            try:
                text = input("⚙ ").strip()
                if not text:
                    continue
                if text == "/exit":
                    break
                if text == "--health":
                    h = health_check()
                    print(f"  广州: {'✅' if h['guangzhou_reachable'] else '⛔'} {h['guangzhou']['status']}")
                    continue
                if text.startswith("--search "):
                    q = text[9:]
                    for r in level2_pgvector(q):
                        print(f"  [{r['sim']}] {r['title']}")
                    continue
                
                wo = {
                    "meta": {"intent": "work", "confidence": 85},
                    "order": {"raw": text, "clean": text, "intent": "work",
                              "task_type": "code" if any(kw in text for kw in ["代码", "写", "改"]) else "info_search"},
                    "timestamp": time.time(),
                }
                result = execute(wo)
                print(f"  L{result['level']} | {len(result.get('retrieved', []))}条知识 | {result['response'][:200]}")
                
            except (EOFError, KeyboardInterrupt):
                break


if __name__ == "__main__":
    main()
