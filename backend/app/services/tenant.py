from __future__ import annotations

"""
テナント別スキーマ自動生成サービス。

新しいテナントが登録されるたびに:
  1. public.tenants に企業情報を保存
  2. tenant_{id:03d} スキーマを自動作成
  3. スキーマ内に業務テーブル（customers, deals, orders, audit_logs,
     roles, role_permissions, user_roles, leads, teams, team_members）を作成
  4. Row Level Security（RLS）ポリシーを自動適用
  5. システムロール（オーナー/メンバー）をシード

たとえ話:
  新しい入居者（テナント企業）が契約したら、
  専用の鍵付き個室が自動的に用意される仕組み。

変更履歴:
  2026-04-16: Phase 1対応（roles/leads/teams追加、system_rolesシード）
"""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# 「メンバー」ロールにデフォルトで付与するパーミッションキー
MEMBER_DEFAULT_PERMISSIONS = [
    "dashboard.view",
    "reports.view",
    "customers.view",
    "leads.view",
    "deals.view",
    "orders.view",
    "teams.view",
]


# テナントスキーマ内に作成する業務テーブルのSQL定義
_TENANT_TABLES_SQL = """
-- 顧客データ
CREATE TABLE IF NOT EXISTS {schema}.customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_code VARCHAR(20),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    company VARCHAR(255),
    registration_source VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    billing_name VARCHAR(255),
    billing_phone VARCHAR(50),
    billing_email VARCHAR(255),
    billing_address TEXT,
    delivery_name VARCHAR(255),
    delivery_phone VARCHAR(50),
    delivery_email VARCHAR(255),
    delivery_address TEXT,
    delivery_country VARCHAR(100),
    business_id VARCHAR(100),
    transaction_count INTEGER DEFAULT 0,
    last_transaction_date TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- リード管理
CREATE TABLE IF NOT EXISTS {schema}.leads (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    lead_code VARCHAR(20),
    customer_name VARCHAR(255) NOT NULL,
    company_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    source VARCHAR(50),
    type VARCHAR(50),
    status VARCHAR(50) DEFAULT '新規',
    temperature VARCHAR(20),
    estimated_scale VARCHAR(20),
    customer_type VARCHAR(50),
    response_speed VARCHAR(20),
    monthly_forecast NUMERIC(15, 2),
    prospect_rank VARCHAR(10),
    assigned_to INTEGER,
    converted_deal_id INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 商談データ
CREATE TABLE IF NOT EXISTS {schema}.deals (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    deal_code VARCHAR(20),
    customer_id INTEGER REFERENCES {schema}.customers(id),
    lead_id INTEGER REFERENCES {schema}.leads(id),
    title VARCHAR(255) NOT NULL,
    amount NUMERIC(15, 2),
    currency VARCHAR(10) DEFAULT 'JPY',
    status VARCHAR(50) DEFAULT 'open',
    stage VARCHAR(50) DEFAULT 'open',
    probability INTEGER DEFAULT 10,
    lost_reason VARCHAR(255),
    assigned_to INTEGER,
    expected_close_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- リード→案件への逆参照FK（leads作成時点ではdealsが未存在のため後から追加）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_leads_converted_deal'
          AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = '{schema_raw}')
    ) THEN
        ALTER TABLE {schema}.leads
            ADD CONSTRAINT fk_leads_converted_deal
            FOREIGN KEY (converted_deal_id) REFERENCES {schema}.deals(id);
    END IF;
END $$;

-- 注文データ
CREATE TABLE IF NOT EXISTS {schema}.orders (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_id INTEGER REFERENCES {schema}.customers(id),
    deal_id INTEGER REFERENCES {schema}.deals(id),
    order_number VARCHAR(100) NOT NULL,
    total_amount NUMERIC(15, 2),
    status VARCHAR(50) DEFAULT 'pending',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 操作履歴（監査ログ）
CREATE TABLE IF NOT EXISTS {schema}.audit_logs (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    user_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    record_id INTEGER,
    old_data JSONB,
    new_data JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ロール（Discord方式のカスタムロール）
CREATE TABLE IF NOT EXISTS {schema}.roles (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#6c757d',
    priority INTEGER NOT NULL DEFAULT 0,
    is_system BOOLEAN DEFAULT FALSE,
    description VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

-- ロール×権限のリンク
CREATE TABLE IF NOT EXISTS {schema}.role_permissions (
    id SERIAL PRIMARY KEY,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES public.permissions(id) ON DELETE CASCADE,
    UNIQUE(role_id, permission_id)
);

-- ユーザー×ロールのリンク（多対多）
CREATE TABLE IF NOT EXISTS {schema}.user_roles (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL REFERENCES {schema}.roles(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    assigned_by INTEGER,
    UNIQUE(user_id, role_id)
);

-- チーム
CREATE TABLE IF NOT EXISTS {schema}.teams (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(100) NOT NULL,
    leader_id INTEGER,
    description VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, name)
);

CREATE TABLE IF NOT EXISTS {schema}.team_members (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES {schema}.teams(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, user_id)
);
"""

# RLS有効化のALTER TABLE群（;で安全に分割可能）
_RLS_ENABLE_SQL = """
ALTER TABLE {schema}.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.teams ENABLE ROW LEVEL SECURITY;
"""

