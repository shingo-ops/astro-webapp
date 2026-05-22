-- Rollback: migration 069 (tenant_profile)
-- 緊急時のみ手動実行。本番では基本使わない。

DO $rb$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT nspname FROM pg_namespace WHERE nspname ~ '^tenant_\d+$' LOOP
        EXECUTE format('DROP TABLE IF EXISTS %I.tenant_profile CASCADE', r.nspname);
        EXECUTE format('DROP FUNCTION IF EXISTS %I.set_updated_at_tenant_profile() CASCADE', r.nspname);
    END LOOP;
END $rb$;

DELETE FROM public.permissions WHERE key IN ('tenant.profile.view', 'tenant.profile.edit');
