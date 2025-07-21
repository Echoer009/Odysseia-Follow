-- 迁移脚本：创建 thread_favorites 表
-- version: 003

CREATE TABLE IF NOT EXISTS thread_favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    thread_id INTEGER NOT NULL,
    thread_name TEXT NOT NULL,
    guild_id INTEGER NOT NULL,
    added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, thread_id)
);
