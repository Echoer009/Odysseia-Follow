-- 迁移脚本：创建 active_thread_members 表
-- version: 004

CREATE TABLE IF NOT EXISTS active_thread_members (
    thread_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    last_seen TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, user_id)
);

-- 为查询创建索引，可以提高性能
CREATE INDEX IF NOT EXISTS idx_user_id ON active_thread_members (user_id);
