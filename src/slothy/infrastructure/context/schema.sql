PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS context_observations (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    summary TEXT NOT NULL,
    token_count INTEGER NOT NULL CHECK (token_count >= 0),
    digest TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_scope ON context_observations(owner_id, session_id, task_id, created_at);
CREATE TABLE IF NOT EXISTS context_memories (
    id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    entities_json TEXT NOT NULL CHECK (json_valid(entities_json)),
    vector_json TEXT NOT NULL CHECK (json_valid(vector_json)),
    embedding_model TEXT NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX IF NOT EXISTS memories_owner_time ON context_memories(owner_id, created_at DESC);
