/**
 * /admin/discord-config — Discord Guild 設定 + チケット機能設定 (ADR-091 KPI3)
 *
 * テナント admin が Discord サーバー（Guild）の Guild ID を登録する画面。
 * ロールマッピングは固定 (Small→Member, Large→Partner) なので表示のみ。
 * チケット機能設定（カテゴリID・ボタンチャンネルID・担当者ロール・ウェルカムメッセージ）も管理する。
 *
 * 権限:
 *   tenant.profile.view → 閲覧
 *   tenant.profile.edit → 保存
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

interface DiscordConfig {
  guild_id: string | null;
  role_member: string;
  role_partner: string;
}

interface DiscordTicketConfig {
  ticket_category_id: string | null;
  ticket_button_channel_id: string | null;
  staff_role_id: string | null;
  welcome_template: string;
  small_channel_id: string | null;
  large_channel_id: string | null;
}

export default function DiscordConfigPage() {
  const { t } = useTranslation();
  const { hasPermission, loading: permsLoading } = usePermissions();

  // Guild 設定
  const [config, setConfig] = useState<DiscordConfig | null>(null);
  const [guildId, setGuildId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  // チケット設定
  const [ticketConfig, setTicketConfig] = useState<DiscordTicketConfig | null>(null);
  const [ticketCategoryId, setTicketCategoryId] = useState("");
  const [ticketButtonChannelId, setTicketButtonChannelId] = useState("");
  const [staffRoleId, setStaffRoleId] = useState("");
  const [welcomeTemplate, setWelcomeTemplate] = useState(
    "ご連絡ありがとうございます。こちらのチャンネルでサポートいたします。"
  );
  const [smallChannelId, setSmallChannelId] = useState("");
  const [largeChannelId, setLargeChannelId] = useState("");
  const [ticketSaving, setTicketSaving] = useState(false);
  const [ticketError, setTicketError] = useState("");
  const [ticketSaved, setTicketSaved] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState("");
  const [deployDone, setDeployDone] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const [data, ticketData] = await Promise.all([
          api.get<DiscordConfig>("/admin/discord-config"),
          api.get<DiscordTicketConfig>("/admin/discord-ticket-config"),
        ]);
        setConfig(data);
        setGuildId(data.guild_id ?? "");
        setTicketConfig(ticketData);
        setTicketCategoryId(ticketData.ticket_category_id ?? "");
        setTicketButtonChannelId(ticketData.ticket_button_channel_id ?? "");
        setStaffRoleId(ticketData.staff_role_id ?? "");
        setWelcomeTemplate(ticketData.welcome_template);
        setSmallChannelId(ticketData.small_channel_id ?? "");
        setLargeChannelId(ticketData.large_channel_id ?? "");
      } catch {
        setError(t("discordConfig.loadError"));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [t]);

  const handleSave = async () => {
    if (!guildId.trim() || !/^\d{17,20}$/.test(guildId.trim())) {
      setError(t("discordConfig.invalidGuildId"));
      return;
    }
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const updated = await api.put<DiscordConfig>("/admin/discord-config", { guild_id: guildId.trim() });
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError(t("discordConfig.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const handleTicketSave = async () => {
    const snowflakeRe = /^\d{17,20}$/;
    if (!ticketCategoryId.trim() || !snowflakeRe.test(ticketCategoryId.trim())) {
      setTicketError(t("discordTicketConfig.invalidSnowflake"));
      return;
    }
    if (!ticketButtonChannelId.trim() || !snowflakeRe.test(ticketButtonChannelId.trim())) {
      setTicketError(t("discordTicketConfig.invalidSnowflake"));
      return;
    }
    if (staffRoleId.trim() && !snowflakeRe.test(staffRoleId.trim())) {
      setTicketError(t("discordTicketConfig.invalidSnowflake"));
      return;
    }
    if (smallChannelId.trim() && !snowflakeRe.test(smallChannelId.trim())) {
      setTicketError(t("discordTicketConfig.invalidSnowflake"));
      return;
    }
    if (largeChannelId.trim() && !snowflakeRe.test(largeChannelId.trim())) {
      setTicketError(t("discordTicketConfig.invalidSnowflake"));
      return;
    }
    setTicketSaving(true);
    setTicketError("");
    setTicketSaved(false);
    try {
      const updated = await api.put<DiscordTicketConfig>("/admin/discord-ticket-config", {
        ticket_category_id: ticketCategoryId.trim(),
        ticket_button_channel_id: ticketButtonChannelId.trim(),
        staff_role_id: staffRoleId.trim() || null,
        welcome_template: welcomeTemplate,
        small_channel_id: smallChannelId.trim() || null,
        large_channel_id: largeChannelId.trim() || null,
      });
      setTicketConfig(updated);
      setSmallChannelId(updated.small_channel_id ?? "");
      setLargeChannelId(updated.large_channel_id ?? "");
      setTicketSaved(true);
      setTimeout(() => setTicketSaved(false), 3000);
    } catch {
      setTicketError(t("discordTicketConfig.saveError"));
    } finally {
      setTicketSaving(false);
    }
  };

  const handleDeployButton = async () => {
    setDeploying(true);
    setDeployError("");
    setDeployDone(false);
    try {
      await api.post("/admin/discord-ticket-config/deploy-button", {});
      setDeployDone(true);
      setTimeout(() => setDeployDone(false), 5000);
    } catch {
      setDeployError(t("discordTicketConfig.deployError"));
    } finally {
      setDeploying(false);
    }
  };

  const canEdit = hasPermission("tenant.profile.edit");

  if (permsLoading || loading) {
    return (
      <PageLayout navKey="nav.discordConfig">
        <p className="text-token-text-secondary text-sm">{t("loading")}</p>
      </PageLayout>
    );
  }

  return (
    <PageLayout navKey="nav.discordConfig">
      <div className="max-w-lg space-y-10">

        {/* ── Guild ID 設定 ── */}
        <section className="space-y-6">
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordConfig.guildIdLabel")}
            </label>
            <input
              type="text"
              value={guildId}
              onChange={(e) => setGuildId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordConfig.guildIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordConfig.guildIdHint")}
            </p>
          </div>

          {/* ロールマッピング（固定・表示のみ） */}
          {config && (
            <div className="rounded border border-token-border bg-token-bg-subtle p-4 space-y-2">
              <p className="text-sm font-medium text-token-text-primary">
                {t("discordConfig.roleMappingTitle")}
              </p>
              <div className="text-sm text-token-text-secondary space-y-1">
                <p>
                  <span className="font-medium">{t("leads.scale_small")}</span>
                  {" → "}
                  <span className="font-mono bg-token-bg-muted px-1.5 py-0.5 rounded text-xs">
                    {config.role_member}
                  </span>
                </p>
                <p>
                  <span className="font-medium">{t("leads.scale_large")}</span>
                  {" → "}
                  <span className="font-mono bg-token-bg-muted px-1.5 py-0.5 rounded text-xs">
                    {config.role_partner}
                  </span>
                </p>
              </div>
            </div>
          )}

          {error && <p className="text-sm text-red-500">{error}</p>}
          {saved && <p className="text-sm text-green-600">{t("discordConfig.saved")}</p>}

          {canEdit && (
            <button onClick={handleSave} disabled={saving} className="btn btn-primary">
              {saving ? t("saving") : t("save")}
            </button>
          )}
        </section>

        <hr className="border-token-border" />

        {/* ── チケット機能設定 ── */}
        <section className="space-y-6">
          <div>
            <p className="text-base font-semibold text-token-text-primary">
              {t("discordTicketConfig.title")}
            </p>
            <p className="mt-1 text-sm text-token-text-secondary">
              {t("discordTicketConfig.description")}
            </p>
          </div>

          {/* カテゴリ ID */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.categoryIdLabel")}
            </label>
            <input
              type="text"
              value={ticketCategoryId}
              onChange={(e) => setTicketCategoryId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.categoryIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.categoryIdHint")}
            </p>
          </div>

          {/* ボタン設置チャンネル ID */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.buttonChannelIdLabel")}
            </label>
            <input
              type="text"
              value={ticketButtonChannelId}
              onChange={(e) => setTicketButtonChannelId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.buttonChannelIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.buttonChannelIdHint")}
            </p>
          </div>

          {/* 担当者ロール ID（任意） */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.staffRoleIdLabel")}
            </label>
            <input
              type="text"
              value={staffRoleId}
              onChange={(e) => setStaffRoleId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.staffRoleIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.staffRoleIdHint")}
            </p>
          </div>

          {/* ウェルカムメッセージ */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.welcomeTemplateLabel")}
            </label>
            <textarea
              value={welcomeTemplate}
              onChange={(e) => setWelcomeTemplate(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.welcomeTemplatePlaceholder")}
              maxLength={500}
              rows={3}
              className="input w-full resize-none"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.welcomeTemplateHint")}
            </p>
          </div>

          {/* 小口顧客向けチャンネル ID（任意） */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.smallChannelIdLabel")}
            </label>
            <input
              type="text"
              value={smallChannelId}
              onChange={(e) => setSmallChannelId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.scaleChannelIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.smallChannelIdHint")}
            </p>
          </div>

          {/* 大口顧客向けチャンネル ID（任意） */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-token-text-primary">
              {t("discordTicketConfig.largeChannelIdLabel")}
            </label>
            <input
              type="text"
              value={largeChannelId}
              onChange={(e) => setLargeChannelId(e.target.value)}
              disabled={!canEdit}
              placeholder={t("discordTicketConfig.scaleChannelIdPlaceholder")}
              className="input w-full"
            />
            <p className="text-xs text-token-text-secondary">
              {t("discordTicketConfig.largeChannelIdHint")}
            </p>
          </div>

          {ticketError && <p className="text-sm text-red-500">{ticketError}</p>}
          {ticketSaved && <p className="text-sm text-green-600">{t("discordTicketConfig.saved")}</p>}

          {canEdit && (
            <button onClick={handleTicketSave} disabled={ticketSaving} className="btn btn-primary">
              {ticketSaving ? t("saving") : t("save")}
            </button>
          )}

          {/* ── ボタン設置 (Phase 3) ── */}
          {canEdit && ticketConfig?.ticket_button_channel_id && (
            <div className="mt-6 rounded border border-token-border bg-token-bg-subtle p-4 space-y-3">
              <p className="text-sm font-medium text-token-text-primary">
                {t("discordTicketConfig.deployButtonTitle")}
              </p>
              <p className="text-xs text-token-text-secondary">
                {t("discordTicketConfig.deployButtonHint")}
              </p>
              {deployError && <p className="text-sm text-red-500">{deployError}</p>}
              {deployDone && <p className="text-sm text-green-600">{t("discordTicketConfig.deployDone")}</p>}
              <button
                onClick={handleDeployButton}
                disabled={deploying}
                className="btn btn-secondary"
              >
                {deploying ? t("discordTicketConfig.deploying") : t("discordTicketConfig.deployButton")}
              </button>
            </div>
          )}
        </section>
      </div>
    </PageLayout>
  );
}
