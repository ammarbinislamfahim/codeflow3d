# backend/main.py - COMPLETE PRODUCTION BACKEND

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, Field, field_validator
import os
import re
import time
import logging
from typing import Optional
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Summary, start_http_server
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from database import get_db, init_db, User, APIKey, Analysis, Subscription, SavedGraph, SiteSettings, SITE_SETTINGS_DEFAULTS
from auth.security import (
    hash_password, verify_password,
    generate_api_key, hash_api_key,
    create_access_token, verify_token
)
from cache import get_cached_analysis, set_analysis_cache, get_code_hash

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("codeflow")

# Metrics
REQUESTS_TOTAL = Counter(
    'codeflow_requests_total',
    'Total requests',
    ['endpoint', 'status']
)
CACHE_HITS = Counter('codeflow_cache_hits_total', 'Cache hits')
ANALYSIS_TIME = Summary('codeflow_analysis_seconds', 'Analysis time')

# Config
ALLOWED_ORIGINS = [
    o.strip() for o in
    os.getenv("ALLOWED_ORIGINS", "http://localhost:5500").split(",")
    if o.strip()
]
MAX_CODE_SIZE = 50_000
MAX_LOOPS = 150
ASYNC_THRESHOLD = 10_000  # Code larger than this (chars) is dispatched to Celery

logger.info("🚀 CodeFlow3D Backend Starting")
logger.info("Allowed origins: %s", ALLOWED_ORIGINS)


@asynccontextmanager
async def lifespan(app):
    logger.info("=" * 60)
    logger.info("CodeFlow3D Final Production Backend")
    logger.info("Password hashing: bcrypt")
    logger.info("API key hashing: SHA256")
    logger.info("Caching: Redis")
    logger.info("Async: Celery + Redis")
    logger.info("Billing: Plan-based limits")
    logger.info("=" * 60)
    # Create tables if they don't exist
    init_db()
    logger.info("Database tables ensured")
    # Auto-seed admin user if ADMIN_EMAIL is set (for hosts without shell access)
    if os.getenv("ADMIN_EMAIL"):
        try:
            from seed_admin import seed
            seed()
            logger.info("Admin seed check completed")
        except Exception as e:
            logger.warning(f"Admin seed failed: {e}")
    try:
        start_http_server(9100)
        logger.info("Prometheus metrics on :9100")
    except OSError:
        pass  # Expected: other gunicorn workers already hold port 9100
    except Exception as e:
        logger.warning(f"Prometheus failed: {e}")
    yield
    logger.info("Backend shutting down")


# FastAPI
app = FastAPI(title="CodeFlow3D SaaS API", version="3.0.0", lifespan=lifespan)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models


_ALLOWED_LANGUAGES = {"python", "c", "cpp", "java", "javascript", "typescript"}


def _validate_email_strict(email: str) -> str:
    """Normalize and strictly validate an email address."""
    email = email.strip().lower()
    if not re.match(r'^[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}$', email):
        raise ValueError("Invalid email address")
    domain = email.split('@')[1]
    if domain in {
        'test.com', 'example.com', 'example.org', 'example.net',
        'invalid.com', 'localhost', 'tempmail.com',
        'throwaway.email', 'mailinator.com', 'guerrillamail.com',
        'sharklasers.com', 'yopmail.com', 'trashmail.com',
    }:
        raise ValueError("Disposable or invalid email domains are not allowed")
    return email


def _validate_username(username: str) -> str:
    """Validate username: starts with letter, 3-64 chars, alphanumeric/_ /-, no consecutive special."""
    if len(username) < 3 or len(username) > 64:
        raise ValueError("Username must be 3–64 characters")
    if not re.match(r'^[a-zA-Z]', username):
        raise ValueError("Username must start with a letter")
    if not re.match(r'^[a-zA-Z0-9_\-]+$', username):
        raise ValueError("Username can only contain letters, numbers, _ and -")
    if re.search(r'[_\-]{2}', username):
        raise ValueError("Username cannot have consecutive _ or -")
    return username


