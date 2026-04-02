# backend/celery_tasks.py - ASYNC TASK QUEUE

import os
import sys
import time
import hashlib
from datetime import datetime

# Ensure task process can import local package modules when cwd is not /app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from celery import Celery
from celery.schedules import crontab
from celery.utils.log import get_task_logger
from sqlalchemy import func
from database import SessionLocal, Analysis
from cache import set_analysis_cache

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "codeflow",
    broker=REDIS_URL,
    backend=REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,
    task_soft_time_limit=25 * 60,
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    beat_schedule={
        'cleanup-old-analyses': {
            'task': 'celery_tasks.cleanup_old_analyses',
            'schedule': crontab(hour=2, minute=0),
        },
        'reset-daily-limits': {
            'task': 'celery_tasks.reset_daily_rate_limits',
            'schedule': crontab(hour=0, minute=0),
        },
    },
)

logger = get_task_logger(__name__)
logger.info(f"celery_tasks cwd={os.getcwd()}, sys.path[0]={[sys.path[0]]}, top_path={sys.path[:5]}")


@celery_app.task(bind=True, max_retries=3)
def analyze_code_task(
    self,
    user_id: int,
    api_key_id: int,
    language: str,
    code: str,
    ip_address: str,
    user_agent: str,
    code_hash: str = None,
    analysis_id: int = None
):
    """Async code analysis task"""
    db = SessionLocal()
    start_time = time.time()

    try:
        # If a pre-created Analysis row exists, mark it as processing
        if analysis_id:
            analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            if analysis:
                analysis.status = "processing"
                db.commit()

        logger.info(f"Starting analysis: user={user_id}, language={language}, size={len(code)}")

        if language == "python":
            from parsers.python_parser import parse
        elif language == "c":
            from parsers.c_parser import parse
        elif language == "cpp":
            from parsers.cpp_parser import parse
        elif language == "java":
            from parsers.java_parser import parse
        elif language == "javascript":
            from parsers.js_parser import parse
        else:
            raise ValueError(f"Unsupported language: {language}")

        result = parse(code)
        execution_time_ms = int((time.time() - start_time) * 1000)

        if analysis_id:
            # Update the pre-created row
            analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
            if analysis:
                analysis.code_hash = code_hash or hashlib.sha256(code.encode()).hexdigest()
                analysis.node_count = len(result.get("nodes", []))
                analysis.edge_count = len(result.get("edges", []))
                analysis.loop_count = len(result.get("loops", []))
                analysis.conditional_count = len(result.get("conditionals", []))
                analysis.execution_time_ms = execution_time_ms
                analysis.status = "success" if not result.get("error") else "error"
                analysis.error_message = result.get("error")
                analysis.result_data = result
                db.commit()
                logger.info(f"Analysis updated: id={analysis.id}, status={analysis.status}")
        else:
            # Legacy path: create a new Analysis row
            analysis = Analysis(
                user_id=user_id,
                api_key_id=api_key_id,
                language=language,
                code_hash=code_hash or hashlib.sha256(code.encode()).hexdigest(),
                code_length=len(code),
                node_count=len(result.get("nodes", [])),
                edge_count=len(result.get("edges", [])),
                loop_count=len(result.get("loops", [])),
                conditional_count=len(result.get("conditionals", [])),
                execution_time_ms=execution_time_ms,
                status="success" if not result.get("error") else "error",
                error_message=result.get("error"),
                result_data=result,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            db.add(analysis)
            db.commit()
            logger.info(f"Analysis saved: id={analysis.id}, status={analysis.status}")

        set_analysis_cache(language, code, result)

        return {
            "analysis_id": analysis.id,
            "status": "success",
            "data": result,
            "execution_time_ms": execution_time_ms
        }

    except Exception as exc:
        logger.exception(f"Analysis failed: {exc}")

        try:
            if analysis_id:
                analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
                if analysis:
                    analysis.execution_time_ms = int((time.time() - start_time) * 1000)
                    analysis.status = "error"
                    analysis.error_message = str(exc)[:500]
                    db.commit()
            else:
                analysis = Analysis(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    language=language,
                    code_length=len(code),
                    execution_time_ms=int((time.time() - start_time) * 1000),
                    status="error",
                    error_message=str(exc)[:500],
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                db.add(analysis)
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to save error analysis row")

        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    finally:
        db.close()


@celery_app.task
def cleanup_old_analyses():
    """Cleanup task: delete analyses older than 90 days"""
    from datetime import timedelta

    db = SessionLocal()
    cutoff_date = datetime.utcnow() - timedelta(days=90)

    try:
        deleted = db.query(Analysis).filter(
            Analysis.created_at < cutoff_date
        ).delete()

        db.commit()
        logger.info(f"Cleaned up {deleted} old analyses")

    except Exception as e:
        logger.exception(f"Cleanup failed: {e}")
        db.rollback()

    finally:
        db.close()


@celery_app.task
def reset_daily_rate_limits():
    """Log daily usage stats. Rate limits reset automatically via date-scoped queries."""
    db = SessionLocal()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stats = db.query(Analysis.user_id, func.count(Analysis.id)).filter(
            Analysis.created_at >= today_start
        ).group_by(Analysis.user_id).all()
        logger.info(f"Daily usage stats: {len(stats)} active users today, "
                    f"total requests: {sum(c for _, c in stats)}")
    except Exception as e:
        logger.exception(f"reset_daily_rate_limits failed: {e}")
    finally:
        db.close()
