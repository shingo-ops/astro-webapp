from __future__ import annotations

"""
テナント別スキーマ自動生成サービス。

新しいテナントが登録されるたびに:
  1. public.tenants に企業情報を保存
  2. tenant_{id:03d} スキーマを自動作成
  3. スキーマ内に業務テーブル（customers, deals, orders, audit_logs）を作成
  4. Row Level Security（RLS）ポリシーを自動適用

たとえ話:
  新しい入居者（テナント企業）が契約したら、
  専用の鍵付き個室が自動的に用意される仕組み。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# テナントスキーマ内に作成する業務テーブルのSQL定義
_TENANT_TABLES_SQL = """
-- 顧客データ
CREATE TABLE IF NOT EXISTS {schema}.customers (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    company VARCHAR(255),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 商談データ
CREATE TABLE IF NOT EXISTS {schema}.deals (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    customer_id INTEGER REFERENCES {schema}.customers(id),
    title VARCHAR(255) NOT NULL,
    amount NUMERIC(15, 2),
    status VARCHAR(50) DEFAULT 'open',
    expected_close_date DATE,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

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
"""

# Row Level Security ポリシーの設定SQL
_RLS_SQL = """
-- RLSを有効化（金庫の二重ロックをONにする）
ALTER TABLE {schema}.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE {schema}.audit_logs ENABLE ROW LEVEL SECURITY;

-- テナント分離ポリシー（自テナントのデータのみアクセス可能）
DO $$
BEGIN
    -- customers
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_customers' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_customers ON {schema}.customers
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- deals
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_deals' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_deals ON {schema}.deals
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- orders
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_orders' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_orders ON {schema}.orders
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
    -- audit_logs
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'tenant_isolation_audit_logs' AND schemaname = '{schema_raw}') THEN
        CREATE POLICY tenant_isolation_audit_logs ON {schema}.audit_logs
            USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
    END IF;
END $$;
"""


async def create_tenant_schema(db: AsyncSession, tenant_id: int) -> str:
    """
    テナント専用スキーマを作成し、業務テーブルとRLSポリシーを設定する。

    Args:
        db: データベースセッション
        tenant_id: テナントID（public.tenants.id）

    Returns:
        作成したスキーマ名（例: "tenant_001"）
    """
    # スキーマ名はtenant_{数値ID}形式（int()で型を強制しSQLインジェクション防止）
    safe_id = int(tenant_id)
    schema_name = f"tenant_{safe_id:03d}"

    # 1. スキーマ作成
    await db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))

    # 2. 業務テーブル作成
    tables_sql = _TENANT_TABLES_SQL.format(
        schema=schema_name,
        tenant_id=safe_id,
    )
    for statement in tables_sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await db.execute(text(statement))

    # 3. RLSポリシー設定
    rls_sql = _RLS_SQL.format(
        schema=schema_name,
        schema_raw=schema_name,
    )
    for statement in rls_sql.strip().split(";"):
        statement = statement.strip()
        if statement:
            await db.execute(text(statement))

    # commitは呼び出し元で行う（監査ログ等と一括でcommitするため）
    return schema_name
