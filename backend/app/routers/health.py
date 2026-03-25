from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    ヘルスチェックエンドポイント
    APIとデータベースの接続状態を確認
    """
    try:
        # データベース接続確認
        result = await db.execute(text("SELECT 1"))
        result.scalar()

        return {
            "status": "ok",
            "database": "connected"
        }
    except Exception as e:
        return {
            "status": "error",
            "database": "disconnected",
            "error": str(e)
        }
