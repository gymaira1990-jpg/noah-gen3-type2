#!/usr/bin/env python3
"""双通道分离 · dual_channel.py — API付费 / Web免费 / 本地零成本

基于四代方案v2.0双通道分离设计 + 六层智能体中台成本策略

三通道:
  🗣️ 闲聊通道: qwen3:4b-instruct本地模型 → 零成本
  🌐 Web通道: Playwright自动化搜索 → 零token
  ⚡ API通道: DeepSeek/豆包 → 按量计费

通道路由规则:
  - 闲聊/创作 → 闲聊通道 (0成本)
  - 信息检索/新闻/知识 → Web通道 (0 token)
  - 代码/推理/文案 → API通道 (按量)
"""

import os, sys, json, re, time
from pathlib import Path
from typing import Optional

PRIME = Path.home() / "noah-prime"
sys.path.insert(0, str(PRIME))


# ─── 通道定义 ───

CHANNELS = {
    "chat": {
        "name": "闲聊通道",
        "cost": "零成本",
        "model": "deepseek-v4-flash",
        "think_default": False,
        "desc": "日常对话/创作",
    },
    "web": {
        "name": "Web通道",
        "cost": "零token",
        "model": "Playwright + 搜索引擎",
        "desc": "信息检索/新闻/知识查询",
    },
    "api": {
        "name": "API通道",
        "cost": "按量计费",
        "model": "DeepSeek/豆包",
        "desc": "代码/推理/文案/复杂任务",
    },
}

# Web通道安全规则
WEB_ALLOWED_KEYWORDS = [
    "搜索", "查", "什么是", "怎么", "为什么", "如何",
    "区别", "对比", "新闻", "最近", "消息", "价格",
    "排名", "推荐", "介绍", "定义", "概念", "原理",
    "教程", "指南", "文档", "API", "版本", "更新",
]

WEB_BLOCKED_KEYWORDS = [
    "登录", "密码", "账号", "注册", "购买", "支付",
    "删除", "修改", "上传", "下载文件", "执行",
    "入侵", "破解", "攻击",
]


# ─── Web通道实现 (Playwright) ───

def web_search(query: str, max_results: int = 5) -> list:
    """Web搜索通道 — 零token

    优先SearXNG(广州·多引擎), 降级httpx直连Bing

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数

    Returns:
        [{"title": ..., "snippet": ..., "url": ...}, ...]
    """
    # 安全检测
    for kw in WEB_BLOCKED_KEYWORDS:
        if kw in query.lower():
            return [{"title": "⛔ 安全拦截", "snippet": f"搜索包含敏感词「{kw}」", "url": ""}]

    # 通道1: SearXNG (广州·多引擎, 零代理开销)
    results = _searxng_search(query, max_results)
    if results:
        return results

    # 通道2: httpx直连Bing (国内可达)
    results = _bing_httpx(query, max_results)
    if results:
        return results

    # 通道3: httpx经首尔SOCKS5
    results = _bing_httpx(query, max_results, proxy="socks5://<proxy_host>:<proxy_port>")
    return results


def _searxng_search(query: str, max_results: int = 5) -> list:
    """SearXNG搜索通道 — 经广州服务器(多引擎)

    通过 SSH 隧道访问广州服务器上的 SearXNG Docker 实例。
    支持多引擎聚合(bing/google/duckduckgo/wikipedia/brave)。

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数

    Returns:
        [{"title": ..., "snippet": ..., "url": ..., "engine": ...}, ...]
    """
    try:
        import httpx, os
        # 清除代理环境变量，直连本地隧道
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "http_proxy", "https_proxy", "all_proxy"]:
            os.environ.pop(var, None)

        with httpx.Client(timeout=15) as c:
            r = c.get(
                "http://127.0.0.1:9091/search",
                params={"q": query, "format": "json", "language": "zh-CN"},
                headers={"User-Agent": "Noah-Prime/1.0"},
            )
            if r.status_code != 200:
                return []
            data = r.json()
            results = []
            for item in data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("content", item.get("snippet", ""))[:300],
                    "url": item.get("url", ""),
                    "engine": item.get("engine", "searxng"),
                })
            return results
    except Exception:
        return []


