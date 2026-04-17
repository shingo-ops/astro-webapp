import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.dependencies import get_current_tenant, get_current_admin
from app.cache import init_redis, close_redis
from app.middleware.audit import AuditMiddleware
from app.routers import health
from app.routers import auth
from app.routers import admin
from app.routers import customers
from app.routers import deals
from app.routers import orders
from app.routers import dashboard
from app.routers import reports
from app.routers import leads
from app.routers import teams
from app.routers import roles
from app.routers import products
from app.routers import shipping
from app.routers import quotes
from app.routers import invoices
from app.routers import suppliers
from app.routers import purchase_orders
from app.routers import duplicates

# 本番環境では Swagger UI を無効化（API仕様の露出を防ぐ）
is_production = os.getenv("ENVIRONMENT", "development") == "production"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    yield
    await close_redis()


app = FastAPI(
    title="Multi-tenant CRM API",
    description="B2B SaaS CRM バックエンドAPI",
    version="1.0.0",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc",
    lifespan=lifespan,
)

# CORS設定（本番では特定のオリジンのみ許可）
allowed_origins = os.getenv("ALLOWED_ORIGINS", "https://jarvis-claude.uk").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# 認証イベント自動記録ミドルウェア
app.add_middleware(AuditMiddleware)

# --- 認証不要なルーター（明示的に除外） ---
# /api/health はバージョンなし（監視ツールが固定URLを使うため）
app.include_router(health.router, prefix="/api", tags=["health"])
# /api/v1/auth にバージョン管理を適用
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

# --- 認証必須なルーター（デフォルトで認証が強制される） ---
# dependencies=[Depends(get_current_tenant)] により、
# JWTトークンの検証 + tenant_idの取得 + search_pathの切り替えが自動で行われる。
app.include_router(
    admin.router,
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_tenant), Depends(get_current_admin)],
)
# CRM業務ルーター（認証必須）
app.include_router(
    customers.router, prefix="/api/v1", tags=["customers"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    deals.router, prefix="/api/v1", tags=["deals"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    orders.router, prefix="/api/v1", tags=["orders"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    dashboard.router, prefix="/api/v1", tags=["dashboard"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    reports.router, prefix="/api/v1", tags=["reports"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 1追加ルーター: リード / チーム / ロール・権限
app.include_router(
    leads.router, prefix="/api/v1", tags=["leads"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    teams.router, prefix="/api/v1", tags=["teams"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    roles.router, prefix="/api/v1", tags=["roles"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 2: 販売・財務プロセス
app.include_router(
    products.router, prefix="/api/v1", tags=["products"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    shipping.router, prefix="/api/v1", tags=["shipping"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    quotes.router, prefix="/api/v1", tags=["quotes"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    invoices.router, prefix="/api/v1", tags=["invoices"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 3: 仕入れ・調達 + 重複検知
app.include_router(
    suppliers.router, prefix="/api/v1", tags=["suppliers"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    purchase_orders.router, prefix="/api/v1", tags=["purchase_orders"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    duplicates.router, prefix="/api/v1", tags=["duplicates"],
    dependencies=[Depends(get_current_tenant)],
)


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant CRM API",
        "version": "1.0.0",
    }
