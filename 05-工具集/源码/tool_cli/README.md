# tool-cli 统一工具管理

注册表驱动的 AI Agent 工具管理 CLI。

```
tool_cli/
├── tool                  # 入口点 (python3 tool search ...)
├── core/
│   ├── router.py         # 子命令发现+路由
│   ├── registry.py       # YAML注册表+健康检查
│   ├── base.py           # Command基类
│   └── display.py        # 输出格式化
├── actions/              # 子命令模块（自动发现）
│   └── search.py         # 搜索命令示例
└── registry/             # YAML工具定义
    └── edge-search.yaml  # 示例注册
```

## 快速开始

```bash
export TOOL_HOME="$(pwd)/tool_cli"
python3 tool_cli/tool -h            # 帮助
python3 tool_cli/tool registry list  # 工具清单
python3 tool_cli/tool search "hello" # 搜索
```

## 添加新命令

1. 在 `actions/` 下新建 `my_command.py`
2. 继承 `Command` 类，设置 `name` 和 `run()` 方法
3. 自动发现，无需注册

## 依赖

- Python 3.8+
- `pip install pyyaml`（注册表解析）
