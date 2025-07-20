-- Version 1: Initial schema setup

CREATE TABLE IF NOT EXISTS authors (
    author_id INTEGER PRIMARY KEY,
    author_name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS followers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    followed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, author_id),
    FOREIGN KEY(author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS author_posts (
    post_id INTEGER PRIMARY KEY,
    author_id INTEGER NOT NULL,
    created_at DATETIME NOT NULL,
    FOREIGN KEY(author_id) REFERENCES authors(author_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_last_view (
    user_id INTEGER PRIMARY KEY,
    last_viewed_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS competitions (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    last_submission_ids TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS competition_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    competition_message_id INTEGER NOT NULL,
    subscribed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, competition_message_id),
    FOREIGN KEY(competition_message_id) REFERENCES competitions(message_id) ON DELETE CASCADE
);

CREATE TRIGGER IF NOT EXISTS update_competitions_updated_at
AFTER UPDATE ON competitions
FOR EACH ROW
BEGIN
    UPDATE competitions SET updated_at = CURRENT_TIMESTAMP WHERE message_id = OLD.message_id;
END;

CREATE TABLE IF NOT EXISTS keyword_subscriptions (
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    followed_keywords TEXT,
    blocked_keywords TEXT,
    PRIMARY KEY (user_id, channel_id)
);