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
from app.routers import companies  # Phase 1-B-2 Step 5b-1
from app.routers import contacts   # Phase 1-B-2 Step 5b-1
from app.routers import deals
from app.routers import orders
from app.routers import order_financials  # ADR-021 Phase 2 / Sprint 2: 売上計算 MVP
from app.routers import order_shipping_details  # ADR-021 Phase 3 / Sprint 3: 発送情報 MVP
from app.routers import dashboard
from app.routers import reports
from app.routers import leads
from app.routers import teams
from app.routers import roles
from app.routers import meta, webhook
from app.routers import meta_inbox  # Phase 1-D Sprint 2: OAuth 接続バックエンド
from app.services import encryption as _encryption  # Phase 1-D Sprint 2: lifespan fail-fast
from app.routers import products
from app.routers import shipping
from app.routers import quotes
from app.routers import invoices
from app.routers import suppliers
from app.routers import purchase_orders
from app.routers import duplicates
from app.routers import analytics
from app.routers import notifications
from app.routers import staff_reports
from app.routers import archives
from app.routers import shifts
from app.routers import buddy
from app.routers import badges
from app.routers import erp
from app.routers import staff
from app.routers import bots

# 本番環境では Swagger UI を無効化（API仕様の露出を防ぐ）
is_production = os.getenv("ENVIRONMENT", "development") == "production"


# Phase 1-D Sprint 2: METADATA_FERNET_KEY のチェックを startup で必須にするか
# 環境変数で切り替えられるようにする。本番では `ENFORCE_METADATA_FERNET_KEY=1` を
# 推奨。テストや既存環境のローリング更新時に startup を壊さないため、
# 既定では「鍵が無い場合は warning ログのみ」にする。
def _fernet_fail_fast_enforced() -> bool:
    flag = os.getenv("ENFORCE_METADATA_FERNET_KEY", "").strip().lower()
    return flag in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1-D Sprint 2: Fernet 鍵を起動時に検証してキャッシュ。
    # 鍵が壊れていれば lru_cache が呼ばれた瞬間に EncryptionConfigurationError。
    # ENFORCE_METADATA_FERNET_KEY=1 のときは startup を失敗させる。
    try:
        _encryption._get_default_fernet()  # type: ignore[attr-defined]
    except _encryption.EncryptionConfigurationError as e:
        if _fernet_fail_fast_enforced():
            raise
        # 既定挙動: warning だけ出して起動継続（既存環境への破壊的変更を避ける）
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "METADATA_FERNET_KEY の検証に失敗しました（Meta OAuth 系統は無効化されます）: %s", e
        )

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
allowed_origins = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://jarvis-claude.uk,https://app.salesanchor.jp,https://salesanchor.jp",
    ).split(",")
    if o.strip()
]

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
# Meta Webhook（認証不要 - Metaのサーバーからアクセスされる）
app.include_router(webhook.router, prefix="/api/v1", tags=["webhook"])
# Meta Data Deletion Callback + Status API（認証不要 - 公開エンドポイント）
app.include_router(meta.router, prefix="/api/v1", tags=["meta"])

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
# Phase 1-B-2 Step 5b-1: 新 companies/contacts API（既存 customers と併存）
app.include_router(
    companies.router, prefix="/api/v1", tags=["companies"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    contacts.router, prefix="/api/v1", tags=["contacts"],
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
# ADR-021 Phase 2 / Sprint 2: 受注売上情報 + 月次集計
app.include_router(
    order_financials.router, prefix="/api/v1", tags=["order_financials"],
    dependencies=[Depends(get_current_tenant)],
)
# ADR-021 Phase 3 / Sprint 3: 発送情報 + eLogi CSV エクスポート
app.include_router(
    order_shipping_details.router, prefix="/api/v1", tags=["order_shipping_details"],
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
app.include_router(
    analytics.router, prefix="/api/v1", tags=["analytics"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 4: コミュニケーション・運用
app.include_router(
    notifications.router, prefix="/api/v1", tags=["notifications"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    staff_reports.router, prefix="/api/v1", tags=["staff_reports"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    archives.router, prefix="/api/v1", tags=["archives"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 5: 拡張機能
app.include_router(
    shifts.router, prefix="/api/v1", tags=["shifts"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    buddy.router, prefix="/api/v1", tags=["buddy"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    badges.router, prefix="/api/v1", tags=["badges"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    erp.router, prefix="/api/v1", tags=["erp"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 1 再設計: staff / bots
app.include_router(
    staff.router, prefix="/api/v1", tags=["staff"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    bots.router, prefix="/api/v1", tags=["bots"],
    dependencies=[Depends(get_current_tenant)],
)
# Phase 1-D Sprint 2: Meta Inbox OAuth 接続バックエンド
app.include_router(
    meta_inbox.router, prefix="/api/v1", tags=["meta-inbox"],
    dependencies=[Depends(get_current_tenant)],
)


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant CRM API",
        "version": "1.0.0",
    }