def crawl4ai_fetch(url: str) -> dict:
    """Crawl4AI 页面抓取 — 经广州服务器

    部署在广州服务器上的 Crawl4AI HTTP 服务，
    对指定URL提取结构化内容(Markdown/标题/元数据)。

    Args:
        url: 目标页面URL

    Returns:
        {"title": ..., "content": ..., "markdown": ..., "url": ...}
    """
    try:
        import httpx, os
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                     "http_proxy", "https_proxy", "all_proxy"]:
            os.environ.pop(var, None)

        with httpx.Client(timeout=30) as c:
            r = c.post(
                "http://127.0.0.1:9092/crawl",
                json={"url": url, "extract": "markdown"},
            )
            if r.status_code == 200:
                return r.json()
            return {"url": url, "content": "", "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"url": url, "content": "", "error": str(e)}


def _playwright_search(query: str, max_results: int = 5) -> list:
    """通过Playwright+首尔SOCKS5代理搜索 (零token)"""
    try:
        from playwright.sync_api import sync_playwright
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                proxy={"server": "socks5://<proxy_host>:<proxy_port>"},
            )
            page = browser.new_page()
            page.goto(f"https://www.bing.com/search?q={query}", timeout=15000)

            # 提取搜索结果
            items = page.query_selector_all("li.b_algo")
            for item in items[:max_results]:
                try:
                    link_el = item.query_selector("h2 a, .b_algo h2 a")
                    title = link_el.inner_text().strip() if link_el else ""
                    url = link_el.get_attribute("href") if link_el else ""
                    snippet_el = item.query_selector(".b_caption p, .b_snippet p")
                    snippet = snippet_el.inner_text().strip() if snippet_el else ""
                    if title:
                        results.append({"title": title, "snippet": snippet[:200], "url": url or ""})
                except Exception:
                    continue
            browser.close()
        return results
    except Exception:
        return []


def _bing_httpx(query: str, max_results: int = 5, proxy: str = None) -> list:
    """httpx直连Bing搜索 (零token, 无需代理)"""
    try:
        import httpx
        client_kw = {"timeout": 10, "verify": False, "follow_redirects": True}
        if proxy:
            client_kw["proxies"] = proxy

        # 清除代理环境变量
        for var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                    "http_proxy", "https_proxy", "all_proxy"]:
            os.environ.pop(var, None)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        with httpx.Client(**client_kw) as c:
            r = c.get(f"https://cn.bing.com/search?q={query}", headers=headers)
            if r.status_code != 200:
                return []

            # 提取结果: <a href="http...">text</a> 中text>10字符且非bing域名的
            links = re.findall(
                r'<a\s+(?:[^>]*?\s+)?href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                r.text, re.DOTALL
            )
            results = []
            seen_urls = set()
            for url, text in links:
                text_clean = re.sub(r'<[^>]+>', '', text).strip()
                # 清理: 去掉Bing附加的域名前缀 (如 "zhihu.comhttps://...")
                text_clean = re.sub(r'^[a-z0-9.-]+\.[a-z]{2,6}https?://.*?\s+', '', text_clean)
                if (len(text_clean) > 10
                        and "bing.com" not in url
                        and "microsoft.com" not in url
                        and url not in seen_urls):
                    seen_urls.add(url)
                    # 找对应的摘要
                    snippet = _find_snippet(r.text, url)
                    results.append({
                        "title": text_clean,
                        "snippet": snippet[:200] if snippet else "",
                        "url": url,
                    })
                    if len(results) >= max_results:
                        break
            return results
    except Exception:
        return []


def _find_snippet(html: str, url: str) -> str:
    """从Bing HTML中找url对应摘要"""
    idx = html.find(url[:60])
    if idx == -1:
        return ""
    # 往前找<p>或<div>包裹的文本
    before = html[max(0, idx - 2000):idx]
    # 找最近的 <p> 内容
    p_match = re.findall(r'<p[^>]*>(.*?)</p>', before, re.DOTALL)
    if p_match:
        for p in reversed(p_match):
            clean = re.sub(r'<[^>]+>', '', p).strip()
            if len(clean) > 30:
                return clean[:200]
    # 降级: 取url后的一段文本去标签
    chunk = html[idx:idx + 1000]
    text = re.sub(r'<[^>]+>', ' ', chunk)
    text = re.sub(r'\s+', ' ', text).strip()
    # 找第一个有意义的分句
    for sep in ['。', '. ', '！', '?']:
        parts = text.split(sep)
        if len(parts) > 1 and len(parts[1]) > 15:
            return parts[1][:200]
    return text[:200]


def _web_fallback(query: str, max_results: int = 5) -> list:
    """Web通道降级 — 使用httpx直接请求
    
    当Playwright不可用时的备选方案
    """
    try:
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        search_url = f"https://cn.bing.com/search?q={query}"
        
        with httpx.Client(timeout=10, verify=False) as c:
            r = c.get(search_url, headers=headers)
            if r.status_code == 200:
                # 简单提取标题
                titles = re.findall(r'<h2><a[^>]*>(.*?)</a></h2>', r.text)
                snippets = re.findall(r'<div class="b_caption"[^>]*><p>(.*?)</p>', r.text)
                results = []
                for i, title in enumerate(titles[:max_results]):
                    snippet = snippets[i] if i < len(snippets) else ""
                    results.append({
                        "title": re.sub(r'<[^>]+>', '', title).strip(),
                        "snippet": re.sub(r'<[^>]+>', '', snippet).strip()[:200],
                        "url": "",
                    })
                return results
    except Exception:
        pass
    return []


# ─── 通道安全清洗 ───

