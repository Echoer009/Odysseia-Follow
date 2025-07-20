-- Version 2: Add is_subscribed to keyword_subscriptions
-- This migration was previously handled by a hardcoded Python function.

-- Add the column, but only if it doesn't already exist.
-- NOTE: Standard SQL doesn't have a clean "ADD COLUMN IF NOT EXISTS".
-- The migration runner logic in Python will handle checking the schema version
-- to prevent this from running on a database that already has this structure.
ALTER TABLE keyword_subscriptions ADD COLUMN is_subscribed BOOLEAN NOT NULL DEFAULT 0;