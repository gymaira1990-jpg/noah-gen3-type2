# 原铸诺亚·二代一型 — API参考

> **NCP模块的调用接口与数据契约**

---

## 一、模块接口速查

### NCP-007 · P4 Router

| 端点 | 方法 | 说明 |
|:-----|:----:|:------|
| `/admin/routes` | GET | 路由表快照 |
| `/admin/route/{name}/disable` | POST | 禁用指定路由 |
| `/admin/route/{name}/enable` | POST | 启用指定路由 |

### NCP-010 · 记忆检索（MCP工具）

| 工具 | 参数 | 说明 |
|:-----|:------|:------|
| `search_knowledge(query, limit)` | query: str, limit: int | 语义检索知识库 |
| `create_entry(title, content, category, tags)` | 全部str | 创建知识条目 |
| `update_entry(entry_id, title, content, category)` | — | 更新条目 |
| `delete_entry(entry_id)` | int | 删除条目 |
| `knowledge_stats()` | — | 统计信息 |
| `list_recent_changes(hours, limit)` | — | 近期变更时间线 |

### NCP-012 · TFC任务系统

| 接口 | 方式 | 说明 |
|:-----|:----:|:------|
| TFC查询 | `psql -c "SELECT ... FROM tfc_tasks"` | 全部通过SQL |
| TFC创建 | `psql INSERT` | 手写SQL |
| TFC更新 | `psql UPDATE` | 改status/priority |

### NCP-013 · FC存档/灾备

| 接口 | 类型 | 说明 |
|:-----|:----:|:------|
| `noah-full-backup` | Hermes Skill | 全量灾备 |
| `noah-self-preservation` | Hermes Skill | 自保：温度迁移+版本管理 |

---

## 二、数据库Schema

### tfc_tasks 表

```sql
CREATE TABLE tfc_tasks (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT CHECK (status IN ('pending','active','done','completed','cancelled','abandoned')),
    priority TEXT CHECK (priority IN ('low','medium','high','critical')),
    project TEXT,
    description TEXT,
    tags TEXT[],                     -- 标签数组, GIN索引
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_tfc_tags ON tfc_tasks USING GIN (tags);
```

### knowledge_entries 表

```sql
CREATE TABLE knowledge_entries (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT,
    category TEXT,
    tags TEXT,
    source TEXT,
    embedding vector(1024),          -- qwen3-embedding:0.6b 1024维
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_knowledge_hnsw ON knowledge_entries 
    USING hnsw (embedding vector_cosine_ops) WITH (m='32', ef_construction='400');
```

### route_vectors 表 (P4 Router)

```sql
CREATE TABLE route_vectors (
    id SERIAL PRIMARY KEY,
    route_name TEXT UNIQUE,
    embedding vector(1024),
    metadata JSONB
);
CREATE INDEX idx_rv_hnsw ON route_vectors 
    USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='200');
```

### memory_store 表 (Hermes记忆插件)

```sql
CREATE TABLE memory_store (
    id SERIAL PRIMARY KEY,
    type TEXT CHECK (type IN ('memory','identity')),
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 三、版本注册表接口

> ⚠️ `version_registry` 表当前在PG中不存在（文档-代码偏差），以下为设计schema：

```sql
CREATE TABLE version_registry (
    id SERIAL PRIMARY KEY,
    ncp_id TEXT,               -- 如 'NCP-007'
    module_name TEXT,
    version TEXT,
    status TEXT,
    verified_at TIMESTAMP
);
```

---

## 四、相关配置文件路径

| 配置 | 路径 | 说明 |
|:-----|:-----|:------|
| Hermes 主配置 | `~/.hermes/config.yaml` | 模型、provider、MCP |
| Hermes 环境变量 | `~/.hermes/.env` | API密钥 |
| P4 Router 代码 | `~/p4-router/` | 独立工程 |
| 备份脚本 | `~/.hermes/scripts/noah-backup.sh` | OS cron驱动 |
| 快照更新 | `~/.hermes/scripts/原铸诺亚-快照更新.py` | 仪表盘数据源 |
| 钩子脚本 | `~/.hermes/scripts/noah-post-verify.py` | 安全门闸 |
