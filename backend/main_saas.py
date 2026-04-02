# backend/main.py - SAAS VERSION WITH DATABASE + QUEUE

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
import os
import logging
from typing import Optional
from slowapi import Limiter
from slowapi.util import get_remote_address
from prometheus_client import Counter, Summary, start_http_server
from datetime import datetime, timedelta

from database import get_db, APIKey, Analysis
from celery_tasks import celery_app, analyze_code_task

# ----------------------------
# Logging
# ----------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("codeflow")

# ----------------------------
# Prometheus Metrics
# ----------------------------

REQUESTS_TOTAL = Counter(
    'codeflow_requests_total',
    'Total requests',
    ['endpoint', 'status']
)
QUEUE_LENGTH = Counter(
    'codeflow_queue_length',
    'Current task queue length'
)
ANALYSIS_TIME = Summary(
    'codeflow_analysis_seconds',
    'Analysis time'
)

# ----------------------------
# Environment
# ----------------------------

API_SECRET = os.getenv("API_SECRET", "change-in-production")
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5500").split(",")
MAX_CODE_SIZE = 50_000
MAX_LOOPS = 50

logger.info("Starting CodeFlow3D SaaS Backend")
logger.info(f"Allowed origins: {ALLOWED_ORIGINS}")

# ----------------------------
# FastAPI App
# ----------------------------

app = FastAPI(
    title="CodeFlow3D SaaS API",
    description="Multi-tenant code flow visualization SaaS",
    version="2.0.0"
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# Models
# ----------------------------


class AnalyzeRequest(BaseModel):
    language: str
    code: str
    title: Optional[str] = None
    save_graph: bool = False


class AnalyzeResponse(BaseModel):
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


class UserRegister(BaseModel):
    username: str
    email: str
    password: str


class APIKeyCreate(BaseModel):
    name: str
    rate_limit_per_minute: int = 10
    rate_limit_per_day: int = 1000

# ----------------------------
# Authentication
# ----------------------------


def verify_api_key(request: Request, db: Session = Depends(get_db)):
    """
    Verify API key from header and get associated user
    """
    api_key_str = request.headers.get("x-api-key")

    if not api_key_str:
        logger.warning(f"Missing API key from {request.client.host}")
        raise HTTPException(status_code=401, detail="Missing x-api-key header")

    # Look up API key in database
    api_key = db.query(APIKey).filter(
        APIKey.key == api_key_str,
        APIKey.revoked_at.is_(None)
    ).first()

    if not api_key:
        logger.warning(f"Invalid API key attempt from {request.client.host}")
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked API key")

    # Check if user is active
    if not api_key.user.is_active:
        logger.warning(f"Inactive user: {api_key.user.id}")
        raise HTTPException(status_code=403, detail="User account is inactive")

    # Update last used
    api_key.last_used_at = datetime.utcnow()
    db.commit()

    return api_key

# ----------------------------
# Validation
# ----------------------------


def validate_code_complexity(code: str):
    """Guard against resource exhaustion"""
    loop_count = code.count("for") + code.count("while") + code.count("do")

    if loop_count > MAX_LOOPS:
        raise HTTPException(
            status_code=400,
            detail=f"Code too complex: {loop_count} loops (max {MAX_LOOPS})"
        )


def check_rate_limit(api_key: APIKey, db: Session):
    """Check per-API-key rate limits"""
    # Check per-minute limit
    minute_ago = datetime.utcnow() - timedelta(minutes=1)
    recent_count = db.query(Analysis).filter(
        Analysis.api_key_id == api_key.id,
        Analysis.created_at > minute_ago
    ).count()

    if recent_count >= api_key.rate_limit_per_minute:
        raise HTTPException(
            status_code=429, detail=f"Rate limit exceeded: {
                api_key.rate_limit_per_minute} requests per minute")

    # Check per-day limit
    day_ago = datetime.utcnow() - timedelta(days=1)
    daily_count = db.query(Analysis).filter(
        Analysis.api_key_id == api_key.id,
        Analysis.created_at > day_ago
    ).count()

    if daily_count >= api_key.rate_limit_per_day:
        raise HTTPException(
            status_code=429, detail=f"Daily limit exceeded: {
                api_key.rate_limit_per_day} requests per day")

# ----------------------------
# Endpoints: Health
# ----------------------------


@app.get("/ping")
async def ping():
    REQUESTS_TOTAL.labels(endpoint="ping", status="success").inc()
    return {"status": "pong"}


@app.get("/")
async def root():
    return {
        "message": "CodeFlow3D SaaS API v2.0",
        "docs": "/docs",
        "health": "/ping"
    }

# ----------------------------
# Endpoints: Analysis (Async)
# ----------------------------


@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("30/minute")
async def analyze(
    request: AnalyzeRequest,
    request_obj: Request,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key)
):
    """
    Async code analysis endpoint

    Returns task_id for polling results
    """
    REQUESTS_TOTAL.labels(endpoint="analyze", status="started").inc()

    try:
        # Validate input
        if len(request.code) > MAX_CODE_SIZE:
            raise HTTPException(status_code=413, detail="Code too large")

        validate_code_complexity(request.code)

        # Check rate limits
        check_rate_limit(api_key, db)

        # Queue analysis task
        task = analyze_code_task.delay(
            user_id=api_key.user_id,
            api_key_id=api_key.id,
            language=request.language,
            code=request.code,
            ip_address=request_obj.client.host,
            user_agent=request_obj.headers.get("user-agent", "")
        )

        logger.info(
            f"Analysis queued: task_id={
                task.id}, user={
                api_key.user_id}")
        REQUESTS_TOTAL.labels(endpoint="analyze", status="queued").inc()

        return AnalyzeResponse(
            task_id=task.id,
            status="queued",
            message="Analysis queued. Check status with /analyze/{task_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Analyze error: {e}")
        REQUESTS_TOTAL.labels(endpoint="analyze", status="error").inc()
        raise HTTPException(status_code=500, detail=str(e)[:100])

