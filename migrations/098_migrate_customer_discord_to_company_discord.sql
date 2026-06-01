-- Migration 098: customer_discord データを company_discord へ移行（ADR-089 Sprint 1 / F2）
--
-- 目的:
--   既存の customer_discord 行を company_discord に移行する。
--   customers.company_name と companies.name の正規化一致でマッピングする。
--
-- マッピング方法:
--   customer_discord.customer_id → customers.company_name (LOWER/TRIM 正規化)
--   → companies.name (LOWER/TRIM 正規化) で JOIN
--
-- 安全弁:
--   - customer_discord が 0 件なら NOTICE を出して skip する
--   - マッピングできない行がある場合は EXCEPTION で中断する（データ損失防止）
--   - company_discord に既に行が存在する場合は INSERT をスキップ（冪等）
--
-- 依存: migration 097 (company_discord テーブル) / customers テーブル（まだ存在）
-- 適用対象: 全テナント（pg_namespace 走査）
-- 冪等: INSERT ... ON CONFLICT DO NOTHING

DO $$
DECLARE
    schema_rec RECORD;
    customer_discord_count INTEGER;
    unmapped_count INTEGER;
    unmapped_names TEXT;
    inserted_count INTEGER;
BEGIN
    FOR schema_rec IN
        SELECT nspname FROM pg_namespace
        WHERE nspname ~ '^tenant_\d+$'
        ORDER BY nspname
    LOOP
        -- customer_discord テーブルが存在しないテナントはスキップ
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'customer_discord'
        ) THEN
            RAISE NOTICE 'migration 098: %: customer_discord が存在しないためスキップ', schema_rec.nspname;
            CONTINUE;
        END IF;

        -- company_discord テーブルが存在しないテナントはスキップ（097 未適用）
        IF NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = schema_rec.nspname AND tablename = 'company_discord'
        ) THEN
            RAISE NOTICE 'migration 098: %: company_discord が存在しないためスキップ（097 を先に適用してください）', schema_rec.nspname;
            CONTINUE;
        END IF;

        -- AC2.4: customer_discord が 0 件なら skip
        EXECUTE format('SELECT COUNT(*) FROM %I.customer_discord', schema_rec.nspname)
            INTO customer_discord_count;

        IF customer_discord_count = 0 THEN
            RAISE NOTICE 'migration 098: %: customer_discord が 0 件のためスキップ', schema_rec.nspname;
            CONTINUE;
        END IF;

        RAISE NOTICE 'migration 098: %: customer_discord % 件を移行開始', schema_rec.nspname, customer_discord_count;

        -- AC2.3: マッピングできない行の検出（EXCEPTION で中断）
        EXECUTE format($q$
            SELECT COUNT(*)
            FROM %I.customer_discord cd
            JOIN %I.customers cu ON cu.id = cd.customer_id
            WHERE NOT EXISTS (
                SELECT 1 FROM %I.companies co
                WHERE LOWER(TRIM(co.name)) = LOWER(TRIM(cu.company_name))
            )
        $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname)
            INTO unmapped_count;

        IF unmapped_count > 0 THEN
            -- マッピングできない customer_name を取得してエラーメッセージに含める
            EXECUTE format($q$
                SELECT string_agg(cu.company_name, ', ')
                FROM %I.customer_discord cd
                JOIN %I.customers cu ON cu.id = cd.customer_id
                WHERE NOT EXISTS (
                    SELECT 1 FROM %I.companies co
                    WHERE LOWER(TRIM(co.name)) = LOWER(TRIM(cu.company_name))
                )
            $q$, schema_rec.nspname, schema_rec.nspname, schema_rec.nspname)
                INTO unmapped_names;

            RAISE EXCEPTION
                'migration 098: %: % 件のマッピング失敗。companies に存在しない顧客名: [%]。'
                ' 手動でマッピングを確認してから再実行してください。',
                schema_rec.nspname, unmapped_count, unmapped_names;
        END IF;

        -- AC2.1/AC2.2: company_discord への INSERT（ON CONFLICT DO NOTHING で冪等）
        EXECUTE format($q$
            INSERT INTO %I.company_discord (
                company_id,
                is_joined,
                channel_id,
                user_id,
                invoice_webhook,
                shipment_webhook,
                created_at,
                updated_at
            )
            SELECT
                co.id AS company_id,
                cd.is_joined,
                cd.channel_id,
                cd.user_id,
                cd.invoice_webhook,
                cd.shipment_webhook,
                cd.created_at,
                cd.updated_at
            FROM %I.customer_discord cd
            JOIN %I.customers cu ON cu.id = cd.customer_id
            JOIN %I.companies co ON LOWER(TRIM(co.name)) = LOWER(TRIM(cu.company_name))
            ON CONFLICT (company_id) DO NOTHING
        $q$,
            schema_rec.nspname,
            schema_rec.nspname, schema_rec.nspname, schema_rec.nspname
        );

        GET DIAGNOSTICS inserted_count = ROW_COUNT;

        -- 検証: 移行後の company_discord 件数が customer_discord 件数と一致するか確認
        -- （ON CONFLICT DO NOTHING のため既存行がある場合は inserted_count < customer_discord_count になりうる）
        RAISE NOTICE 'migration 098: %: % 件挿入完了（customer_discord % 件）',
            schema_rec.nspname, inserted_count, customer_discord_count;
    END LOOP;

    RAISE NOTICE 'migration 098: 全テナントのデータ移行完了';
END $$;
