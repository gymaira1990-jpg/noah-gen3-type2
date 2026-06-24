# 🏰 Mnemosyne · 记忆宫殿

> ⚠️ **项目迁移通知 (2026-06-25)**
> 
> **本项目已正式立项为独立产品 "Mnemosyne OS v5.0"，搬迁至独立仓库维护。**
> 
> 🔗 **新仓库:** [github.com/gymaira1990-jpg/Mnemosyne-OS](https://github.com/gymaira1990-jpg/Mnemosyne-OS)
> 
> **本目录 (02-Mnemosyne-记忆宫殿) 不再更新。** 所有后续开发、版本发布、文档更新请在 Mnemosyne OS 独立仓库进行。
>
> ---
>
> Noah 认知架构的永久记忆子系统

## 概述

Mnemosyne（记忆宫殿）是 Noah AI 认知架构的记忆子系统，提供多层级记忆管理、语义检索、热度排序和自动提炼能力。本目录是 Mnemosyne 项目的**公开文档与源码**。

> ⚠️ **本地开发版本**（含服务器配置、部署脚本、运维记录）在 `/opt/data/workspace/记忆宫殿/`，不包含在公开仓库中。

## 目录结构

| 目录/文件 | 说明 |
|-----------|------|
| `架构设计/` | Mnemosyne v2.1 TMT 层级记忆系统设计文档、升级路线图、外部系统调研 |
| `TMT层级记忆系统/` | 5 级时间记忆树设计：碎片→会话→每日→每周→画像 |
| `MCP桥接/` | Hermes Agent ↔ Mnemosyne 的 MCP 桥接工具（Python） |
| `源码/` | Mnemosyne 服务端核心源码（FastAPI + PostgreSQL） |
| `日常运维/` | 通用运维示例脚本（不含服务器特定配置） |
| `产品说明书.md` | Mnemosyne 产品功能说明 |
| `开源版发布方案.md` | 开源版本发布计划 |
| `版本分析报告.md` | 版本演进分析 |

## TMT 5 级记忆树

```
L1 碎片 (memories)    ← 单条对话记忆（自动存储）
L2 会话 (tmt_sessions) ← 整轮对话摘要（每10分钟自动提炼）
L3 每日 (tmt_daily)    ← 跨会话主题提炼（每日一次）
L4 每周 (tmt_weekly)   ← 模式/趋势综合（每周一次）
L5 画像 (tmt_profiles) ← 人设/偏好固化（每月一次）
```

## 关联项目

- [noah-gen3-type2](https://github.com/gymaira1990-jpg/noah-gen3-type2) — 主项目
- 本地开发工作区: `/opt/data/workspace/记忆宫殿/`
