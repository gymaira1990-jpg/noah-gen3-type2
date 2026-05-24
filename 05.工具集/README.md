# 05 · AI 智能工具集

> 🛠️ 浏览器 CDP 控制 · 统一工具管理 · 智能搜索管线

## 文档

| 文件 | 说明 |
|:-----|:------|
| [技术说明书.md](./技术说明书.md) | 🏆 系统介绍：架构、组件、核心指标 |
| [学习指南.md](./学习指南.md) | 🎓 架构设计、核心算法、常见误区 |
| [接入指南.md](./接入指南.md) | 🔌 10 分钟集成、最小示例、验证清单 |
| [API参考.md](./API参考.md) | 📖 完整接口文档、数据模型、返回格式 |
| [立项书.md](./立项书.md) | 📄 背景、目标、不做什么 |

## 源码

| 文件/目录 | 行数 | 说明 |
|:----------|:----:|:------|
| [edge_cdp.py](./源码/edge_cdp.py) | ~260 | 纯 stdlib CDP 浏览器控制 |
| [tool_cli/](./源码/tool_cli/) | ~456 | 统一工具管理 CLI 系统 |

### tool CLI 架构

```
源码/tool_cli/
├── tool                  ← 入口点
├── core/
│   ├── router.py         ← 子命令自动发现
│   ├── registry.py       ← YAML 注册表+健康检查
│   ├── base.py           ← Command 基类
│   └── display.py        ← 输出格式化
├── actions/
│   └── search.py         ← 搜索命令示例
└── registry/
    └── edge-search.yaml  ← 工具注册示例
```

## 使用速览

```bash
# 1. 浏览器启动（带 CDP）
msedge.exe --remote-debugging-port=9222

# 2. 搜索
python3 源码/edge_cdp.py search "大语言模型"

# 3. 抓取
python3 源码/edge_cdp.py crawl "https://example.com"
```

## 状态

| 指标 | 数据 |
|:-----|:-----|
| 核心工具 | Edge CDP + 工具CLI + 健康监控 |
| 代码量 | ~260 行 (Python, 零依赖) + ~230 行 (Bash) |
| 搜索引擎 | 百度/Google/Bing 三引擎 |
