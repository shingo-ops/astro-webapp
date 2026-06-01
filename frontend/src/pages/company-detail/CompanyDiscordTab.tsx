/**
 * 会社詳細 — Discord タブ（ADR-089 Sprint 2）
 * company_discord の表示・編集をインラインフォームで行う。
 */

import { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { DiscordFormState } from "./company-detail.types";

interface Props {
  discordForm: DiscordFormState;
  setDiscordForm: (f: DiscordFormState) => void;
  discordDirty: boolean;
  setDiscordDirty: (v: boolean) => void;
  discordSubmitting: boolean;
  handleDiscordSubmit: (e: FormEvent) => void;
  handleDiscordDelete: () => void;
  canEdit: boolean;
}

export function CompanyDiscordTab({
  discordForm, setDiscordForm,
  discordDirty, setDiscordDirty,
  discordSubmitting,
  handleDiscordSubmit, handleDiscordDelete,
  canEdit,
}: Props) {
  const { t } = useTranslation();

  const update = (patch: Partial<DiscordFormState>) => {
    setDiscordForm({ ...discordForm, ...patch });
    setDiscordDirty(true);
  };

  return (
    <div>
      <form onSubmit={handleDiscordSubmit}>
        <div className="form-grid">
          <div className="form-row">
            <label>
              <input
                type="checkbox"
                checked={discordForm.is_joined}
                onChange={(e) => update({ is_joined: e.target.checked })}
                disabled={!canEdit}
              />
              {" "}{t("discord.isJoined")}
            </label>
          </div>
          <div className="form-row">
            <label>{t("discord.channelId")}</label>
            <input
              value={discordForm.channel_id}
              onChange={(e) => update({ channel_id: e.target.value })}
              disabled={!canEdit}
              maxLength={50}
            />
          </div>
          <div className="form-row">
            <label>{t("discord.userId")}</label>
            <input
              value={discordForm.user_id}
              onChange={(e) => update({ user_id: e.target.value })}
              disabled={!canEdit}
              maxLength={50}
            />
          </div>
          <div className="form-row">
            <label>{t("discord.invoiceWebhook")}</label>
            <input
              value={discordForm.invoice_webhook}
              onChange={(e) => update({ invoice_webhook: e.target.value })}
              disabled={!canEdit}
              placeholder="https://discord.com/api/webhooks/..."
            />
          </div>
          <div className="form-row">
            <label>{t("discord.shipmentWebhook")}</label>
            <input
              value={discordForm.shipment_webhook}
              onChange={(e) => update({ shipment_webhook: e.target.value })}
              disabled={!canEdit}
              placeholder="https://discord.com/api/webhooks/..."
            />
          </div>
        </div>

        {canEdit && (
          <div className="form-actions" style={{ marginTop: "var(--space-3)" }}>
            <button
              type="submit"
              className="btn-sm btn-primary"
              disabled={!discordDirty || discordSubmitting}
            >
              {discordSubmitting ? t("common.saving") : t("common.save")}
            </button>
            <button
              type="button"
              className="btn-sm btn-danger"
              onClick={handleDiscordDelete}
              style={{ marginLeft: "var(--space-2)" }}
            >
              {t("discord.deleteSettings")}
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
