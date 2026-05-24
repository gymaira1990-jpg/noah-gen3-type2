-- NOAH-PRIME · PG 表结构初始化
-- 执行: psql -h localhost -U gcat -d noah_prime -f scripts/init_pg.sql

-- 1. pgvector 扩展（用于向量语义检索）
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. 知识条目（核心记忆库）
CREATE TABLE IF NOT EXISTS knowledge_entries (
    id SERIAL PRIMARY KEY,
    title TEXT,
    content TEXT NOT NULL,
    embedding vector(1024),
    category TEXT DEFAULT 'general',
    tags TEXT[] DEFAULT '{}',
    freq INTEGER DEFAULT 0,
    source TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. 精确信息（宪法/灵魂规则等结构化数据）
CREATE TABLE IF NOT EXISTS exact_info (
    key TEXT PRIMARY KEY,
    value TEXT,
    category TEXT DEFAULT 'soul',
    tags TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 4. API调用日志
CREATE TABLE IF NOT EXISTS api_call_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    model TEXT,
    tokens_used INTEGER DEFAULT 0,
    ticket_id TEXT DEFAULT '',
    response_summary TEXT DEFAULT ''
);

-- 5. 工单日志（TFC任务追踪）
CREATE TABLE IF NOT EXISTS tickets_log (
    id SERIAL PRIMARY KEY,
    ticket_id TEXT,
    status TEXT DEFAULT 'pending',
    memory_ids TEXT[] DEFAULT '{}',
    summary TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 6. 评分记录（自我进化数据）
CREATE TABLE IF NOT EXISTS score_records (
    id SERIAL PRIMARY KEY,
    ticket_id TEXT,
    efficiency FLOAT DEFAULT 0.0,
    accuracy FLOAT DEFAULT 0.0,
    resource_cost FLOAT DEFAULT 0.0,
    stability FLOAT DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 7. 索引
CREATE INDEX IF NOT EXISTS idx_ke_category ON knowledge_entries(category);
CREATE INDEX IF NOT EXISTS idx_ke_freq ON knowledge_entries(freq DESC);
CREATE INDEX IF NOT EXISTS idx_ke_source ON knowledge_entries(source);
CREATE INDEX IF NOT EXISTS idx_api_time ON api_call_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_api_ticket ON api_call_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_status ON tickets_log(status);
CREATE INDEX IF NOT EXISTS idx_ticket_created ON tickets_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_score_ticket ON score_records(ticket_id);