# テナント分離ポリシー（DO $$ ... END $$ ブロックは1ステートメントとして実行する。
# 内部の;でsplitすると$$ドル引用が分断されPostgresSyntaxErrorになるため）
_RLS_POLICY_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customers' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customers ON {schema}.customers
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_deals' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_deals ON {schema}.deals
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_orders' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_orders ON {schema}.orders
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_audit_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_audit_logs ON {schema}.audit_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_leads' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_leads ON {schema}.leads
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_roles' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_roles ON {schema}.roles
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_teams' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_teams ON {schema}.teams
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$
"""


async def seed_system_roles(db: AsyncSession, tenant_id: int, schema_name: str) -> None:
    """
    システムロール（オーナー/メンバー）をシードする。
    既に存在する場合は冪等的にupsert。

    - オーナー: priority=1000、全権限付与、is_system=TRUE（削除不可）
    - メンバー: priority=1、閲覧権限のみ、is_system=TRUE（削除不可）
    """
    # オーナーロール作成
    owner_result = await db.execute(
        text(f"""
            INSERT INTO {schema_name}.roles (tenant_id, name, color, priority, is_system, description)
            VALUES (:tid, 'オーナー', '#e74c3c', 1000, TRUE, 'テナントの全権限を持つシステムロール')
            ON CONFLICT (tenant_id, name) DO UPDATE SET priority = EXCLUDED.priority
            RETURNING id
        """),
        {"tid": tenant_id},
    )
    owner_id = owner_result.scalar_one()

    # メンバーロール作成
    member_result = await db.execute(
        text(f"""
            INSERT INTO {schema_name}.roles (tenant_id, name, color, priority, is_system, description)
            VALUES (:tid, 'メンバー', '#3498db', 1, TRUE, 'デフォルトの標準メンバーロール')
            ON CONFLICT (tenant_id, name) DO UPDATE SET priority = EXCLUDED.priority
            RETURNING id
        """),
        {"tid": tenant_id},
    )
    member_id = member_result.scalar_one()

    # 権限クリア（冪等性確保）
    await db.execute(
        text(f"DELETE FROM {schema_name}.role_permissions WHERE role_id IN (:o, :m)"),
        {"o": owner_id, "m": member_id},
    )

    # オーナー: 全権限
    await db.execute(
        text(f"""
            INSERT INTO {schema_name}.role_permissions (role_id, permission_id)
            SELECT :role_id, id FROM public.permissions
        """),
        {"role_id": owner_id},
    )

    # メンバー: デフォルト権限
    for key in MEMBER_DEFAULT_PERMISSIONS:
        await db.execute(
            text(f"""
                INSERT INTO {schema_name}.role_permissions (role_id, permission_id)
                SELECT :role_id, id FROM public.permissions WHERE key = :key
                ON CONFLICT DO NOTHING
            """),
            {"role_id": member_id, "key": key},
        )


async def create_tenant_schema(db: AsyncSession, tenant_id: int) -> str:
    """
    テナント専用スキーマを作成し、業務テーブルとRLSポリシー、
    システムロールを設定する。

    Args:
        db: データベースセッション
        tenant_id: テナントID（public.tenants.id）

    Returns:
        作成したスキーマ名（例: "tenant_001"）
    """
    # スキーマ名はtenant_{数値ID}形式（int()で型を強制しSQLインジェクション防止）
    # セキュリティ不変条件: schema_nameは必ず ^tenant_\d{3,}$ にマッチすること
    safe_id = int(tenant_id)
    schema_name = f"tenant_{safe_id:03d}"
    if not re.match(r"^tenant_\d{3,}$", schema_name):
        raise ValueError(f"不正なスキーマ名: {schema_name}")

    # 1. スキーマ作成
    await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # 2. 業務テーブル作成（DO $$ ブロックがあるため単純split不可、区切り工夫）
    tables_sql = _TENANT_TABLES_SQL.format(
        schema=schema_name,
        schema_raw=schema_name,
        tenant_id=safe_id,
    )
    # DO $$ ... END $$ ブロックを保ったまま分割するため、セミコロンでのsplitを避けて
    # ブロック単位で分割する（PostgreSQLは単一execute内で複数文を許容しないため
    # ステートメントを分ける必要がある）。
    await _execute_statements_preserving_do_blocks(db, tables_sql)

    # 3a. RLS有効化（ALTER TABLE群、;で分割可能）
    enable_sql = _RLS_ENABLE_SQL.format(schema=schema_name)
    for statement in enable_sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await db.execute(text(statement))

    # 3b. RLSポリシー（DOブロック、splitせず1ステートメントで実行）
    policy_sql = _RLS_POLICY_SQL.format(schema=schema_name, schema_raw=schema_name)
    await db.execute(text(policy_sql))

    # 4. システムロール（オーナー/メンバー）をシード
    await seed_system_roles(db, safe_id, schema_name)

    # commitは呼び出し元で行う（監査ログ等と一括でcommitするため）
    return schema_name


async def _execute_statements_preserving_do_blocks(db: AsyncSession, sql: str) -> None:
    """
    DO $$ ... END $$ ブロックを壊さずに複数SQL文を順次実行する。
    $$ 区切り内部のセミコロンは文の終わりとみなさない。
    """
    statements = _split_sql_preserving_do_blocks(sql)
    for stmt in statements:
        stmt = stmt.strip()
        if stmt:
            await db.execute(text(stmt))


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """
    DO $$ ... END $$ ブロック内の ; を保持したまま SQL をステートメント単位に分割する。

    単純に ";" で split すると、DO $$ 内部の ; が文末と誤認されて
    SQL が壊れる。$$ ペアを検出して「ブロック内」か判定する。
    """
    result: list[str] = []
    buffer: list[str] = []
    in_dollar_block = False
    i = 0
    while i < len(sql):
        if sql[i:i + 2] == "$$":
            in_dollar_block = not in_dollar_block
            buffer.append("$$")
            i += 2
            continue
        ch = sql[i]
        if ch == ";" and not in_dollar_block:
            result.append("".join(buffer))
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    if buffer:
        result.append("".join(buffer))
    return result
