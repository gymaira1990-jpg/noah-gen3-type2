# 06 · 诺亚核心 · 轻量模型管理与对话面板

> **pip install 即跑的 LLM 模型管理中心 — CLI + Web 双门**
> 🟢 生产运行 · ⚖️ MIT

---

> **Noah Core** — A lightweight LLM model management and chat panel.
> `pip install` 4 deps, `arc serve` for Web UI. Manages cloud APIs + local models (Ollama / llama.cpp / HuggingFace) in one place.

---

## 文档清单

| 文件 | 说明 |
|:-----|:------|
| 立项书.md | 🏆 项目背景 + 目标 + 边界 |
| 技术说明书.md | 📖 架构总览 + 模块拆解 + 设计哲学 |
| 接入指南.md | 🔌 从零安装到运行 |
| 学习指南.md | 🎓 核心设计决策 + 模块依赖 + 常见误区 |
| API参考.md | 📖 完整 REST API 文档 |

## 目录

```
源码/
├── core/                    # Python 核心模块（15 文件）
│   ├── kernel.py            # 数据模型 + YAML 配置
│   ├── models.py            # 模型 CRUD
│   ├── health.py            # 健康检查
│   ├── chat.py              # 对话引擎
│   ├── dashboard.py         # 仪表盘数据
│   ├── discovery.py         # 模型发现/搜索/下载
│   ├── cli.py               # CLI 入口（11 子命令）
│   ├── server.py            # Web 服务器
│   ├── handlers/            # FastAPI 路由（4 文件）
│   └── deepseek/            # DeepSeek 适配（7 文件）
│   └── static/templates/    # Web 前端（6 文件）
├── requirements.txt         # 依赖声明
└── arc.sh                   # CLI 快捷入口
```

## 快速体验

```bash
pip install pyyaml fastapi uvicorn jinja2
git clone ... 
cd 06-诺亚核心-模型管理与对话面板/源码
python -m core init   # 创建默认配置
python -m core serve  # 启动 Web 面板
# → 浏览器打开 http://localhost:8110
```

## 技术栈

| 层 | 选型 | 理由 |
|:---|:-----|:------|
| 后端 | Python 3.12 + FastAPI | 仅 4 个 pip 依赖 |
| 前端 | 原生 HTML/CSS/JS | 零构建，零 Node.js |
| 配置 | YAML | 人类可读，CLI 友好 |
| 对话协议 | OpenAI 兼容 | Ollama/llama.cpp/DeepSeek 通用 |
