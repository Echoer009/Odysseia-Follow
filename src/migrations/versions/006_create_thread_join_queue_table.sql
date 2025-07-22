-- 创建一个新的表，用于存放需要机器人加入的帖子的队列
CREATE TABLE IF NOT EXISTS thread_join_queue (
    thread_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 为 guild_id 创建索引，以加快按服务器查询的速度
CREATE INDEX IF NOT EXISTS idx_thread_join_queue_guild_id ON thread_join_queue(guild_id);