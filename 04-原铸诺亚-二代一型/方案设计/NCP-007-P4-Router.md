# NCP-007: P4 Router

## 1. 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | NCP-007 |
| 模块名称 | P4 Router (AI路由引擎) |
| 当前版本 | v3.0.0-plan |
| 运行状态 | active |
| 保存槽位 | slot1 |
| 槽位标签 | "v3.0 架构方案完成, 待实施" |
| 槽位时间 | 2026-05-14 13:51 |
| 负责人 | 待确认 |
| 创建日期 | 2026-05-14 |

## 1.5 模块功能

### 定位
P4 Router (Provider Proxy Permutation Pipeline) 是原铸诺亚的 **AI API 智能路由管理层**。
作为多 Provider 间的统一请求调度中枢，负责所有对外 LLM API 调用的路由决策、健康监控、降级兜底。

### 核心能力

| 功能 | 说明 |
|:----|:------|
| **多 Provider 管理** | 统一管理 DeepSeek、OpenRouter、Ollama 本地等 Provider 的 API key、余额、端点 |
| **智能路由决策** | 按任务类型（聊天/嵌入/代码）自动选择最优 Provider |
| **降级链** | 主 Provider 不可用时自动降级到备选，兜底到本地 Ollama 模型 |
| **余额感知** | 实时监控各 Provider 余额，余额不足时自动移出路由池 |
| **延迟监控** | 追踪每次请求的响应延迟，作为路由评分因子 |
| **OpenAI 兼容 Server** | 提供 `/v1/chat/completions` 标准 OpenAI 格式接口 |
| **向量语义匹配** | （Phase 1 已实现）基于 PG pgvector 的路由偏好匹配 |
| **管理面板** | 可视化仪表盘，实时查看 Provider 状态和路由日志 |
| **定时优化** | 每日自动分析路由日志，优化路由参数（no-agent cron 脚本） |

### 架构层级

```
路由入口 → Phase 1·向量语义匹配 → Phase 2·硬规则 → Phase 3·成本排序 → Phase 4·健康过滤 → Phase 5·降级兜底 → 执行
                (pgvector)          (agent_id/关键词)   (免费优先)        (熔断/余额)        (本地 Ollama)
```

### 在 Hermes 中的角色
P4 Router 通过 `ai-provider-routing` skill 与 Hermes 对话引擎集成。Hermes 的 model routing 层调用 P4 做路由决策，P4 返回最优 Provider 后 Hermes 执行实际 API 调用。

## 2. 资源锚定

| 资源 | 路径 | 验证方法 |
|------|------|----------|
| 项目根目录 | ~/p4-router/ (1.2MB, 34 files) | `ls -la ~/p4-router/` |
| 路由引擎 | ~/p4-router/p4_router/core.py | `python -c "from p4_router.core import *; print('OK')"` |
| 降级链 | ~/p4-router/p4_router/chain.py | 待验证 |
| 向量匹配 | ~/p4-router/p4_router/vector_match.py | 待验证 |
| 管理API | ~/p4-router/p4_router/admin.py | 待验证 |
| 模拟器 | ~/p4-router/p4_router/simulator.py | 待验证 |
| 面板(静态) | ~/p4-router/p4_router/static/index.html | 待验证 |
| OpenAI兼容 | ~/p4-router/p4_router/server.py | 待验证 |
| 配置文件 | ~/p4-router/config/config.yaml | 待验证 |
| 包配置 | ~/p4-router/setup.py | 待验证 |
| 测试文件 | ~/p4-router/tests/test_p4_router.py | `python -m pytest ~/p4-router/tests/ -v` |
| Git分支 | 待验证 | `cd ~/p4-router && git branch` |

## 3. 模块接口

| 接口 | 端点/命令 | 说明 |
|------|-----------|------|
| OpenAI兼容API | `/v1/chat/completions` | 标准 OpenAI 格式路由 |
| 管理接口 | `/admin/*` | 路由管理、面板、状态查询 |
| CLI模拟 | `python -m p4_router simulate "..."` | 命令行模拟路由决策 |
| Skill调用 | `ai-provider-routing` | Hermes skill 集成入口 |

## 4. 开发状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| Phase 1: 向量语义匹配层 | ✅ 完成 | slot1 已保存 (2026-05-14) |
| Phase 2–7 | ⏳ 配置中 | 定义存在于 config.yaml，未实现 |

详细阶段划分：
- Phase 2: 硬规则匹配 (agent_id/关键词)
- Phase 3: 成本/能力排序 (免费优先)
- Phase 4: 实时健康过滤 (熔断/余额不足)
- Phase 5: 降级兜底 (本地 Ollama 模型)
- Phase 6: 监控与仪表盘
- Phase 7: 多租户与权限

## 5. 续接指令

> **用户**: 继续开发 NCP-007 P4 Router，从 Phase 2 开始实现硬规则匹配层。
>
> **AI**: 收到。NCP-007 当前停留在 Phase 1（向量语义匹配，slot1 存档）。
> 下一步硬规则匹配层涉及：
> 1. agent_id 精确路由
> 2. 关键词正则匹配
> 3. 规则优先级排序
> 4. 配置文件扩展
> 
> 是否需要我打开 ~/p4-router/ 并加载 config.yaml 查看当前 Phase 2 的定义？

## 6. 关联

| 关联类型 | 名称 | 路径/引用 |
|----------|------|-----------|
| Hermes Skill | `ai-provider-routing` | `~/.hermes/skills/core/ai-provider-routing/` |
| 设计蓝图 | AI路由模块原始设计 | `~/noah-档案馆/礼物/AI路由模块-设计蓝图.txt` |
| 吸收分析 | AI路由模块分析报告 | `~/noah-档案馆/礼物/AI路由模块-吸收分析报告.md` |
| 设计参考 | 蓝图参考 | `~/.hermes/skills/core/ai-provider-routing/references/design-blueprint.md` |
| 礼物归档 | 原始设计 TXT | `~/小诺亚的箱子/礼物-AI路由模块.txt` |

## 7. 变更日志

| 日期 | 变更 | 操作者 |
|------|------|--------|
| 2026-05-14 | 从审计报告创建模块定义文件 | 原铸诺亚 |
