-- Rollback for migration 067.
DELETE FROM public.permissions WHERE key IN (
    'central.parse_review.approve', 'central.parse_review.reject'
);
ALTER TABLE public.discord_inbound_messages DROP COLUMN IF EXISTS version;