class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def username_rules(cls, v: str) -> str:
        return _validate_username(v)

    @field_validator("email")
    @classmethod
    def email_strict(cls, v: str) -> str:
        return _validate_email_strict(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        from auth.security import validate_password_strength
        failures = validate_password_strength(v)
        if failures:
            raise ValueError("Password requirements not met: " + "; ".join(failures))
        return v


class UserLogin(BaseModel):
    login: str = Field(min_length=1, description="Email or username")
    password: str


class AnalyzeRequest(BaseModel):
    language: str
    code: str

    @field_validator("language")
    @classmethod
    def language_must_be_supported(cls, v: str) -> str:
        if v not in _ALLOWED_LANGUAGES:
            raise ValueError(f"language must be one of {sorted(_ALLOWED_LANGUAGES)}")
        return v


class AnalyzeResponse(BaseModel):
    task_id: Optional[str] = None
    status: str = "success"
    cached: bool = False
    nodes: Optional[list] = None
    edges: Optional[list] = None
    loops: Optional[list] = None
    conditionals: Optional[list] = None
    call_edges: Optional[list] = None
    function_groups: Optional[dict] = None
    unused_functions: Optional[list] = None
    error: Optional[str] = None
    error_line: Optional[int] = None


class SaveGraphRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    code: str
    language: str
    graph_data: dict
    is_public: bool = False


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)

# Auth


def verify_api_key_dep(request: Request, db: Session = Depends(get_db)):
    """Verify API key and return associated user"""
    api_key_str = request.headers.get("x-api-key")

    if not api_key_str:
        logger.warning(f"Missing API key from {request.client.host}")
        raise HTTPException(status_code=401, detail="Missing x-api-key header")

    key_hash = hash_api_key(api_key_str)
    api_key = db.query(APIKey).filter(
        APIKey.key_hash == key_hash,
        APIKey.revoked_at.is_(None)
    ).first()

    if not api_key:
        logger.warning(f"Invalid API key from {request.client.host}")
        raise HTTPException(status_code=401, detail="Invalid API key")

    if not api_key.user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")

    now = datetime.now(timezone.utc)
    if not api_key.last_used_at or (now - api_key.last_used_at).total_seconds() > 60:
        api_key.last_used_at = now
        db.commit()

    return api_key

# Revoked key cleanup

def prune_revoked_keys(user_id: int, db: Session, keep: int = 5):
    """Delete old revoked API keys for a user, keeping only the most recent `keep`."""
    revoked = db.query(APIKey).filter(
        APIKey.user_id == user_id,
        APIKey.revoked_at.isnot(None)
    ).order_by(APIKey.revoked_at.desc()).all()
    if len(revoked) > keep:
        for old_key in revoked[keep:]:
            db.delete(old_key)
        db.commit()
        logger.info(f"Pruned {len(revoked) - keep} old revoked keys for user {user_id}")

# Plan enforcement


def check_plan_limits(user: User, db: Session):
    """Enforce subscription plan limits"""
    sub = db.query(Subscription).filter_by(user_id=user.id).first()

    if not sub:
        sub = Subscription(user_id=user.id, plan="free", requests_per_day=100)
        db.add(sub)
        db.commit()

    today = datetime.now(timezone.utc).date()
    today_start = datetime(today.year, today.month, today.day)

    today_count = db.query(Analysis).filter(
        Analysis.user_id == user.id,
        Analysis.created_at >= today_start
    ).count()

    if today_count >= sub.requests_per_day:
        logger.warning(f"Rate limit exceeded for user {user.id}: {sub.plan}")
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit reached ({sub.requests_per_day} requests)"
        )

# Endpoints


@app.get("/ping")
async def ping():
    REQUESTS_TOTAL.labels(endpoint="ping", status="success").inc()
    return {"status": "pong"}


@app.get("/")
async def root():
    return {
        "message": "CodeFlow3D SaaS API v3.0",
        "docs": "/docs",
        "health": "/ping"
    }


@app.get("/test")
async def test_flow():
    logger.info("Test endpoint")
    return {
        "nodes": [
            {"id": "n0", "label": "START"},
            {"id": "n1", "label": "Function: main()"},
            {"id": "n2", "label": "if condition"},
            {"id": "n3", "label": "for loop"},
            {"id": "n4", "label": "call: printf"},
            {"id": "n5", "label": "return"},
        ],
        "edges": [
            {"from": "n0", "to": "n1"},
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4"},
            {"from": "n4", "to": "n5"},
        ],
        "loops": [{"from": "n3", "to": "n3"}],
        "conditionals": [{"from": "n2", "to": "n3"}],
        "debug": "Test data"
    }


