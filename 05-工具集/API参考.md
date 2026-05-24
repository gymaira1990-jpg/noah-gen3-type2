# 05 · 工具集 · API 参考

> 📖 完整接口文档 · 数据模型 · 返回格式

---

## Edge CDP API

### `check_cdp() → dict`

检查浏览器 CDP 连接状态。

**返回：**
```json
{"connected": true, "browser": "Edg/148.0.0"}
```
```json
{"connected": false, "error": "Connection refused"}
```

---

### `edge_search(query: str, engine: str = "baidu", max_results: int = 8) → dict`

通过真实浏览器执行搜索。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|:-----|:----:|:------:|:-----|
| `query` | str | (必填) | 搜索关键词 |
| `engine` | str | `"baidu"` | 搜索引擎：`"baidu"` / `"google"` / `"bing"` |
| `max_results` | int | 8 | 搜索结果数（搜索引擎限制，非精确） |

**返回（成功）：**
```json
{
  "query": "Python asyncio",
  "engine": "google",
  "page_title": "Python asyncio - Google 搜索",
  "links": [
    {"title": "asyncio 官方文档", "url": "https://docs.python.org/3/library/asyncio.html"},
    {"title": "asyncio 教程", "url": "https://realpython.com/async-io-python/"}
  ],
  "content_preview": "asyncio 是 Python 标准库...",
  "content_len": 15342
}
```

**返回（错误）：**
```json
{"error": "新建标签页失败: [Errno 111] Connection refused"}
```

---

### `edge_crawl(url: str) → dict`

抓取指定 URL 的页面全文。

**参数：**

| 参数 | 类型 | 默认值 | 说明 |
|:-----|:----:|:------:|:-----|
| `url` | str | (必填) | 完整 URL，含协议头 |

**返回（成功）：**
```json
{
  "url": "https://example.com",
  "title": "Example Domain",
  "content": "This domain is for use in illustrative examples...",
  "content_len": 1256
}
```

---

## CLI 接口

### `python3 edge_cdp.py check`

等同于 `check_cdp()`，JSON 输出。

### `python3 edge_cdp.py search <query> [engine]`

等同于 `edge_search(query, engine)`。

### `python3 edge_cdp.py crawl <url>`

等同于 `edge_crawl(url)`。

---

## 工具注册表格式（YAML）

```yaml
# 注册表条目格式
name: string            # 工具名称（唯一标识）
type: string            # "local" | "remote" | "http"
command: string         # 主命令（路径或shell命令）
actions:                # 子命令映射
  action_name: string   # 执行命令（可用 {arg} 占位）
health:                 # 健康检查（可选）
  check: string         # 健康检查命令
fallback: string        # 降级工具名称（可选）
```

---

## 搜索引擎支持

| 引擎 | URL 模板 | 特点 |
|:-----|:---------|:-----|
| `baidu` | `https://www.baidu.com/s?wd={query}&rn={n}` | 中文搜索最优 |
| `google` | `https://www.google.com/search?q={query}&num={n}` | 全球搜索 |
| `bing` | `https://cn.bing.com/search?q={query}&count={n}` | 中英兼顾 |
