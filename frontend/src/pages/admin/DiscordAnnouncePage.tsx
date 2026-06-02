/**
 * /admin/discord-announce — Discord アナウンス投稿 (ADR-091 KPI4)
 *
 * テナント admin が Discord チャンネルへアナウンスを投稿する画面。
 * SalesAnchor からそのまま投稿でき Discord を開く必要がない（KGI）。
 *
 * 権限: tenant.profile.edit → 投稿
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

export default function DiscordAnnouncePage() {
  const { t } = useTranslation();
  const { hasPermission, loading: permsLoading } = usePermissions();

  const [channelId, setChannelId] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const handleSend = async () => {
    const trimmedId = channelId.trim();
    const trimmedMsg = message.trim();

    if (!trimmedId || !/^\d{17,20}$/.test(trimmedId)) {
      setError(t("discordAnnounce.invalidChannelId"));
      return;
    }
    if (!trimmedMsg) {
      setError(t("discordAnnounce.messageRequired"));
      return;
    }

    setSending(true);
    setError("");
    setSent(false);

    try {
      await api.post("/discord/announce", {
        channel_id: trimmedId,
        message: trimmedMsg,
      });
      setSent(true);
      setMessage("");
      setTimeout(() => setSent(false), 4000);
    } catch {
      setError(t("discordAnnounce.sendError"));
    } finally {
      setSending(false);
    }
  };

  const canEdit = hasPermission("tenant.profile.edit");

  if (permsLoading) {
    return (
      <PageLayout navKey="nav.discordAnnounce">
        <p className="text-token-text-secondary text-sm">{t("loading")}</p>
      </PageLayout>
    );
  }

  return (
    <PageLayout navKey="nav.discordAnnounce">
      <div className="max-w-lg space-y-6">
        <p className="text-token-text-secondary text-sm">
          {t("discordAnnounce.description")}
        </p>

        {/* チャンネル ID */}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-token-text-primary">
            {t("discordAnnounce.channelIdLabel")}
          </label>
          <input
            type="text"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            disabled={!canEdit}
            placeholder={t("discordAnnounce.channelIdPlaceholder")}
            className="input w-full"
          />
          <p className="text-xs text-token-text-secondary">
            {t("discordAnnounce.channelIdHint")}
          </p>
        </div>

        {/* メッセージ */}
        <div className="space-y-2">
          <label className="block text-sm font-medium text-token-text-primary">
            {t("discordAnnounce.messageLabel")}
          </label>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={!canEdit}
            placeholder={t("discordAnnounce.messagePlaceholder")}
            maxLength={2000}
            rows={6}
            className="input w-full resize-y"
          />
          <p className="text-xs text-token-text-secondary text-right">
            {message.length} / 2000
          </p>
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}
        {sent && <p className="text-sm text-green-600">{t("discordAnnounce.sent")}</p>}

        {canEdit && (
          <button
            onClick={handleSend}
            disabled={sending || !channelId.trim() || !message.trim()}
            className="btn btn-primary"
          >
            {sending ? t("discordAnnounce.sending") : t("discordAnnounce.send")}
          </button>
        )}
      </div>
    </PageLayout>
  );
}
