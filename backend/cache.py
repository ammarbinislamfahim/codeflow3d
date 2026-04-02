# backend/cache.py - REDIS CACHING LAYER

import redis
import json
import hashlib
import logging
from typing import Optional
import os

logger = logging.getLogger("codeflow.cache")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

redis_client = None

def _get_redis():
    """Lazy Redis connection — avoids blocking at import time."""
    global redis_client
    if redis_client is not None:
        return redis_client
    try:
        client = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
        client.ping()
        logger.info("Redis cache connected")
        redis_client = client
        return redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        return None

ANALYSIS_CACHE_TTL = 3600
HISTORY_CACHE_TTL = 300
ANALYSIS_CACHE_VERSION = "v9"


def get_code_hash(code: str) -> str:
    """Generate hash of code for cache key"""
    return hashlib.sha256(code.encode()).hexdigest()


def get_analysis_cache_key(language: str, code_hash: str) -> str:
    """Generate cache key for analysis result"""
    return f"analysis:{ANALYSIS_CACHE_VERSION}:{language}:{code_hash}"


def get_cached_analysis(language: str, code: str) -> Optional[dict]:
    """Get analysis result from cache"""
    client = _get_redis()
    if not client:
        return None

    code_hash = get_code_hash(code)
    cache_key = get_analysis_cache_key(language, code_hash)

    try:
        cached = client.get(cache_key)
        if cached:
            logger.info(f"Cache hit: {cache_key}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Cache get error: {e}")

    return None


def set_analysis_cache(language: str, code: str, result: dict) -> bool:
    """Cache analysis result — never cache error results"""
    client = _get_redis()
    if not client:
        return False

    # Do not cache results that contain an error; the error may be transient
    # (e.g. a parser bug that gets fixed) and we never want to serve stale errors.
    if result.get("error"):
        logger.info("Skipping cache: result contains error")
        return False

    code_hash = get_code_hash(code)
    cache_key = get_analysis_cache_key(language, code_hash)

    try:
        client.setex(
            cache_key,
            ANALYSIS_CACHE_TTL,
            json.dumps(result)
        )
        logger.info(f"Cache set: {cache_key}")
        return True
    except Exception as e:
        logger.warning(f"Cache set error: {e}")
        return False


def invalidate_analysis_cache(language: str, code: str) -> bool:
    """Invalidate cached analysis"""
    client = _get_redis()
    if not client:
        return False

    code_hash = get_code_hash(code)
    cache_key = get_analysis_cache_key(language, code_hash)

    try:
        client.delete(cache_key)
        logger.info(f"Cache invalidated: {cache_key}")
        return True
    except Exception as e:
        logger.warning(f"Cache invalidate error: {e}")
        return False
