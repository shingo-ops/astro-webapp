-- Phase 1-B-1 / Migration 026: customer_contact_channels テーブル作成
--
-- 背景:
--   Phase 1-A では customers.primary_contact_channel VARCHAR(30) の単一列で
--   「主連絡ツール」を管理していた。しんごさん 2026-04-23 指示で
--   「1顧客が複数の連絡ツールを用途別に持つ」運用に変更する。
--     例: Aさん → WhatsApp(商談用) + Discord(発送通知用)
--
-- 設計:
--   customer_contact_channels: customer_id × channel × purpose の多対多テーブル
--   - channel: whatsapp / discord / instagram / facebook_messenger / line_id /
--              telegram / email / phone / referral などのenum値
--   - purpose: "商談用" / "発送通知用" / "請求書送付用" 等、自由記述（任意）
--   - is_primary: 「主連絡ツール」フラグ。1顧客につき最大1行 TRUE（部分UNIQUE INDEXで制約）
--
--   customer_discord（Phase 1-A）との関係:
--     - customer_discord テーブルは残す（channel_id/webhook URL 等の Discord 固有情報を保持）
--     - customer_contact_channels に channel='discord' の行を追加して「Discord を連絡手段として使用中」を宣言
--     - 両テーブルは独立に管理（案α）
--
-- 冪等性:
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE POLICY は pg_policies 存在確認
--   - 非テンプレート、DO block で pg_namespace 走査して全 tenant_NNN schema に適用
--
-- 変更履歴:
--   2026-04-23: 初版作成（Phase 1-B-1）

DO $$
DECLARE
    schema_rec RECORD;
    created_count INTEGER := 0;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- customers テーブルが存在するスキーマのみ対象
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customers'
        ) THEN
            CONTINUE;
        END IF;

        -- trg_set_updated_at() 関数が未定義のスキーマに備えて保険で作成（冪等）
        -- 本来 migration 015 で作成されているが、過去に手動作成されたテナントに欠けている可能性
        EXECUTE format($q$
            CREATE OR REPLACE FUNCTION %I.trg_set_updated_at()
            RETURNS TRIGGER AS $fn$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $fn$ LANGUAGE plpgsql
        $q$, schema_rec.nspname);

        -- テーブル作成（冪等: IF NOT EXISTS）
        EXECUTE format($q$
            CREATE TABLE IF NOT EXISTS %I.customer_contact_channels (
                id SERIAL PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES %I.customers(id) ON DELETE CASCADE,
                channel VARCHAR(30) NOT NULL,
                purpose VARCHAR(50),
                is_primary BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        $q$, schema_rec.nspname, schema_rec.nspname);

        -- インデックス（冪等）
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_ccc_customer_id ON %I.customer_contact_channels (customer_id)',
            schema_rec.nspname
        );
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS idx_ccc_channel ON %I.customer_contact_channels (channel)',
            schema_rec.nspname
        );
        -- 部分UNIQUE: 1顧客につき is_primary=TRUE の行は最大1つ
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_ccc_one_primary_per_customer '
            'ON %I.customer_contact_channels (customer_id) WHERE is_primary = TRUE',
            schema_rec.nspname
        );

        -- updated_at トリガ（関数は tenant.py テンプレで既に作成済の想定）
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
            WHERE tgname = 'trg_ccc_updated_at'
              AND tgrelid = format('%I.customer_contact_channels', schema_rec.nspname)::regclass
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER trg_ccc_updated_at BEFORE UPDATE ON %I.customer_contact_channels '
                'FOR EACH ROW EXECUTE FUNCTION %I.trg_set_updated_at()',
                schema_rec.nspname, schema_rec.nspname
            );
        END IF;

        -- RLS 有効化（冪等）
        EXECUTE format(
            'ALTER TABLE %I.customer_contact_channels ENABLE ROW LEVEL SECURITY',
            schema_rec.nspname
        );

        -- RLS ポリシー: customers を経由してテナント分離
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE policyname = 'tenant_isolation_customer_contact_channels'
              AND schemaname = schema_rec.nspname
        ) THEN
            EXECUTE format($q$
                CREATE POLICY tenant_isolation_customer_contact_channels ON %I.customer_contact_channels
                    USING (EXISTS (
                        SELECT 1 FROM %I.customers c
                        WHERE c.id = customer_contact_channels.customer_id
                          AND c.tenant_id = public.current_tenant_id()
                    ))
            $q$, schema_rec.nspname, schema_rec.nspname);
        END IF;

        created_count := created_count + 1;
        RAISE NOTICE 'migration 026: %: customer_contact_channels 作成完了', schema_rec.nspname;
    END LOOP;
    RAISE NOTICE 'migration 026: 全 % テナントに customer_contact_channels を適用', created_count;
END $$;
