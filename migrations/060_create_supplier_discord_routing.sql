-- ============================================================================
-- Migration 060: public.supplier_discord_routing (仕入元↔Discord channel 紐付け)
--
-- 経緯:
--   spec.md v1.1 F1 / F5 AC5.3: 受信メッセージの supplier_id 解決および
--   未登録 guild からのメッセージを ignored_routing として skip する基準テーブル。
--
-- 設計:
--   - public schema 中央共有
--   - UNIQUE (discord_guild_id, discord_channel_id) で同一 channel の重複登録防止
--   - is_active で論理削除可能
--
-- 関連:
--   .claude-pipeline/spec.md F1 / F5 / AC2.5 (UI で routing 設定可能)
--
-- 作成日: 2026-05-21
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.supplier_discord_routing (
    id                  SERIAL PRIMARY KEY,
    supplier_id         INTEGER NOT NULL REFERENCES public.suppliers(id) ON DELETE CASCADE,
    discord_guild_id    VARCHAR(50) NOT NULL,
    discord_channel_id  VARCHAR(50) NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    notes               TEXT,
    created_by          INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discord_guild_id, discord_channel_id)
);

CREATE INDEX IF NOT EXISTS idx_sdr_supplier
    ON public.supplier_discord_routing (supplier_id);
CREATE INDEX IF NOT EXISTS idx_sdr_active_channel
    ON public.supplier_discord_routing (discord_channel_id)
    WHERE is_active = TRUE;

-- updated_at トリガ
CREATE OR REPLACE FUNCTION public.set_updated_at_sdr()
RETURNS TRIGGER AS $upd$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$upd$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_set_updated_at_sdr ON public.supplier_discord_routing;
CREATE TRIGGER trigger_set_updated_at_sdr
    BEFORE UPDATE ON public.supplier_discord_routing
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at_sdr();

COMMENT ON TABLE public.supplier_discord_routing IS
    'spec F1/F5 AC5.3: 仕入元 supplier_id と Discord guild/channel の紐付け（routing マスタ）';

-- ============================================================================
-- Rollback:
--   DROP TRIGGER IF EXISTS trigger_set_updated_at_sdr ON public.supplier_discord_routing;
--   DROP FUNCTION IF EXISTS public.set_updated_at_sdr();
--   DROP TABLE IF EXISTS public.supplier_discord_routing;
-- ============================================================================
