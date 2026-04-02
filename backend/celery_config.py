# backend/celery_config.py - CELERY CONFIGURATION

import os
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


class CeleryConfig:
    broker_url = REDIS_URL
    result_backend = REDIS_URL

    task_serializer = "json"
    accept_content = ["json"]
    result_serializer = "json"
    timezone = "UTC"
    enable_utc = True

    task_track_started = True
    task_time_limit = 30 * 60
    task_soft_time_limit = 25 * 60

    worker_prefetch_multiplier = 4
    worker_max_tasks_per_child = 1000

    beat_schedule = {
        'cleanup-old-analyses': {
            'task': 'celery_tasks.cleanup_old_analyses',
            'schedule': crontab(hour=2, minute=0),
        },
        'reset-daily-limits': {
            'task': 'celery_tasks.reset_daily_rate_limits',
            'schedule': crontab(hour=0, minute=0),
        },
    }
