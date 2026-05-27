# 诺亚核心 · API 参考

> 完整 REST API 接口文档

---

## 一、基础信息

| 项目 | 值 |
|:-----|:----|
| 基础 URL | `http://localhost:8110` |
| 数据格式 | JSON |
| 字符编码 | UTF-8 |

---

## 二、系统状态

### GET /api/system

系统资源状态（CPU/内存/GPU/磁盘/Swap/运行时间）。

**响应示例**：
```json
{
  "cpu": {
    "cores": "32",
    "load": ["0.36", "0.55", "0.67"]
  },
  "memory": {
    "total": 21766,
    "used": 3283,
    "free": 12534,
    "pct": "15.1%",
    "pct_num": 15
  },
  "gpu": [
    {
      "name": "NVIDIA GeForce RTX 5070 Laptop GPU",
      "vram_total": 8151,
      "vram_used": 7436,
      "vram_pct": 91.2,
      "util": 3,
      "temp": "41"
    }
  ],
  "disk": {
    "mount": "/",
    "total": "252G",
    "used": "47G",
    "avail": "196G",
    "use_pct": "20%",
    "use_pct_num": 20
  },
  "swap": {
    "total": 131072,
    "used": 1176,
    "pct": "0.9%",
    "pct_num": 1
  },
  "uptime": "4时 0分",
  "uptime_sec": 14402,
  "processes": 61,
  "hostname": "hostname"
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `cpu.cores` | string | CPU 核心数 |
| `cpu.load` | string[] | 1/5/15 分钟平均负载 |
| `memory.total` | int | 物理内存总量 (MB) |
| `memory.used` | int | 已用内存 (MB) |
| `memory.free` | int | 空闲内存 (MB) |
| `memory.pct` | string | 使用率 (字符串，含 `%`) |
| `memory.pct_num` | int | 使用率 (纯数字) |
| `gpu[].name` | string | GPU 型号 |
| `gpu[].vram_total` | int | 显存总量 (MiB) |
| `gpu[].vram_used` | int | 已用显存 (MiB) |
| `gpu[].vram_pct` | float | 显存使用率 (%) |
| `gpu[].util` | int | GPU 利用率 (%) |
| `gpu[].temp` | string | GPU 温度 (°C) |
| `disk.total` | string | 磁盘总量 |
| `disk.used` | string | 已用空间 |
| `disk.use_pct` | string | 使用率 |
| `disk.use_pct_num` | int | 使用率 (纯数字) |
| `swap.total` | int | Swap 总量 (MB) |
| `swap.used` | int | 已用 Swap (MB) |
| `swap.pct_num` | int | Swap 使用率 |
| `uptime` | string | 运行时间 |
| `processes` | int | 进程总数 |
| `hostname` | string | 主机名 |

### GET /api/check

所有模型健康状态。

**响应示例**：
```json
{
  "total": 3,
  "online": 1,
  "offline": 2,
  "models": [
    {
      "name": "deepseek-chat",
      "online": true,
      "latency_ms": 234.5,
      "status_text": "在线 (235ms)",
      "provider": "openai",
      "type": "api",
      "description": "DeepSeek V4 Flash",
      "real_name": "DeepSeek V4 Flash",
      "model_id": "deepseek-chat",
      "api_base": "https://api.deepseek.com/v1",
      "api_key_env": "DEEPSEEK_API_KEY",
      "temperature": 0.7,
      "max_tokens": 8192,
      "notes": ""
    }
  ]
}
```

### GET /api/check/{name}

单个模型健康状态。

### GET /api/services

本地 llama.cpp 服务状态。

**响应示例**：
```json
[
  {
    "name": "Qwen3.5-4B",
    "service": "lla-server",
    "active": true,
    "port": 11435,
    "has_mmproj": false
  },
  {
    "name": "Qwen3 Embedding",
    "service": "lla-embed",
    "active": false,
    "port": 11433,
    "has_mmproj": false
  }
]
```

### GET /api/config

返回配置文件内容。

---

## 三、模型管理

### GET /api/models

列出所有模型。

**响应示例**：
```json
{
  "object": "list",
  "data": [
    {
      "id": "deepseek-chat",
      "name": "deepseek-chat",
      "real_name": "DeepSeek V4 Flash",
      "model_id": "deepseek-chat",
      "object": "model",
      "owned_by": "openai",
      "api_base": "https://api.deepseek.com/v1",
      "api_key_env": "DEEPSEEK_API_KEY",
      "type": "api",
      "temperature": 0.7,
      "max_tokens": 8192,
      "description": "DeepSeek V4 Flash — 主力推理模型",
      "notes": ""
    }
  ]
}
```

### POST /api/models

添加新模型。

**请求体**：
```json
{
  "name": "my-model",
  "real_name": "我的模型",
  "model_id": "gpt-4",
  "provider": "openai",
  "api_base": "https://api.openai.com/v1",
  "api_key_env": "OPENAI_API_KEY",
  "type": "api",
  "temperature": 0.7,
  "max_tokens": 4096,
  "description": "测试模型",
  "notes": ""
}
```

**响应**: `{"status": "ok", "name": "my-model"}` — 201
**错误**: `409` 模型已存在, `400` 名称或 API 地址为空

### PUT /api/models/{name}

编辑模型。支持部分更新，只传需要改的字段。

**请求体**（可选传任一字段）：
```json
{
  "temperature": 0.5,
  "description": "新描述"
}
```

### DELETE /api/models/{name}

删除模型。

**响应**: `{"status": "ok", "name": "deepseek-chat"}`

### GET /api/models/library

分类模型库，按「可对话 vs 功能模型」和「本地 vs 云」分组。

**响应结构**：
```json
{
  "chat": {
    "local": [...],
    "cloud": [...]
  },
  "function": {
    "local": [...],
    "cloud": [...]
  }
}
```

---

## 四、模型发现

### GET /api/discover-ollama

扫描本地 Ollama 和 llama.cpp 模型。

### GET /api/discover-api?api_base=...&api_key_env=...

扫描指定 API 端点的可用模型。

### GET /api/search-hf?q=qwen3

搜索 HuggingFace GGUF 模型。

| 参数 | 必填 | 说明 |
|:-----|:----:|:------|
| `q` | 是 | 搜索关键词 |

**响应**：
```json
{
  "results": [
    {
      "id": "Qwen/Qwen3.5-4B-GGUF",
      "real_name": "Qwen3.5-4B-GGUF",
      "downloads": 1234567,
      "likes": 890,
      "pipeline_tag": "text-generation"
    }
  ]
}
```

### POST /api/add-discovered

批量添加发现的模型。

---

## 五、对话

### POST /api/chat/{name}

非流式对话。

**请求体**：
```json
{
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "thinking": "enabled",
  "reasoning_effort": "high",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

**可选参数**：
| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `thinking` | string | 思考模式: `"enabled"` / `"disabled"` |
| `reasoning_effort` | string | 思考强度: `"high"` / `"max"` |
| `tools` | array | 工具定义列表 |
| `tool_choice` | string | 工具选择策略 |
| `response_format` | string | 输出格式: `"json_object"` |
| `temperature` | float | 温度 (0~2) |
| `max_tokens` | int | 最大输出 token |
| `top_p` | float | 核采样 |
| `stop` | string/array | 停止序列 |

### POST /api/chat/{name}/stream

流式对话 (SSE)。参数同上，返回 SSE 流。

**SSE 格式**：
```
data: {"choices": [{"delta": {"content": "你好"}}]}

data: {"choices": [{"delta": {"content": "，我是"}}]}

data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}

data: [DONE]
```

思考模式时，每个 chunk 还包含 `reasoning_content` 字段。

---

## 六、DeepSeek 专用 API

### POST /api/deepseek/chat/{name}

DeepSeek 非流式对话（同 `/api/chat/{name}`，但返回格式为标准 DeepSeek API 格式）。

### POST /api/deepseek/chat/stream/{name}

DeepSeek 流式对话（标准 DeepSeek SSE 格式）。

### POST /api/deepseek/fim/{name}

FIM 代码补全端点。

### GET /api/deepseek/models

可用的 DeepSeek 模型列表。

### POST /api/deepseek/anthropic/messages

Anthropic Messages API 兼容端点。接收 Anthropic 格式请求，转换为 DeepSeek 格式处理。

**模型映射**：
| Anthropic 模型 | DeepSeek 模型 |
|:---------------|:--------------|
| `claude-opus-*` | `deepseek-v4-pro` |
| `claude-haiku-*` | `deepseek-v4-flash` |
| `claude-sonnet-*` | `deepseek-v4-flash` |

---

## 七、页面路由

| 路由 | 说明 |
|:-----|:------|
| `/` | 重定向到仪表盘 |
| `/dashboard` | 仪表盘页面 |
| `/models` | 模型库页面 |
| `/chat/deepseek` | DeepSeek 对话页 |
| `/chat/4b` | 本地 4B 对话页 |

---

## 八、数据模型

### ModelConfig

| 字段 | 类型 | 必填 | 说明 |
|:-----|:----:|:----:|:------|
| `name` | string | 是 | 显示名称（唯一标识） |
| `provider` | string | 是 | 提供商: `openai` / `ollama` / `llamacpp` |
| `api_base` | string | 是 | API 地址 |
| `model_id` | string | 否 | API 请求时用的模型 ID（默认 = name） |
| `real_name` | string | 否 | 真实名称（默认 = model_id） |
| `api_key_env` | string | 否 | API Key 环境变量名 |
| `type` | string | 否 | `api` / `local` |
| `temperature` | float | 否 | 温度 (默认 0.7) |
| `max_tokens` | int | 否 | 最大 Token (默认 4096) |
| `description` | string | 否 | 描述 |
| `notes` | string | 否 | 备注 |

### ModelStatus

| 字段 | 类型 | 说明 |
|:-----|:----:|:------|
| `name` | string | 模型名称 |
| `online` | bool | 是否在线 |
| `latency_ms` | float | 延迟 (毫秒) |
| `error` | string | 错误信息 |
| `provider` | string | 提供商 |
| `type` | string | 类型 |
| `description` | string | 描述 |
