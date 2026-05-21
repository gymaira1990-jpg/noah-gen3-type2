# Mnemosyne 记忆宫殿 · API 参考

> FastAPI 引擎公开的 REST 端点 (13 类, 33 个工具)

---

## 记忆 CRUD

### POST /memories — 存储记忆

```json
{
  "user_id": "string (必填)",
  "content": "string (必填)",
  "category": "fact|experience|belief|chat|work|note|test (默认: fact)",
  "project_id": "string (可选)",
  "importance": "float (0-1, 默认 0.5)"
}
→ {"id": 123, "status": "stored", "heat_score": 0.5}
```

### GET /memories/{id} — 获取单条

```
→ {id, user_id, content, category, heat_score, tier, 
   access_count, last_accessed, is_deleted, created_at, ...}
```

### GET /memories — 列出记忆

```
?user_id=xxx&category=fact&limit=10&offset=0&tier=L1
→ {results: [...], total: N}
```

### DELETE /memories/{id} — 软删除

```
→ {status: "deleted"}
```

### POST /memories/{id}/restore — 恢复已删除

```
→ {status: "restored"}
```

---

## 检索

### POST /memories/search — 语义搜索

```json
{
  "user_id": "string (必填)",
  "query": "string (必填)",
  "top_k": "int (默认 5, 最大 20)",
  "category": "string (可选)",
  "mode": "hybrid|semantic|fulltext (默认 hybrid)"
}
→ {results: [{id, content, category, heat_score, ...}], total: N}
```

### POST /memories/search-by-category — 按分类搜索

```json
{
  "user_id": "string (必填)",
  "query": "string (必填)",
  "category": "string (必填)",
  "top_k": "int (默认 5)"
}
→ {results: [...]}
```

### GET /memories/heat-top — 最热记忆

```
?user_id=xxx&limit=10&min_heat=0.0
→ [{id, content, heat_score, access_count, last_accessed}, ...]
```

---

## 记忆管理

### POST /memories/{id}/feedback — 反馈

```json
{
  "feedback": "positive|negative"
}
→ {status: "feedback_recorded", heat_adjustment: +0.1}
```

### GET /memories/{id}/traces — 操作轨迹

```
→ [{action, details, executed_at}, ...]
```

### POST /memories/evolve — 触发进化

```json
{
  "strategy": "consolidate|cleanup|boost (默认: consolidate)"
}
→ {status: "evolving", strategy: "...", processed: N}
```

### POST /memories/reflect — 触发反思

```json
{
  "mode": "light|deep (默认: light)"
}
→ {status: "reflecting", mode: "...", actions: [...]}
```

### GET /memories/stats — 健康报告

```
?user_id=system
→ {total, by_category: {...}, by_tier: {...}, 
   avg_heat, deleted_count, protected_count}
```

---

## 多模态

### POST /memories/multimodal — 存储多模态

```json
{
  "user_id": "string (必填)",
  "content": "string (必填) — 视觉理解的文本描述",
  "media_urls": ["string (可选) — 原始媒体链接"],
  "media_type": "image|video|audio (默认: image)"
}
→ {id: 123, status: "stored"}
```

### POST /memories/multimodal/search — 搜索多模态

```json
{
  "user_id": "string (必填)",
  "query": "string (必填)",
  "top_k": "int (默认 5)"
}
→ {results: [...]}
```

---

## 知识图谱

### POST /entities/extract — 实体提取

```json
{
  "user_id": "string (可选)",
  "limit": "int (默认 50)"
}
→ {entities_extracted: N, synced_to_age: true}
```

### GET /graph/search — 图遍历搜索

```
?query=xxx&user_id=xxx&max_hops=2
→ {nodes: [...], edges: [...]}
```

### POST /relationships — 创建关系

```json
{
  "user_id": "string (必填)",
  "source": "string (必填)",
  "target": "string (必填)",
  "rel_type": "string (默认 related_to)",
  "strength": "float (0-1, 默认 0.5)"
}
→ {status: "created", id: 123}
```

### GET /relationships/search — 搜索关系

```
?entity=xxx&user_id=xxx
→ [{source, target, rel_type, strength}, ...]
```

---

## Wiki

### POST /wiki — 创建 Wiki 页面

```json
{
  "user_id": "string (必填)",
  "title": "string (必填)",
  "content": "string (必填)"
}
→ {id: 123, status: "created"}
```

### GET /wiki/search — 搜索 Wiki

```
?query=xxx&user_id=xxx&top_k=5
→ [{id, title, snippet, ...}]
```

### GET /wiki/{id} — 获取 Wiki 页面

```
→ {id, title, content, version, created_at, updated_at}
```

---

## 知识文档

### POST /documents — 上传文档

```json
{
  "user_id": "string (必填)",
  "title": "string (必填)",
  "content": "string (必填)",
  "project_id": "int (可选)"
}
→ {id: 123, status: "uploaded"}
```

### GET /documents/search — 搜索文档

```
?query=xxx&user_id=xxx&top_k=5
→ [{id, title, snippet, ...}]
```

---

## 项目

### POST /projects — 创建项目

```json
{
  "user_id": "string (必填)",
  "name": "string (必填)",
  "description": "string (可选)"
}
→ {id: 123, status: "created"}
```

### GET /projects — 列出项目

```
?user_id=xxx
→ [{id, name, description, created_at}, ...]
```

---

## 上下文工具

### POST /compress — LLMLingua 压缩文本

```json
{
  "text": "string (必填)",
  "ratio": "float (0-1, 默认 0.5)"
}
→ {compressed: "..."}
```

### POST /conversations — 存储对话轮次

```json
{
  "user_id": "string (必填)",
  "session_id": "string (必填)",
  "role": "user|assistant",
  "content": "string (必填)"
}
→ {id: 123, status: "stored"}
```

### GET /conversations/search — 搜索对话

```
?user_id=xxx&session_id=xxx&limit=50
→ {messages: [...]}
```

---

## 数据模型

### memories 表核心字段

| 字段 | 类型 | 说明 |
|:-----|:-----|:-----|
| id | BIGSERIAL | 主键 |
| user_id | TEXT | 用户 ID |
| project_id | TEXT | 项目隔离域 |
| content | TEXT | 记忆内容 |
| category | TEXT | fact/experience/belief/chat/work/note/test |
| embedding | VECTOR(1024) | 向量嵌入 (HNSW 索引) |
| importance | FLOAT | 重要性 0~1 |
| heat_score | FLOAT | 热度得分 (四层) |
| tier | TEXT | L1/L2/L3/L4 |
| is_deleted | BOOLEAN | 软删除标记 |
| forgotten_at | TIMESTAMPTZ | 遗忘时间 |
| metadata | JSONB | 扩展元数据 |