# ----------------------------
# Endpoints: Task Status
# ----------------------------


@app.get("/analyze/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key)
):
    """
    Get status of queued analysis task
    """
    task = celery_app.AsyncResult(task_id)

    if task.state == "PENDING":
        return TaskStatusResponse(
            task_id=task_id,
            status="pending",
            message="Task is queued"
        )
    elif task.state == "SUCCESS":
        return TaskStatusResponse(
            task_id=task_id,
            status="success",
            result=task.result
        )
    elif task.state == "FAILURE":
        return TaskStatusResponse(
            task_id=task_id,
            status="failed",
            error=str(task.info)
        )
    else:
        return TaskStatusResponse(
            task_id=task_id,
            status=task.state.lower()
        )

# ----------------------------
# Endpoints: History
# ----------------------------


@app.get("/history")
async def get_analysis_history(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key)
):
    """
    Get user's analysis history
    """
    analyses = db.query(Analysis).filter(
        Analysis.user_id == api_key.user_id
    ).order_by(
        Analysis.created_at.desc()
    ).limit(limit).offset(offset).all()

    return {
        "total": db.query(Analysis).filter(
            Analysis.user_id == api_key.user_id
        ).count(),
        "limit": limit,
        "offset": offset,
        "analyses": [
            {
                "id": a.id,
                "language": a.language,
                "status": a.status,
                "node_count": a.node_count,
                "execution_time_ms": a.execution_time_ms,
                "created_at": a.created_at.isoformat()
            }
            for a in analyses
        ]
    }

# ----------------------------
# Startup/Shutdown
# ----------------------------


@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("🚀 CodeFlow3D SaaS Backend Starting")
    logger.info("📊 Queue: Redis")
    logger.info("💾 Database: PostgreSQL")
    logger.info("🔐 Authentication: API Keys (per-user)")
    logger.info("=" * 60)

    try:
        start_http_server(9100)
        logger.info("Prometheus metrics on :9100")
    except Exception as e:
        logger.warning(f"Prometheus failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Backend shutting down")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
