-- MIGRATION: 007_add_status_to_join_queue.sql
-- Created at: 2025-07-23 03:55:00
-- Purpose: Add status and tracking columns to the thread_join_queue table
-- to prevent reprocessing of threads.

-- SQLite does not support ADD COLUMN with default values in older versions in a single statement.
-- The safest way is to recreate the table. However, for a simple queue that can be repopulated,
-- we can risk a simpler approach. A more robust approach for production would be to
-- create a new table, copy data, drop old table, and rename.
-- Given the nature of this table (a queue), we can simply add columns.

-- Add new columns to the thread_join_queue table
ALTER TABLE thread_join_queue ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE thread_join_queue ADD COLUMN last_attempted_at TIMESTAMP;

-- Create an index on the status column to speed up fetching pending tasks.
CREATE INDEX IF NOT EXISTS idx_thread_join_queue_status ON thread_join_queue(status);

-- Note: Existing rows will have 'pending' as their status.