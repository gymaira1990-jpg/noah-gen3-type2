#!/usr/bin/env python3
"""
Edge/Chrome CDP 控制工具 — 纯 Python stdlib 实现

无需 Playwright/Selenium，不依赖任何第三方库。
通过 Chrome DevTools Protocol (CDP) 控制浏览器：
  - 真实浏览器搜索，绕过搜索引擎 CAPTCHA
  - 页面全文抓取
  - 基于浏览器用户登录态

架构：Agent → 原生 TCP socket → HTTP 创建标签页 → 自制 WebSocket 帧解析
"""

import json, os, socket, struct, base64, time, random, http.client, urllib.parse

# ─── 清除代理环境变量 ───
# WSL/Linux 常见 HTTP_PROXY 污染，干扰 CDP 连接
for k in list(os.environ.keys()):
    if 'proxy' in k.lower():
        os.environ.pop(k, None)

# CDP 端点 — 通过环境变量配置，默认 localhost:9222
CDP_HOST = os.getenv("CDP_HOST", "127.0.0.1")
CDP_PORT = int(os.getenv("CDP_PORT", "9222"))


# ═══════════════════════════════════════════════
# 裸 WebSocket 实现
# ═══════════════════════════════════════════════

class RawWS:
    """无依赖的 WebSocket 客户端。

    绕过 HTTP_PROXY 污染的标准做法：
    用原生 socket 建立 TCP 连接，手动 HTTP Upgrade 握手。
    """

    def __init__(self, path: str):
        self.sock = socket.create_connection(
            (CDP_HOST, CDP_PORT), timeout=10
        )
        self._handshake(path)

    def _handshake(self, path: str):
        """WebSocket 升级握手 (RFC 6455)"""
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {CDP_HOST}:{CDP_PORT}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b''
        while not buf.endswith(b'\r\n\r\n'):
            c = self.sock.recv(1)
            if not c:
                raise ConnectionError("WebSocket 握手失败")
            buf += c
        if b"101" not in buf.split(b"\r\n")[0]:
            raise ConnectionError(
                f"WebSocket 拒绝: {buf.decode(errors='replace')[:100]}"
            )

    def send(self, data):
        """发送 WebSocket 帧（客户端需 MASK）"""
        d = data.encode() if isinstance(data, str) else data
        frame = bytearray([0x81])  # text frame + FIN
        mask = os.urandom(4)
        if len(d) < 126:
            frame.append(0x80 | len(d))
        elif len(d) < 65536:
            frame.extend([0x80 | 126])
            frame.extend(struct.pack('>H', len(d)))
        else:
            frame.extend([0x80 | 127])
            frame.extend(struct.pack('>Q', len(d)))
        frame.extend(mask)
        frame.extend(bytes(d[i] ^ mask[i % 4] for i in range(len(d))))
        self.sock.sendall(frame)

    def recv(self, timeout=10):
        """接收一帧。服务器帧不加 MASK"""
        self.sock.settimeout(timeout)
        try:
            raw = self.sock.recv(65536)
        except socket.timeout:
            return None
        if len(raw) < 2:
            return None
        length = raw[1] & 0x7f
        offset = 2
        if length == 126:
            length, offset = struct.unpack('>H', raw[2:4])[0], 4
        elif length == 127:
            length, offset = struct.unpack('>Q', raw[2:10])[0], 10
        if raw[1] & 0x80:  # 客户端帧有 MASK 位（但服务器不会）
            offset += 4
        return raw[offset:offset + length]

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════
# CDP 协议层
# ═══════════════════════════════════════════════

def _new_tab(url: str) -> tuple:
    """通过 CDP HTTP 接口创建新标签页"""
    conn = http.client.HTTPConnection(CDP_HOST, CDP_PORT, timeout=5)
    qurl = urllib.parse.quote(url, safe='')
    conn.request("PUT", f"/json/new?{qurl}")
    resp = conn.getresponse()
    if resp.status != 200:
        raise RuntimeError(f"新建标签页失败: HTTP {resp.status}")
    page = json.loads(resp.read())
    conn.close()
    return page["webSocketDebuggerUrl"], page["id"]


def _close_tab(page_id: str):
    """关闭标签页"""
    try:
        conn = http.client.HTTPConnection(CDP_HOST, CDP_PORT, timeout=5)
        conn.request("DELETE", f"/json/close/{page_id}")
        conn.getresponse().read()
        conn.close()
    except Exception:
        pass  # 关不掉不阻塞


def _cdp_call(ws: RawWS, method: str, params: dict = None,
              timeout=20) -> dict:
    """发送 CDP 命令并等待匹配的响应"""
    msg_id = random.randint(1000, 9999)
    cmd = {"id": msg_id, "method": method}
    if params:
        cmd["params"] = params
    ws.send(json.dumps(cmd))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = ws.recv(timeout=min(3.0, deadline - time.time()))
        except socket.timeout:
            continue
        if r is None:
            continue
        try:
            d = json.loads(r)
            if d.get("id") == msg_id:
                return d
        except json.JSONDecodeError:
            continue
    return {"error": "timeout", "method": method}