@app.post("/register")
@limiter.limit("5/minute")
async def register(request: Request, user: UserRegister, db: Session = Depends(get_db)):
    """Register new user"""
    normalized_email = user.email.strip().lower()
    normalized_username = user.username.strip()

    if db.query(User).filter(User.email == normalized_email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    from sqlalchemy import func
    if db.query(User).filter(func.lower(User.username) == normalized_username.lower()).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    hashed_password = hash_password(user.password)
    new_user = User(
        username=normalized_username,
        email=normalized_email,
        password_hash=hashed_password
    )

    db.add(new_user)
    db.flush()

    subscription = Subscription(user_id=new_user.id, plan="free")
    db.add(subscription)

    raw_api_key = generate_api_key()
    key_hash = hash_api_key(raw_api_key)

    api_key = APIKey(
        user_id=new_user.id,
        key_hash=key_hash,
        key_prefix=raw_api_key[:20],
        name="Default"
    )

    db.add(api_key)
    db.commit()

    logger.info(f"User registered: {user.email}")
    REQUESTS_TOTAL.labels(endpoint="register", status="success").inc()

    return {
        "user_id": new_user.id,
        "username": new_user.username,
        "api_key": raw_api_key,
        "message": "User registered. Store your API key securely!"
    }


@app.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, creds: UserLogin, db: Session = Depends(get_db)):
    """Login user with email or username and return JWT token"""
    identifier = creds.login.strip()
    from sqlalchemy import func
    # Check if login looks like an email
    if '@' in identifier:
        user = db.query(User).filter(User.email == identifier.lower()).first()
    else:
        user = db.query(User).filter(func.lower(User.username) == identifier.lower()).first()

    if not user or not verify_password(creds.password, user.password_hash):
        logger.warning("Failed login attempt for identifier: %s", creds.login[:100].replace('\n', '').replace('\r', ''))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token(user.id)

    logger.info(f"User logged in: {user.email}")
    REQUESTS_TOTAL.labels(endpoint="login", status="success").inc()

    return {
        "access_token": token,
        "user_id": user.id,
        "username": user.username
    }


