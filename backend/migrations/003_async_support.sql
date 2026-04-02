-- Migration 003: Add async task tracking to analyses
-- Adds celery_task_id column and result_data JSONB column for storing
-- completed async task results that can be polled via /task/{task_id}.

ALTER TABLE analyses ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(255);
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS result_data JSONB;

CREATE INDEX IF NOT EXISTS idx_analyses_celery_task_id ON analyses(celery_task_id);
