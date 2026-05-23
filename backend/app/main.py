import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError

_logger = logging.getLogger(__name__)

from app.auth.dependencies import get_current_tenant, get_current_admin
from app.cache import init_redis, close_redis
from app.middleware.audit import AuditMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.session_guard import SessionGuardMiddleware
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
from app.routers import order_purchase_details  # ADR-021 Phase 4 / Sprint 4: 仕入情報 MVP
from app.routers import order_commissions  # ADR-021 Phase 5 / Sprint 5: 報酬計算 MVP
from app.routers import tenant_commission_settings  # ADR-021 Phase 5 / Sprint 5: 報酬計算 MVP
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
from app.routers import tenant_profile  # Sprint 8 / F8: PO PDF / メール差出人情報
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
from app.routers import contact  # LP問い合わせフォーム受付
# spec.md v1.1 F2 (Sprint 2): マスタ編集 UI（中央 admin + テナント admin の二層）
from app.routers import super_admin_knowledge
from app.routers import super_admin_aliases
from app.routers import super_admin_tcg
from app.routers import super_admin_dex
from app.routers import super_admin_suppliers
# spec.md v1.1 F4 (Sprint 4): LLM 予算管理 admin UI
from app.routers import super_admin_llm_budget
# spec.md v1.1 F5 (Sprint 5): Discord Inbound 受信メッセージ一覧 admin UI
from app.routers import super_admin_inbound
# spec.md v1.1 F6 (Sprint 6): 解析結果レビュー UI + 在庫差分反映
from app.routers import parse_review
from app.routers import tenant_admin_inventory_visibility
# spec.md v1.1 F7 (Sprint 7): 在庫検索 API (全 7 種横断 + AND/OR + visibility マスク)
from app.routers import inventory_search
# spec.md v1.2 F9 (Sprint 9): スプレッドシート並走 Phase 切替 admin UI
from app.routers import super_admin_phase_switch

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
        _logger.warning(
            "METADATA_FERNET_KEY の検証に失敗しました（Meta OAuth 系統は無効化されます）: %s", e
        )

    # 基盤環境変数チェック（DATABASE_URL, REDIS_URL, CELERY_BROKER_URL）
    for _infra_var in ("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL"):
        if not os.getenv(_infra_var):
            _logger.warning("インフラ環境変数 %s が未設定です", _infra_var)

    # Webhook 必須環境変数チェック
    # ENFORCE_WEBHOOK_SECRETS=1 の場合は起動を失敗させる
    _enforce_webhook = os.getenv("ENFORCE_WEBHOOK_SECRETS", "").strip().lower() in ("1", "true", "yes", "on")
    for _var in ("META_APP_SECRET", "META_VERIFY_TOKEN"):
        if not os.getenv(_var):
            if _enforce_webhook:
                raise RuntimeError(f"Required env var {_var} is not set")
            _logger.warning("必須環境変数 %s が未設定です（ENFORCE_WEBHOOK_SECRETS=1 で起動を強制失敗させられます）", _var)

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

# 認証イベント・データアクセス自動記録ミドルウェア
app.add_middleware(AuditMiddleware)
# APIレート制限（認証済み100回/分、未認証60回/分）
app.add_middleware(RateLimitMiddleware)
# セッションハイジャック検知（物理的に不可能な移動のみ強制再認証）
app.add_middleware(SessionGuardMiddleware)

