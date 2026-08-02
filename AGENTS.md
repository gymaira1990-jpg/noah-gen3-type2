# noah-gen3-type2 仓库治理规范

## 本仓库是做什么的

诺亚三代二型（noah-gen3-type2）：通用型 AI 认知架构。
从【原铸诺亚】数万轮实战对话中萃取，面向下一代 AI Agent 的通用解决方案。
包含：上下文管理组装系统、Mnemosyne 记忆宫殿（已独立为 Mnemosyne OS）、认知 AI 底座、原铸诺亚（已爆炸仅供参考）、工具集、诺亚核心模型管理与对话面板。

## 目录与命名规范

- 顶级子项目用 `NN-名称/` 编号前缀（01-上下文管理 / 02-Mnemosyne / ... / 06-诺亚核心）
- 02-Mnemosyne 已独立为 Mnemosyne OS，本仓库仅保留迁移通知
- 新增大类/子项目必须同步更新 README 的目录树 + 项目清单表格

## 发布流程（公开仓库红线）

1. **隐私审计**：push 前扫描本地用户名路径 / 真实 IP / API Key / token 模式，0 命中才可 push
2. **密钥规范**：API Key 一律 `os.environ.get("XXX_API_KEY", "")` 读取，禁止硬编码
3. **仓库治理门禁**：LICENSE / .github 五件套 / AGENTS.md / CHANGELOG.md 齐全
4. **只推 GitHub**：唯一 remote = origin（gymaira1990-jpg）。ATomGIT 已废弃 (2026-08-03)
5. 用经典 PAT（ghp_）push，细粒度 PAT 仅 API 读操作

## 提交规范

- 格式：`类型: 描述`（feat/fix/docs/refactor/security/chore）
- 禁止提交：.env / .pem / .key / .bak / 模型文件 / 保险柜内容
- 提交前 `git status` 确认无遗漏，重要节点打 tag

## 禁止事项

- ❌ 不提交真实服务器 IP、SSH 配置、API 密钥、本地路径
- ❌ 不硬编码 DEEPSEEK_API_KEY 等密钥（必须环境变量）
- ❌ 不用旧 workspace 覆盖线上（先拉取对比）
