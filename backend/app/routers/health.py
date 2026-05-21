import logging
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    ヘルスチェックエンドポイント。

    - DB接続失敗 → 503（サービス不可）
    - Redis/Celery失敗 → 200 degraded（インフラ劣化状態、サービスは継続）
    - 全正常 → 200 ok
    """
    checks: dict = {}

    # ── DB チェック（必須）──────────────────────────────
    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        checks["database"] = "connected"
    except Exception as e:
        logger.error("Health check: database failed - %s", e)
        checks["database"] = "disconnected"
        return JSONResponse(
            status_code=503,
            content={"status": "error", **checks},
        )

    # ── Redis チェック（degraded 扱い）──────────────────
    try:
        from app.cache import get_redis
        r = get_redis()
        if r:
            await r.ping()
            checks["redis"] = "connected"
        else:
            checks["redis"] = "not_initialized"
    except Exception as e:
        logger.warning("Health check: redis failed - %s", e)
        checks["redis"] = "disconnected"

    # ── Celery チェック（degraded 扱い、timeout=2秒）────
    try:
        celery_broker = os.getenv("CELERY_BROKER_URL", "")
        if celery_broker:
            from app.celery_app import celery_app
            result_inspect = celery_app.control.ping(timeout=2)
            checks["celery"] = "connected" if result_inspect else "no_workers"
        else:
            checks["celery"] = "not_configured"
    except Exception as e:
        logger.warning("Health check: celery failed - %s", e)
        checks["celery"] = "disconnected"

    # Redis/Celery の劣化は degraded で 200 を返す（監視がアラートを飛ばす）
    has_degraded = any(v not in ("connected", "not_configured") for v in [checks.get("redis"), checks.get("celery")])
    return {
        "status": "degraded" if has_degraded else "ok",
        **checks,
    }