@app.post("/auth/api-key")
@limiter.limit("10/minute")
async def exchange_token_for_api_key(request: Request, db: Session = Depends(get_db)):
    """Exchange a valid JWT (from /login) for a fresh API key. Key is returned once and never stored in plaintext."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = auth_header[7:]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    # Revoke any existing un-revoked Session keys for this user so logins
    # don't accumulate unlimited dead keys over time.
    db.query(APIKey).filter(
        APIKey.user_id == user.id,
        APIKey.name == "Session",
        APIKey.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    api_key = APIKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=raw_key[:20],
        name="Session",
    )
    db.add(api_key)
    db.commit()
    prune_revoked_keys(user.id, db)
    logger.info(f"Session API key issued for user {user.id}")
    return {"api_key": raw_key, "username": user.username}


@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("30/minute")
async def analyze(
    request: Request,
    analyze_request: AnalyzeRequest,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Analyze code with caching"""
    REQUESTS_TOTAL.labels(endpoint="analyze", status="started").inc()
    with ANALYSIS_TIME.time():
        try:
            if len(analyze_request.code) > MAX_CODE_SIZE:
                raise HTTPException(status_code=413, detail="Code too large")

            # Count actual loop constructs. For Python use the AST (comprehensions
            # and generator expressions are NOT For/While AST nodes) so list
            # comprehensions don't trigger the complexity cap.
            if analyze_request.language == "python":
                try:
                    import ast as _ast
                    _tree = _ast.parse(analyze_request.code)
                    loop_count = sum(
                        1 for _n in _ast.walk(_tree)
                        if isinstance(_n, (_ast.For, _ast.While))
                    )
                except SyntaxError:
                    loop_count = 0
            else:
                _code_for_count = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '', analyze_request.code)
                _code_for_count = re.sub(r"'[^'\\]*(?:\\.[^'\\]*)*'", '', _code_for_count)
                _code_for_count = re.sub(r'`[^`\\]*(?:\\.[^`\\]*)*`', '', _code_for_count)
                _code_for_count = re.sub(r'//[^\n]*', '', _code_for_count)
                _code_for_count = re.sub(r'/\*.*?\*/', '', _code_for_count, flags=re.DOTALL)
                _code_for_count = re.sub(r'#[^\n]*', '', _code_for_count)
                loop_count = len(re.findall(r'\bfor\b', _code_for_count)) + \
                             len(re.findall(r'\bwhile\b', _code_for_count))
            if loop_count > MAX_LOOPS:
                raise HTTPException(status_code=400, detail="Code too complex")

            check_plan_limits(api_key.user, db)

            cached_result = get_cached_analysis(analyze_request.language, analyze_request.code)
            if cached_result and not cached_result.get("error"):
                logger.info(f"Cache hit for {analyze_request.language}")
                CACHE_HITS.inc()
                REQUESTS_TOTAL.labels(endpoint="analyze", status="cached").inc()

                return AnalyzeResponse(
                    task_id=None,
                    status="success",
                    cached=True,
                    nodes=cached_result.get("nodes", []),
                    edges=cached_result.get("edges", []),
                    loops=cached_result.get("loops", []),
                    conditionals=cached_result.get("conditionals", []),
                    call_edges=cached_result.get("call_edges", []),
                    function_groups=cached_result.get("function_groups", {}),
                    unused_functions=cached_result.get("unused_functions", []),
                    error=None
                )

            _code_hash = get_code_hash(analyze_request.code)

            # --- Async path: dispatch large analyses to Celery ---
            if len(analyze_request.code) >= ASYNC_THRESHOLD:
              try:
                from celery_tasks import analyze_code_task

                # Pre-create Analysis row so it counts toward rate limits immediately
                analysis_row = Analysis(
                    user_id=api_key.user_id,
                    api_key_id=api_key.id,
                    language=analyze_request.language,
                    code_hash=_code_hash,
                    code_length=len(analyze_request.code),
                    status="pending",
                    ip_address=request.client.host,
                    user_agent=request.headers.get("user-agent", ""),
                )
                db.add(analysis_row)
                db.commit()

                task = analyze_code_task.delay(
                    user_id=api_key.user_id,
                    api_key_id=api_key.id,
                    language=analyze_request.language,
                    code=analyze_request.code,
                    ip_address=request.client.host,
                    user_agent=request.headers.get("user-agent", ""),
                    code_hash=_code_hash,
                    analysis_id=analysis_row.id,
                )

                # Store the Celery task ID on the Analysis row for polling
                analysis_row.celery_task_id = task.id
                db.commit()

                logger.info(
                    f"Async analysis dispatched: analysis_id={analysis_row.id}, "
                    f"celery_task_id={task.id}, user={api_key.user_id}, "
                    f"lang={analyze_request.language}, size={len(analyze_request.code)}"
                )
                REQUESTS_TOTAL.labels(endpoint="analyze", status="queued").inc()

                return AnalyzeResponse(
                    task_id=task.id,
                    status="pending",
                    cached=False,
                )
              except Exception as _celery_err:
                logger.warning("Celery unavailable, falling back to sync: %s", _celery_err)

            # --- Sync path: parse small code inline for instant results ---
            if analyze_request.language == "python":
                from parsers.python_parser import parse
            elif analyze_request.language == "c":
                from parsers.c_parser import parse
            elif analyze_request.language == "cpp":
                from parsers.cpp_parser import parse
            elif analyze_request.language == "java":
                from parsers.java_parser import parse
            elif analyze_request.language == "javascript":
                from parsers.js_parser import parse
            elif analyze_request.language == "typescript":
                from parsers.js_parser import parse as _js_parse
                parse = lambda code: _js_parse(code, language="typescript")
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported language: {analyze_request.language}")

            t_start = time.time()
            try:
                result = parse(analyze_request.code)
            except SyntaxError as exc:
                logger.warning(f"Syntax error ({analyze_request.language}): {exc}")
                err_line = getattr(exc, 'lineno', None)
                err_msg = getattr(exc, 'msg', None) or str(exc) or "Syntax error in submitted code"
                return AnalyzeResponse(
                    task_id=None,
                    status="error",
                    error=f"Syntax error: {err_msg}",
                    error_line=err_line,
                )
            except Exception as exc:
                _ename = type(exc).__name__
                _emod = type(exc).__module__ or ""
                if ("pycparser" in _emod or "javalang" in _emod
                        or _ename in ("ParseError", "LexerError", "JavaSyntaxError")):
                    logger.warning(f"Parse error ({analyze_request.language}, {_ename}): {exc}")
                    err_line = None
                    _at = getattr(exc, 'at', None)
                    if _at is not None and hasattr(_at, 'line'):
                        err_line = _at.line
                    if err_line is None:
                        _coord = getattr(exc, 'coord', None)
                        if _coord is not None and hasattr(_coord, 'line'):
                            err_line = _coord.line
                    if err_line is None:
                        err_line = getattr(exc, 'line', None) or getattr(exc, 'lineno', None)
                    return AnalyzeResponse(
                        task_id=None,
                        status="error",
                        error=f"Parse error: {_ename}",
                        error_line=err_line,
                    )
                raise
            exec_ms = int((time.time() - t_start) * 1000)

            REQUESTS_TOTAL.labels(endpoint="analyze", status="success").inc()

            set_analysis_cache(analyze_request.language, analyze_request.code, result)

            analysis_row = Analysis(
                user_id=api_key.user_id,
                api_key_id=api_key.id,
                language=analyze_request.language,
                code_hash=_code_hash,
                code_length=len(analyze_request.code),
                node_count=len(result.get("nodes", [])),
                edge_count=len(result.get("edges", [])),
                loop_count=len(result.get("loops", [])),
                conditional_count=len(result.get("conditionals", [])),
                execution_time_ms=exec_ms,
                status="success" if not result.get("error") else "error",
                error_message=result.get("error"),
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent", ""),
            )
            db.add(analysis_row)
            db.commit()

            logger.info(
                f"Analysis complete: id={analysis_row.id}, user={api_key.user_id}, "
                f"lang={analyze_request.language}, nodes={len(result.get('nodes', []))}, "
                f"time={exec_ms}ms"
            )

            return AnalyzeResponse(
                task_id=str(analysis_row.id),
                status="success",
                cached=False,
                nodes=result.get("nodes", []),
                edges=result.get("edges", []),
                loops=result.get("loops", []),
                conditionals=result.get("conditionals", []),
                call_edges=result.get("call_edges", []),
                function_groups=result.get("function_groups", {}),
                unused_functions=result.get("unused_functions", []),
                error=result.get("error")
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Analyze error: {e}")
            REQUESTS_TOTAL.labels(endpoint="analyze", status="error").inc()
            raise HTTPException(status_code=500, detail="Internal analysis error")


@app.get("/task/{task_id}")
async def get_task_status(
    task_id: str,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Get status of an async analysis task"""
    # Look up the Analysis row by celery_task_id to verify ownership
    analysis = db.query(Analysis).filter(
        Analysis.celery_task_id == task_id,
        Analysis.user_id == api_key.user_id
    ).first()

    if not analysis:
        raise HTTPException(status_code=404, detail="Task not found")

    # If the worker already wrote the final result to the DB, return it directly
    if analysis.status == "success" and analysis.result_data:
        result = analysis.result_data
        return {
            "status": "success",
            "result": {
                "nodes": result.get("nodes", []),
                "edges": result.get("edges", []),
                "loops": result.get("loops", []),
                "conditionals": result.get("conditionals", []),
                "call_edges": result.get("call_edges", []),
                "function_groups": result.get("function_groups", {}),
                "unused_functions": result.get("unused_functions", []),
            }
        }
    elif analysis.status == "error":
        return {"status": "error", "error": analysis.error_message}

    # Otherwise check Celery for live task state
    from celery_tasks import celery_app
    task = celery_app.AsyncResult(task_id)

    if task.state == "SUCCESS":
        task_result = task.result or {}
        data = task_result.get("data", {})
        return {
            "status": "success",
            "result": {
                "nodes": data.get("nodes", []),
                "edges": data.get("edges", []),
                "loops": data.get("loops", []),
                "conditionals": data.get("conditionals", []),
                "call_edges": data.get("call_edges", []),
                "function_groups": data.get("function_groups", {}),
                "unused_functions": data.get("unused_functions", []),
            }
        }
    elif task.state == "FAILURE":
        return {"status": "error", "error": str(task.info)[:500]}
    elif task.state == "STARTED":
        return {"status": "processing", "message": "Analysis in progress"}
    else:
        return {"status": "pending", "message": "Task queued"}


@app.get("/history")
async def get_history(
    limit: int = 50,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Get analysis history"""
    limit = max(1, min(limit, 500))
    base_q = db.query(Analysis).filter(Analysis.user_id == api_key.user_id)
    total = base_q.count()
    analyses = base_q.order_by(Analysis.created_at.desc()).limit(limit).all()

    return {
        "total": total,
        "analyses": [
            {
                "id": a.id,
                "language": a.language,
                "status": a.status,
                "nodes": a.node_count,
                "edges": a.edge_count,
                "time_ms": a.execution_time_ms,
                "created": a.created_at.isoformat()
            }
            for a in analyses
        ]
    }


# --- Saved Graphs ---

@app.post("/graphs")
async def save_graph(
    req: SaveGraphRequest,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Save a graph for the authenticated user"""
    import json as _json
    if len(_json.dumps(req.graph_data)) > 500 * 1024:
        raise HTTPException(status_code=413, detail="Graph data too large (max 500KB)")
    graph = SavedGraph(
        user_id=api_key.user_id,
        title=req.title,
        description=req.description,
        code=req.code,
        language=req.language,
        graph_data=req.graph_data,
        is_public=req.is_public,
    )
    db.add(graph)
    db.commit()
    logger.info(f"Graph saved: user={api_key.user_id}, title={req.title!r}")
    return {"id": graph.id, "title": graph.title, "created_at": graph.created_at.isoformat()}


@app.get("/graphs")
async def list_graphs(
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """List saved graphs for the authenticated user"""
    graphs = db.query(SavedGraph).filter(
        SavedGraph.user_id == api_key.user_id
    ).order_by(SavedGraph.created_at.desc()).all()
    return {
        "graphs": [
            {
                "id": g.id,
                "title": g.title,
                "description": g.description,
                "language": g.language,
                "is_public": g.is_public,
                "created_at": g.created_at.isoformat(),
            }
            for g in graphs
        ]
    }


@app.get("/graphs/{graph_id}")
async def get_graph(
    graph_id: int,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Get full saved graph data"""
    graph = db.query(SavedGraph).filter(SavedGraph.id == graph_id).first()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    if graph.user_id != api_key.user_id and not graph.is_public:
        raise HTTPException(status_code=403, detail="Not authorized")
    return {
        "id": graph.id,
        "title": graph.title,
        "description": graph.description,
        "language": graph.language,
        "code": graph.code,
        "graph_data": graph.graph_data,
        "is_public": graph.is_public,
        "created_at": graph.created_at.isoformat(),
    }


@app.delete("/graphs/{graph_id}")
async def delete_graph(
    graph_id: int,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Delete a saved graph"""
    graph = db.query(SavedGraph).filter(SavedGraph.id == graph_id).first()
    if not graph:
        raise HTTPException(status_code=404, detail="Graph not found")
    if graph.user_id != api_key.user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    db.delete(graph)
    db.commit()
    return {"message": "Graph deleted"}


# --- API Key Management ---

@app.get("/api-keys")
async def list_api_keys(
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """List all API keys for the authenticated user"""
    keys = db.query(APIKey).filter(APIKey.user_id == api_key.user_id).all()
    return {
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_valid(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ]
    }


@app.post("/api-keys")
async def create_api_key(
    req: CreateApiKeyRequest,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Create a new API key. The raw key is returned once and never stored."""
    active_key_count = db.query(APIKey).filter(
        APIKey.user_id == api_key.user_id,
        APIKey.revoked_at.is_(None)
    ).count()
    if active_key_count >= 20:
        raise HTTPException(status_code=429, detail="API key limit reached (max 20 active keys)")
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    new_key = APIKey(
        user_id=api_key.user_id,
        key_hash=key_hash,
        key_prefix=raw_key[:20],
        name=req.name,
    )
    db.add(new_key)
    db.commit()
    logger.info(f"New API key created: user={api_key.user_id}, name={req.name!r}")
    return {
        "id": new_key.id,
        "name": new_key.name,
        "key_prefix": new_key.key_prefix,
        "api_key": raw_key,
        "message": "Store this key securely — it will not be shown again.",
    }


@app.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Revoke an API key"""
    if key_id == api_key.id:
        raise HTTPException(status_code=400, detail="Cannot revoke the key you are currently using")
    target = db.query(APIKey).filter(
        APIKey.id == key_id,
        APIKey.user_id == api_key.user_id
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="API key not found")
    target.revoked_at = datetime.now(timezone.utc)
    db.commit()
    prune_revoked_keys(api_key.user_id, db)
    logger.info(f"API key revoked: id={key_id}, user={api_key.user_id}")
    return {"message": "API key revoked"}


# --- User Profile Info ---

@app.get("/me")
async def get_my_profile(
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Get the current user's basic profile"""
    user = api_key.user
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
    }


# --- User Subscription Info ---

@app.get("/me/subscription")
async def get_my_subscription(
    db: Session = Depends(get_db),
    api_key: APIKey = Depends(verify_api_key_dep)
):
    """Get the current user's subscription info"""
    sub = db.query(Subscription).filter_by(user_id=api_key.user_id).first()
    if not sub:
        sub = Subscription(user_id=api_key.user_id, plan="free")
        db.add(sub)
        db.commit()

    today = datetime.now(timezone.utc).date()
    today_start = datetime(today.year, today.month, today.day)
    today_count = db.query(Analysis).filter(
        Analysis.user_id == api_key.user_id,
        Analysis.created_at >= today_start
    ).count()

    return {
        "plan": sub.plan,
        "requests_per_day": sub.requests_per_day,
        "requests_per_month": sub.requests_per_month,
        "requests_used_today": today_count,
    }


# --- Public Site Settings ---

@app.get("/settings/public")
async def get_public_settings(db: Session = Depends(get_db)):
    """Get publicly visible site settings (plan prices, contact email, upgrade instructions)"""
    settings = db.query(SiteSettings).all()
    result = dict(SITE_SETTINGS_DEFAULTS)  # start with defaults
    for s in settings:
        result[s.key] = s.value
    return result


# --- Admin Middleware ---

def verify_admin(request: Request, db: Session = Depends(get_db)):
    """Verify the caller is an admin via API key or JWT Bearer token."""
    # Try API key first
    api_key_str = request.headers.get("x-api-key")
    if api_key_str:
        key_hash = hash_api_key(api_key_str)
        api_key = db.query(APIKey).filter(
            APIKey.key_hash == key_hash,
            APIKey.revoked_at.is_(None)
        ).first()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        user = api_key.user
    else:
        # Try JWT Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Admin auth required")
        token = auth_header[7:]
        user_id = verify_token(token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = db.query(User).filter(User.id == user_id).first()

    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User inactive")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# --- Admin Pydantic Models ---

class AdminUpdateUser(BaseModel):
    username: Optional[str] = Field(default=None, min_length=3, max_length=64)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None

    @field_validator("username")
    @classmethod
    def username_rules(cls, v):
        if v is not None:
            return _validate_username(v)
        return v

    @field_validator("email")
    @classmethod
    def email_strict(cls, v):
        if v is not None:
            return _validate_email_strict(v)
        return v


class AdminUpdateSubscription(BaseModel):
    plan: str
    requests_per_day: Optional[int] = None
    requests_per_month: Optional[int] = None


# --- Admin Endpoints ---

@app.get("/admin/stats")
async def admin_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Dashboard stats overview"""
    from sqlalchemy import func
    today = datetime.now(timezone.utc).date()
    today_start = datetime(today.year, today.month, today.day)

    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()
    total_analyses = db.query(Analysis).count()
    today_analyses = db.query(Analysis).filter(Analysis.created_at >= today_start).count()
    total_graphs = db.query(SavedGraph).count()

    sub_counts = dict(
        db.query(Subscription.plan, func.count(Subscription.id))
        .group_by(Subscription.plan).all()
    )

    lang_counts = dict(
        db.query(Analysis.language, func.count(Analysis.id))
        .group_by(Analysis.language).all()
    )

    recent_signups = db.query(User).filter(
        User.created_at >= today_start
    ).count()

    return {
        "total_users": total_users,
        "active_users": active_users,
        "recent_signups_today": recent_signups,
        "total_analyses": total_analyses,
        "analyses_today": today_analyses,
        "total_saved_graphs": total_graphs,
        "subscriptions_by_plan": sub_counts,
        "analyses_by_language": lang_counts,
    }


@app.get("/admin/users")
async def admin_list_users(
    page: int = 1,
    per_page: int = 50,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """List all users with pagination and search"""
    per_page = max(1, min(per_page, 200))
    page = max(1, page)

    query = db.query(User)
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (User.username.ilike(pattern)) | (User.email.ilike(pattern))
        )

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    result = []
    for u in users:
        sub = db.query(Subscription).filter_by(user_id=u.id).first()
        analysis_count = db.query(Analysis).filter_by(user_id=u.id).count()
        key_count = db.query(APIKey).filter(
            APIKey.user_id == u.id, APIKey.revoked_at.is_(None)
        ).count()
        result.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat(),
            "updated_at": u.updated_at.isoformat() if u.updated_at else None,
            "plan": sub.plan if sub else "free",
            "requests_per_day": sub.requests_per_day if sub else 100,
            "analysis_count": analysis_count,
            "active_api_keys": key_count,
        })

    return {"total": total, "page": page, "per_page": per_page, "users": result}


@app.get("/admin/users/{user_id}")
async def admin_get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Get detailed user info"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub = db.query(Subscription).filter_by(user_id=user.id).first()
    keys = db.query(APIKey).filter(APIKey.user_id == user.id).all()
    analysis_count = db.query(Analysis).filter_by(user_id=user.id).count()
    graph_count = db.query(SavedGraph).filter_by(user_id=user.id).count()

    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "subscription": {
            "plan": sub.plan if sub else "free",
            "requests_per_day": sub.requests_per_day if sub else 100,
            "requests_per_month": sub.requests_per_month if sub else 3000,
        } if sub else {"plan": "free", "requests_per_day": 100, "requests_per_month": 3000},
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_valid(),
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ],
        "analysis_count": analysis_count,
        "saved_graph_count": graph_count,
    }


@app.patch("/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    updates: AdminUpdateUser,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Update user fields (username, email, is_active, is_admin)"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if updates.username is not None:
        from sqlalchemy import func
        existing = db.query(User).filter(func.lower(User.username) == updates.username.lower(), User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = updates.username.strip()
    if updates.email is not None:
        normalized_email = updates.email.strip().lower()
        existing = db.query(User).filter(User.email == normalized_email, User.id != user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        user.email = normalized_email
    if updates.is_active is not None:
        user.is_active = updates.is_active
    if updates.is_admin is not None:
        if user.id == admin.id and not updates.is_admin:
            raise HTTPException(status_code=400, detail="Cannot revoke your own admin access")
        user.is_admin = updates.is_admin

    db.commit()
    logger.info(f"Admin {admin.id} updated user {user_id}")
    return {"message": "User updated"}


@app.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Delete a user and all their data"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    logger.info(f"Admin {admin.id} deleted user {user_id}")
    return {"message": "User deleted"}


@app.put("/admin/users/{user_id}/subscription")
async def admin_update_subscription(
    user_id: int,
    sub_update: AdminUpdateSubscription,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Update a user's subscription plan"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan_defaults = {
        "free": {"requests_per_day": 100, "requests_per_month": 3000},
        "pro": {"requests_per_day": 1000, "requests_per_month": 30000},
        "enterprise": {"requests_per_day": 10000, "requests_per_month": 300000},
    }
    if sub_update.plan not in plan_defaults:
        raise HTTPException(status_code=400, detail="Plan must be free, pro, or enterprise")

    sub = db.query(Subscription).filter_by(user_id=user_id).first()
    if not sub:
        sub = Subscription(user_id=user_id)
        db.add(sub)

    defaults = plan_defaults[sub_update.plan]
    sub.plan = sub_update.plan
    sub.requests_per_day = sub_update.requests_per_day or defaults["requests_per_day"]
    sub.requests_per_month = sub_update.requests_per_month or defaults["requests_per_month"]
    db.commit()

    logger.info(f"Admin {admin.id} set user {user_id} to plan={sub_update.plan}")
    return {"message": f"Subscription updated to {sub_update.plan}"}


@app.get("/admin/users/{user_id}/api-keys")
async def admin_list_user_api_keys(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """List all API keys for a specific user"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    keys = db.query(APIKey).filter(APIKey.user_id == user_id).all()
    return {
        "api_keys": [
            {
                "id": k.id,
                "name": k.name,
                "key_prefix": k.key_prefix,
                "is_active": k.is_valid(),
                "rate_limit_per_minute": k.rate_limit_per_minute,
                "rate_limit_per_day": k.rate_limit_per_day,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                "created_at": k.created_at.isoformat(),
                "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
            }
            for k in keys
        ]
    }


@app.post("/admin/users/{user_id}/api-keys/reset")
async def admin_reset_user_api_keys(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Revoke all API keys for a user and issue a fresh one"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.query(APIKey).filter(
        APIKey.user_id == user_id,
        APIKey.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)

    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    new_key = APIKey(
        user_id=user_id,
        key_hash=key_hash,
        key_prefix=raw_key[:20],
        name="Admin-Reset",
    )
    db.add(new_key)
    db.commit()
    prune_revoked_keys(user_id, db)

    logger.info(f"Admin {admin.id} reset API keys for user {user_id}")
    return {"message": "All keys revoked, new key issued", "api_key": raw_key}


@app.delete("/admin/api-keys/{key_id}")
async def admin_revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Revoke a specific API key"""
    key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    prune_revoked_keys(key.user_id, db)
    logger.info(f"Admin {admin.id} revoked API key {key_id}")
    return {"message": "API key revoked"}


@app.get("/admin/me")
async def admin_me(admin: User = Depends(verify_admin)):
    """Return current admin user info (used by admin UI to verify access)"""
    return {"id": admin.id, "username": admin.username, "is_admin": True}


# --- Admin Site Settings ---

class AdminUpdateSettings(BaseModel):
    contact_email: Optional[str] = None
    plan_price_free: Optional[str] = None
    plan_price_pro: Optional[str] = None
    plan_price_enterprise: Optional[str] = None
    upgrade_instructions: Optional[str] = None


@app.get("/admin/settings")
async def admin_get_settings(
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Get all site settings"""
    settings = db.query(SiteSettings).all()
    result = dict(SITE_SETTINGS_DEFAULTS)
    for s in settings:
        result[s.key] = s.value
    return result


@app.put("/admin/settings")
async def admin_update_settings(
    updates: AdminUpdateSettings,
    db: Session = Depends(get_db),
    admin: User = Depends(verify_admin)
):
    """Update site settings (contact email, plan prices, upgrade instructions)"""
    changes = {k: v for k, v in updates.model_dump().items() if v is not None}
    for key, value in changes.items():
        setting = db.query(SiteSettings).filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            db.add(SiteSettings(key=key, value=value))
    db.commit()
    logger.info(f"Admin {admin.id} updated site settings: {list(changes.keys())}")
    return {"message": "Settings updated", "updated": list(changes.keys())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
