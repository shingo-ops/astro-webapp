"""
ルーター共通ユーティリティ（routers/_utils.py）

DB例外を統一的にハンドリングするデコレーター。
"""
from __future__ import annotations

import functools
import logging
from typing import Callable, TypeVar

from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, SQLAlchemyError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)


def handle_db_exceptions(func: F) -> F:
    """SQLAlchemy例外をHTTPエラーに変換するデコレーター。

    - OperationalError（DB接続失敗・タイムアウト） → 503
    - SQLAlchemyError（その他のDB例外）            → 500
    - HTTPException                                → そのまま透過（二重変換防止）
    - その他の例外                                 → そのまま（グローバルハンドラーへ）

    使い方:
        @router.get("/items")
        @handle_db_exceptions
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except OperationalError as e:
            logger.error("Database operational error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=503,
                detail="データベースに接続できません。しばらく待ってから再試行してください。",
            ) from e
        except SQLAlchemyError as e:
            logger.error("Database error in %s: %s", func.__name__, e)
            raise HTTPException(
                status_code=500,
                detail="データベースエラーが発生しました。",
            ) from e
    return wrapper  # type: ignore[return-value]