def web_sanitize(results: list) -> list:
    """Web通道返回内容二次清洗
    
    去除危险指令/广告/无关链接
    """
    sanitized = []
    danger_patterns = [
        r"rm\s+-rf", r"format\s+[c-z]:", r"dd\s+if=",
        r"DROP\s+TABLE", r"TRUNCATE\s+TABLE",
        r"sudo\s+rm", r"chmod\s+777",
    ]
    
    for item in results:
        content = f"{item.get('title', '')} {item.get('snippet', '')}"
        
        # 检查危险指令
        dangerous = False
        for pat in danger_patterns:
            if re.search(pat, content, re.IGNORECASE):
                dangerous = True
                break
        
        if dangerous:
            continue  # 丢弃危险结果
        
        sanitized.append(item)
    
    return sanitized


# ─── 通道路由 ───

def route(work_order: dict) -> dict:
    """通道路由决策
    
    Args:
        work_order: 来自助理层的工单
        
    Returns:
        {"channel": "chat|web|api", "reason": "...", "cost": "零成本|零token|按量"}
    """
    intent = work_order.get("order", {}).get("intent", "chat")
    task_type = work_order.get("order", {}).get("task_type", "chat")
    clean_query = work_order.get("order", {}).get("clean", "")
    
    # 闲聊 → 本地3B
    if intent == "chat":
        return {"channel": "chat", "reason": "闲聊走本地3B, 零成本", "cost": "零成本"}
    
    # 搜索/知识查询 → Web通道
    if intent in ("knowledge", "study"):
        return {"channel": "web", "reason": f"知识查询走Web搜索, 零token", "cost": "零token"}
    
    # 工作类
    if intent == "work":
        # 检查是否搜索类任务
        is_search = any(kw in clean_query.lower() for kw in WEB_ALLOWED_KEYWORDS)
        if is_search and task_type in ("info_search",):
            return {"channel": "web", "reason": "搜索类走Web通道, 零token", "cost": "零token"}
        
        # 其他工作走API
        return {"channel": "api", "reason": f"工作类({task_type})走API, 按量计费", "cost": "按量计费"}
    
    # 修bug → API
    if intent == "fix":
        return {"channel": "api", "reason": "修bug走API, 按量计费", "cost": "按量计费"}
    
    # 默认安全 → API
    return {"channel": "api", "reason": "默认走API, 宁可花钱不可出错", "cost": "按量计费"}


# ─── 月成本估算 ───

def estimate_monthly_cost(stats: dict = None) -> dict:
    """估算月成本
    
    Args:
        stats: 调用量统计, 默认使用典型值
        
    Returns:
        {"chat": {"calls": N, "cost": "¥0"},
         "web": {"calls": N, "cost": "¥0"},
         "api": {"calls": N, "cost": "¥N"},
         "total": "¥N"}
    """
    if stats is None:
        stats = {"chat": 2000, "web": 500, "api": 250}
    
    api_cost_per_call = 0.03  # DeepSeek ~¥0.03/次
    api_total = stats.get("api", 0) * api_cost_per_call
    
    return {
        "chat": {"calls": stats.get("chat", 0), "cost": "¥0"},
        "web": {"calls": stats.get("web", 0), "cost": "¥0"},
        "api": {"calls": stats.get("api", 0), "cost": f"¥{api_total:.1f}"},
        "total": f"¥{api_total:.1f}",
    }


# ─── 集成助手 ───

def get_channel_info(channel: str) -> dict:
    """获取通道详细信息"""
    return CHANNELS.get(channel, {"name": "未知", "cost": "?", "desc": "?"})


# ─── CLI ───

def main():
    import sys
    if "--cost" in sys.argv:
        est = estimate_monthly_cost()
        print("月成本估算:")
        print(f"  闲聊通道: {est['chat']['calls']}次 → {est['chat']['cost']}")
        print(f"  Web通道:  {est['web']['calls']}次 → {est['web']['cost']}")
        print(f"  API通道:  {est['api']['calls']}次 → {est['api']['cost']}")
        print(f"  ─────────────────────")
        print(f"  总计: {est['total']}")
        return
    
    if "--search" in sys.argv and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        print(f"Web搜索: {query}")
        results = web_search(query)
        for r in results:
            print(f"  • {r['title']}")
            if r['snippet']:
                print(f"    {r['snippet'][:100]}")
        return
    
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        wo = {
            "meta": {"intent": "work", "confidence": 85},
            "order": {"raw": text, "clean": text, "intent": "work",
                      "task_type": "info_search" if any(
                          kw in text for kw in ["搜索", "查", "什么", "怎么"]) else "code"},
        }
        r = route(wo)
        info = get_channel_info(r["channel"])
        print(f"通道: {info['name']} ({r['cost']})")
        print(f"理由: {r['reason']}")
    else:
        print("双通道分离 · API付费 / Web免费 / 本地零成本")
        print("用法: python3 dual_channel.py <文本>")
        print("      python3 dual_channel.py --search <关键词>")
        print("      python3 dual_channel.py --cost")
        print()
        for ch, info in CHANNELS.items():
            print(f"  {ch:6} | {info['name']:10} | {info['cost']:8} | {info['desc']}")


if __name__ == "__main__":
    main()
