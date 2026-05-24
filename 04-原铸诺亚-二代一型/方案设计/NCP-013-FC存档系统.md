# NCP-013: FC存档系统

## 1. 元信息

| 字段 | 值 |
|------|-----|
| 模块编号 | NCP-013 |
| 模块名称 | FC存档系统 (Full Checkpoint Save System) |
| 当前版本 | v2.0.0 |
| 运行状态 | active |
| 保存槽位 | 4 (slot1 + auto1/auto2/auto3) |
| 项目根目录 | 无专用目录（Hermes Core Skill） |
| 负责人 | 待确认 |
| 创建日期 | 2026-05-14 |
| 版本验证 | 2026-05-15 — noah-full-backup skill `version:` 字段确认 |

### 保存槽位

| 槽位 | 类型 | 说明 |
|------|------|------|
| slot1 | 手动 | 由用户或开发流程触发保存 |
| auto1 | 自动 | 系统定时/事件驱动自动保存 |
| auto2 | 自动 | 系统定时/事件驱动自动保存 |
| auto3 | 自动 | 系统定时/事件驱动自动保存 |

## 2. 资源锚定

| 资源 | 路径 | 验证方法 |
|------|------|----------|
| Skill定义 | `~/.hermes/skills/core/fc-save-system/` | `ls -la ~/.hermes/skills/core/fc-save-system/` |
| Skill元数据 | skill manifest | `hermes skills info fc-save-system` |
| 存档数据存储 | 待验证 | 查看 skill 代码确认存储位置 |
| 存档内容 | 各 NCP 模块快照 | 待验证 |

注意：manifest 中 skill 名为 `fc-save-system`（非 `fc-save-system` 拼写），按实际目录名为准。

## 3. 模块接口

| 接口 | 说明 |
|------|------|
| 手动存档 | 保存当前模块状态到指定槽位 |
| 自动存档 | 定时/事件触发自动保存 |
| 存档列表 | 查看所有可用存档及标签 |
| 存档恢复 | 从指定槽位恢复模块状态 |
| Skill 调用 | `fc-save-system` skill 接口 |

## 4. 开发状态

| 状态 | 说明 |
|------|------|
| ✅ active | 存档系统正常运行 |
| 💾 4个槽位 | 1 手动 + 3 自动，覆盖基本存档需求 |

## 5. 续接指令

> **用户**: 保存 NCP-007 当前状态到 slot2。
>
> **AI**: 收到。执行 FC 存档：
> 1. 调用 `fc-save-system` skill
> 2. 目标：NCP-007 P4 Router
> 3. 槽位：slot2（当前已有 slot1 为 Phase 1存档）
> 4. 标签：需提供描述性标签
> 
> 需要我立即执行吗？请提供存档标签文字。

## 6. 关联

| 关联类型 | 名称 | 路径/引用 |
|----------|------|-----------|
| Hermes Skill | `fc-save-system` | `~/.hermes/skills/core/fc-save-system/` |
| 关联模块 | NCP-007 P4 Router | slot1 已保存 Phase 1 |
| 关联模块 | 所有 NCP (007-012) | 各模块皆可通过 FC 系统存档 |
| 关联模块 | NCP-010 记忆系统 | 存档可能存入记忆数据库 |

## 7. 变更日志

| 日期 | 变更 | 操作者 |
|------|------|--------|
| 2026-05-14 | 从审计报告创建模块定义文件 | 原铸诺亚 |
