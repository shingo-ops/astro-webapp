import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
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
        pool_timeout=30,  # コネクションプール枯渇時の無限待機を防止（30秒で諦めて503を返す）
        connect_args={"prepared_statement_cache_size": 0},  # ADR-065: コンテナ再起動後の InvalidCachedStatementError 防止
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
        except Exception:
            # SQLエラー時は明示的にロールバックしてからコネクションを返却する。
            # ロールバックせずに close() すると INTRANS_INERROR 状態のままプールに
            # 返却され、次のリクエストで別の SQLAlchemyError が発生することがある。
            await session.rollback()
            raise
