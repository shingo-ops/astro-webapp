/**
 * /admin/discord-config — Discord Guild 設定 (Sprint D2 / F5)
 *
 * テナント admin が Discord サーバー（Guild）の Guild ID を登録する画面。
 * ロールマッピングは固定 (Small→Member, Large→Partner) なので表示のみ。
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

export default function DiscordConfigPage() {
  const { t } = useTranslation();
  const { hasPermission, loading: permsLoading } = usePermissions();
  const [config, setConfig] = useState<DiscordConfig | null>(null);
  const [guildId, setGuildId] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const res = await api.get("/admin/discord-config");
        const data: DiscordConfig = res.data;
        setConfig(data);
        setGuildId(data.guild_id ?? "");
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
      const res = await api.put("/admin/discord-config", { guild_id: guildId.trim() });
      setConfig(res.data);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {
      setError(t("discordConfig.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const canEdit = hasPermission("tenant.profile.edit");

  if (permsLoading || loading) {
    return (
      <PageLayout title={t("discordConfig.title")}>
        <p className="text-token-text-secondary text-sm">{t("loading")}</p>
      </PageLayout>
    );
  }

  return (
    <PageLayout title={t("discordConfig.title")}>
      <div className="max-w-lg space-y-6">
        <p className="text-token-text-secondary text-sm">
          {t("discordConfig.description")}
        </p>

        {/* Guild ID 入力 */}
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

        {error && (
          <p className="text-sm text-red-500">{error}</p>
        )}
        {saved && (
          <p className="text-sm text-green-600">{t("discordConfig.saved")}</p>
        )}

        {canEdit && (
          <button
            onClick={handleSave}
            disabled={saving}
            className="btn btn-primary"
          >
            {saving ? t("saving") : t("save")}
          </button>
        )}
      </div>
    </PageLayout>
  );
}
