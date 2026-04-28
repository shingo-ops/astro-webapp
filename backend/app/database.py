import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker

# 環境変数からDATABASE_URLを取得
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://myapp_user:password@postgres:5432/myapp_db")

# 非同期エンジンの作成（本番ではSQLログを無効化）
_engine_kwargs = {
    "echo": os.getenv("ENVIRONMENT", "development") != "production",
    "future": True,
}
# PostgreSQL使用時のみコネクションプール設定を追加（SQLiteはStaticPoolのため不要）
if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(
        pool_size=20,
        max_overflow=10,
        pool_recycle=3600,
        pool_pre_ping=True,
    )
engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

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
