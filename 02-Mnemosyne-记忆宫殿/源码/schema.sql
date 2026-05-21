-- Mnemosyne 记忆宫殿 — 数据库 Schema v3.0
-- PostgreSQL 16 + pgvector 0.8+ + pg_trgm
-- 
-- 建库:
--   CREATE DATABASE mnemosyne;
--   \c mnemosyne
--   CREATE EXTENSION vector;
--   CREATE EXTENSION pg_trgm;
--   \i schema.sql

-- ══════════════════════════════════════════════════════
-- 核心记忆表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'fact',        -- fact|experience|belief|chat|work|note|test
    embedding VECTOR(1024),
    importance FLOAT DEFAULT 0.5,
    heat_score FLOAT DEFAULT 0.5,
    tier TEXT DEFAULT 'L2',             -- L1热|L2常温|L3冷|L4归档
    access_count INT DEFAULT 0,
    last_accessed TIMESTAMPTZ DEFAULT NOW(),
    is_deleted BOOLEAN DEFAULT FALSE,
    forgotten_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 向量索引 (HNSW, cosine distance)
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops)
    WITH (m=16, ef_construction=200);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_memories_lookup
    ON memories (user_id, tier, heat_score);
CREATE INDEX IF NOT EXISTS idx_memories_category
    ON memories (user_id, category);
CREATE INDEX IF NOT EXISTS idx_memories_deleted
    ON memories (is_deleted) WHERE is_deleted = true;

-- ══════════════════════════════════════════════════════
-- 多模态记忆表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS media_memories (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    content TEXT NOT NULL,
    media_type TEXT NOT NULL,            -- image|video|audio
    media_url TEXT,
    media_hash TEXT,
    embedding VECTOR(1024),
    importance FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_media_embedding
    ON media_memories USING hnsw (embedding vector_cosine_ops)
    WITH (m=16, ef_construction=200);
CREATE INDEX IF NOT EXISTS idx_media_user
    ON media_memories (user_id);

-- ══════════════════════════════════════════════════════
-- 元记忆追踪表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS memory_traces (
    id BIGSERIAL PRIMARY KEY,
    memory_id BIGINT REFERENCES memories(id) ON DELETE CASCADE,
    action TEXT NOT NULL,                -- stored|recalled|feedback|deleted|restored|merged
    details JSONB DEFAULT '{}',
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_memory ON memory_traces (memory_id);

-- ══════════════════════════════════════════════════════
-- 知识图谱表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT DEFAULT 'concept',  -- person|place|concept|event|object
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    target_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    rel_type TEXT DEFAULT 'related_to',
    strength FLOAT DEFAULT 0.5,
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id BIGINT REFERENCES memories(id) ON DELETE CASCADE,
    entity_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (memory_id, entity_id)
);

-- ══════════════════════════════════════════════════════
-- 知识文档表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    project_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024),
    tags TEXT[] DEFAULT '{}',
    source TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_docs_embedding
    ON documents USING hnsw (embedding vector_cosine_ops)
    WITH (m=16, ef_construction=200);

-- ══════════════════════════════════════════════════════
-- Wiki 表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS wiki_pages (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wiki_title ON wiki_pages USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS wiki_versions (
    id BIGSERIAL PRIMARY KEY,
    page_id BIGINT REFERENCES wiki_pages(id) ON DELETE CASCADE,
    version INT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════
-- 对话轮次表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS conversation_turns (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,                  -- user|assistant|system
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_session ON conversation_turns (user_id, session_id);

-- ══════════════════════════════════════════════════════
-- 用户和项目表
-- ══════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
