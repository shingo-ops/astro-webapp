-- migrations/039_create_data_deletion_logs.sql
-- Meta App Review §B3: Data Deletion Callback の監査ログテーブル
-- 仕様書: data_deletion_instructions.docx v1.0 §5.1
-- 注意: テナント横断のため public schema 配下に配置（per-tenant ではない）
-- idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS で再実行 no-op

CREATE TABLE IF NOT EXISTS public.data_deletion_logs (
    id BIGSERIAL PRIMARY KEY,

    -- 内部管理用受付 ID (REQ-YYYYMMDD-xxx)
    request_id VARCHAR(50) NOT NULL UNIQUE,

    -- ユーザーへ発行する確認コード (DEL-YYYYMMDD-xxxx)
    -- ステータス確認 URL のクエリパラメータとして使用
    confirmation_code VARCHAR(50) NOT NULL UNIQUE,

    -- 申請経路: meta_callback (Meta Platform 経由) / email (メール直接連絡)
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('meta_callback', 'email')),

    -- ユーザー種別: user (利用者) / end_user (エンドユーザー)
    user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('user', 'end_user')),

    -- 識別子の種類と値
    -- end_user の場合: identifier_type='meta_user_id', identifier_value=<PSID/IGSID>
    -- user の場合: identifier_type='email' or 'staff_id', identifier_value=<...>
    identifier_type VARCHAR(50),
    identifier_value VARCHAR(200),

    -- 該当テナント（end_user 削除でテナント特定できた場合）
    -- NULL = テナント不明 / 全テナント検索済 / メタ削除依頼直後で未確定
    tenant_id INTEGER,

    -- タイムスタンプ
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- ステータス遷移
    -- received -> verifying -> processing -> completed | failed | rejected
    status VARCHAR(20) NOT NULL DEFAULT 'received'
        CHECK (status IN (
            'received', 'verifying', 'processing',
            'completed', 'failed', 'rejected'
        )),

    -- 削除実績の JSON 記録
    -- 例: {"meta_messages": 12, "lead_channels": 1, "tenants_searched": 3}
    data_items_deleted JSONB,

    -- 失敗時のエラーメッセージ
    error_message TEXT,

    -- 対応者識別 (将来 staff 認証付与時に使用、Meta callback は 'meta_callback_auto')
    handled_by VARCHAR(100),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 索引（仕様書 §5.1 に明記）
CREATE INDEX IF NOT EXISTS idx_deletion_logs_request_id
    ON public.data_deletion_logs (request_id);

CREATE INDEX IF NOT EXISTS idx_deletion_logs_confirmation_code
    ON public.data_deletion_logs (confirmation_code);

CREATE INDEX IF NOT EXISTS idx_deletion_logs_status
    ON public.data_deletion_logs (status);

-- updated_at 自動更新トリガー（既存パターンに倣う）
CREATE OR REPLACE FUNCTION public.set_updated_at_data_deletion_logs()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_data_deletion_logs
    ON public.data_deletion_logs;

CREATE TRIGGER trigger_set_updated_at_data_deletion_logs
    BEFORE UPDATE ON public.data_deletion_logs
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at_data_deletion_logs();
