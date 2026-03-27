import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.dependencies import get_current_tenant
from app.routers import health
from app.routers import auth

# 本番環境では Swagger UI を無効化（API仕様の露出を防ぐ）
is_production = os.getenv("ENVIRONMENT", "development") == "production"

app = FastAPI(
    title="Multi-tenant CRM API",
    description="B2B SaaS CRM バックエンドAPI",
    version="1.0.0",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
)

# CORS設定（本番では特定のオリジンのみ許可）
allowed_origins = os.getenv("ALLOWED_ORIGINS", "https://jarvis-claude.uk").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 認証不要なルーター（明示的に除外） ---
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# --- 認証必須なルーター（デフォルトで認証が強制される） ---
# 今後追加するCRM業務ルーターは全てここに登録する。
# dependencies=[Depends(get_current_tenant)] により、
# JWTトークンの検証 + tenant_idの取得 + search_pathの切り替えが自動で行われる。
#
# 例:
# from app.routers import customers, deals, orders
# app.include_router(
#     customers.router,
#     prefix="/api/v1",
#     tags=["customers"],
#     dependencies=[Depends(get_current_tenant)],
# )


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant CRM API",
        "version": "1.0.0",
    }
