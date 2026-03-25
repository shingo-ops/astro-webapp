import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 環境変数からDATABASE_URLを取得
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://myapp_user:password@postgres:5432/myapp_db")

# 非同期エンジンの作成
engine = create_async_engine(
    DATABASE_URL,
    echo=True,  # SQLログを出力（開発用）
    future=True
)

# 非同期セッションの作成
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# ベースクラス
Base = declarative_base()

# データベースセッションの依存性注入
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