def _wait_loaded(ws: RawWS, max_wait=20) -> bool:
    """等待页面加载完成"""
    time.sleep(2)  # 给页面启动时间
    for _ in range(max_wait):
        r = _cdp_call(ws, "Runtime.evaluate",
                      {"expression": "document.readyState"})
        if "error" in r:
            time.sleep(1)
            continue
        state = (r.get("result", {}).get("result", {}).get("value", ""))
        if state == "complete":
            return True
        time.sleep(1)
    return False


# ═══════════════════════════════════════════════
# 搜索 API
# ═══════════════════════════════════════════════

SEARCH_ENGINES = {
    "baidu":  "https://www.baidu.com/s?wd={query}&rn={max_results}",
    "bing":   "https://cn.bing.com/search?q={query}&count={max_results}",
    "google": "https://www.google.com/search?q={query}&num={max_results}",
}


def edge_search(query: str, engine: str = "baidu",
                max_results: int = 8) -> dict:
    """真实浏览器搜索 — 新建标签页，提取结果，用完即关"""
    url_tpl = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["baidu"])
    url = url_tpl.format(query=query, max_results=max_results)

    try:
        ws_url, page_id = _new_tab(url)
        path = "/" + ws_url.split("/", 3)[3]
        ws = RawWS(path)
    except Exception as e:
        return {"error": f"新建标签页失败: {e}"}

    try:
        _wait_loaded(ws, max_wait=20)
        time.sleep(random.uniform(1.0, 2.0))

        # 页面标题
        r = _cdp_call(ws, "Runtime.evaluate",
                      {"expression": "document.title"})
        title = r.get("result", {}).get("result", {}).get("value", "")

        # 页面文本
        r = _cdp_call(ws, "Runtime.evaluate",
                      {"expression": "document.body.innerText"})
        content = r.get("result", {}).get("result", {}).get("value", "")

        # 提取链接
        js = """JSON.stringify(
            Array.from(document.querySelectorAll('a'))
            .filter(a => a.href && a.innerText.trim().length > 5
                    && a.href.startsWith('http'))
            .slice(0, 15)
            .map(a => ({title: a.innerText.trim(), url: a.href}))
        )"""
        r = _cdp_call(ws, "Runtime.evaluate", {"expression": js})
        links_str = (r.get("result", {}).get("result", {}).get("value", "[]"))
        try:
            links = json.loads(links_str)
        except json.JSONDecodeError:
            links = []

        return {
            "query": query, "engine": engine,
            "page_title": title,
            "links": links,
            "content_preview": content[:500],
            "content_len": len(content),
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        ws.close()
        _close_tab(page_id)


def edge_crawl(url: str) -> dict:
    """抓取页面全文"""
    try:
        ws_url, page_id = _new_tab(url)
        path = "/" + ws_url.split("/", 3)[3]
        ws = RawWS(path)
    except Exception as e:
        return {"error": f"新建标签页失败: {e}"}

    try:
        _wait_loaded(ws, max_wait=30)
        time.sleep(random.uniform(2.0, 3.0))

        r = _cdp_call(ws, "Runtime.evaluate",
                      {"expression": "document.title"})
        title = r.get("result", {}).get("result", {}).get("value", "")

        r = _cdp_call(ws, "Runtime.evaluate",
                      {"expression": "document.body.innerText"})
        text = r.get("result", {}).get("result", {}).get("value", "")

        return {"url": url, "title": title,
                "content": text[:8000], "content_len": len(text)}
    except Exception as e:
        return {"error": str(e)}
    finally:
        ws.close()
        _close_tab(page_id)


def check_cdp() -> dict:
    """检查 CDP 连接状态"""
    try:
        conn = http.client.HTTPConnection(CDP_HOST, CDP_PORT, timeout=5)
        conn.request("GET", "/json/version")
        resp = conn.getresponse()
        info = json.loads(resp.read())
        conn.close()
        return {"connected": True, "browser": info.get("Browser", "?")}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ═══════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法:")
        print(f"  python3 {sys.argv[0]} check")
        print(f"  python3 {sys.argv[0]} search <query> [baidu|google|bing]")
        print(f"  python3 {sys.argv[0]} crawl <url>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "check":
        result = check_cdp()
    elif cmd == "search":
        query = sys.argv[2] if len(sys.argv) > 2 else ""
        engine = sys.argv[3] if len(sys.argv) > 3 else "baidu"
        result = edge_search(query, engine=engine)
    elif cmd == "crawl":
        url = sys.argv[2] if len(sys.argv) > 2 else ""
        result = edge_crawl(url)
    else:
        result = {"error": f"未知命令: {cmd}"}

    print(json.dumps(result, ensure_ascii=False, indent=2))