# --- 認証不要なルーター（明示的に除外） ---
# /api/health はバージョンなし（監視ツールが固定URLを使うため）
app.include_router(health.router, prefix="/api", tags=["health"])
# /api/v1/auth にバージョン管理を適用
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
# Meta Webhook（認証不要 - Metaのサーバーからアクセスされる）
app.include_router(webhook.router, prefix="/api/v1", tags=["webhook"])
# Meta Data Deletion Callback + Status API（認証不要 - 公開エンドポイント）
app.include_router(meta.router, prefix="/api/v1", tags=["meta"])
# LP問い合わせフォーム受付（認証不要 - salesanchor.jp からのフォーム送信）
app.include_router(contact.router, prefix="/api/v1", tags=["contact"])

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
# ADR-021 Phase 4 / Sprint 4: 仕入情報 + 仕入元別履歴
app.include_router(
    order_purchase_details.router, prefix="/api/v1", tags=["order_purchase_details"],
    dependencies=[Depends(get_current_tenant)],
)
# ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
app.include_router(
    tenant_commission_settings.router, prefix="/api/v1", tags=["tenant_commission_settings"],
    dependencies=[Depends(get_current_tenant)],
)
app.include_router(
    order_commissions.router, prefix="/api/v1", tags=["order_commissions"],
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
# Sprint 8 / F8: テナント発行者情報 (PO PDF / メール差出人) admin CRUD
app.include_router(
    tenant_profile.router, prefix="/api/v1", tags=["tenant_profile"],
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

# spec.md v1.1 F2 (Sprint 2): マスタ編集 UI（中央 admin）
#
# super-admin/* は public schema のマスタを操作するため、get_current_tenant
# ではなく require_super_admin を各ルーターレベルで適用。
# get_current_tenant を付けない理由: search_path を tenant に固定すると
# public schema 直書きの SQL が tenant schema を先に見てしまう可能性がある。
# テストでは get_current_tenant は不要 (DB は SQLite で search_path 非対応)。
app.include_router(
    super_admin_knowledge.router, prefix="/api/v1", tags=["super-admin"],
)
app.include_router(
    super_admin_aliases.router, prefix="/api/v1", tags=["super-admin"],
)
app.include_router(
    super_admin_tcg.router, prefix="/api/v1", tags=["super-admin"],
)
app.include_router(
    super_admin_dex.router, prefix="/api/v1", tags=["super-admin"],
)
app.include_router(
    super_admin_suppliers.router, prefix="/api/v1", tags=["super-admin"],
)
# Sprint 4 (F4): LLM 予算管理 (public.tenant_llm_budgets) 中央 admin
app.include_router(
    super_admin_llm_budget.router, prefix="/api/v1", tags=["super-admin"],
)
# Sprint 5 (F5): Discord Inbound 受信メッセージ一覧 (public.discord_inbound_messages) 中央 admin
app.include_router(
    super_admin_inbound.router, prefix="/api/v1", tags=["super-admin"],
)
# Sprint 6 (F6): 解析結果レビュー UI + 在庫差分反映 (public.inventory_movements + products) 中央 admin
app.include_router(
    parse_review.router, prefix="/api/v1", tags=["super-admin"],
)
# テナント admin 用 inventory visibility は get_current_tenant 必須
app.include_router(
    tenant_admin_inventory_visibility.router, prefix="/api/v1",
    tags=["tenant-admin-inventory-visibility"],
    dependencies=[Depends(get_current_tenant)],
)

# spec.md v1.1 F7 (Sprint 7): 在庫検索 API (営業向け、QuoteCreatePage 等から呼び出し)
# tenant search_path 設定 + token 認証必須 (load_user_permissions で権限判定)
app.include_router(
    inventory_search.router, prefix="/api/v1",
    tags=["inventory-search"],
    dependencies=[Depends(get_current_tenant)],
)

# spec.md v1.2 F9 (Sprint 9): スプレッドシート並走 Phase 切替 admin API
# require_super_admin で保護 (router レベル + 各エンドポイントで重ねガード)
app.include_router(
    super_admin_phase_switch.router, prefix="/api/v1", tags=["super-admin"],
)


@app.exception_handler(OperationalError)
async def db_operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    """DB接続エラー（OperationalError）を503に変換する。

    コネクションプール枯渇・DB再起動中・タイムアウトなどのインフラ障害を
    502ではなく503（Service Unavailable）で返す。
    """
    _logger.error("Database operational error: %s %s - %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "データベースに接続できません。しばらく待ってから再試行してください。"},
    )


@app.exception_handler(SQLAlchemyError)
async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """その他のSQLAlchemyエラーを500に変換する。"""
    _logger.error("Database error: %s %s - %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "データベースエラーが発生しました。"},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未捕捉例外をすべて 500 に変換してクライアントに返す。

    FastAPI が HTTPException / SQLAlchemyError を先処理するため、
    それらはここに届かない。予期しない例外の最終防波堤。
    """
    _logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "内部サーバーエラーが発生しました"},
    )


@app.get("/")
async def root():
    return {
        "message": "Multi-tenant CRM API",
        "version": "1.0.0",
    }
