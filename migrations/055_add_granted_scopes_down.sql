-- ADR-041 ロールバック: granted_scopes 列を削除
ALTER TABLE {schema}.tenant_meta_config
    DROP COLUMN IF EXISTS granted_scopes;
