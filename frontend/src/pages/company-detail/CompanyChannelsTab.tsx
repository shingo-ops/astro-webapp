/**
 * 会社詳細 — 販売チャネルタブ。
 * カンマ区切り UI で sales_channels を全置換する。
 */

import { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { Company } from "./company-detail.types";

interface Props {
  company: Company;
  channelsText: string;
  setChannelsText: (v: string) => void;
  channelsDirty: boolean;
  setChannelsDirty: (v: boolean) => void;
  channelsSubmitting: boolean;
  handleChannelsSubmit: (e: FormEvent) => void;
  canEdit: boolean;
}

export function CompanyChannelsTab({
  company, channelsText, setChannelsText, channelsDirty, setChannelsDirty,
  channelsSubmitting, handleChannelsSubmit, canEdit,
}: Props) {
  const { t } = useTranslation();

  return (
    <form onSubmit={handleChannelsSubmit} className="form-grid">
      <div className="form-row">
        <label>{t("companies.salesChannelsLabel")}</label>
        <input disabled={!canEdit} value={channelsText}
          onChange={(e) => { setChannelsText(e.target.value); setChannelsDirty(true); }} />
        <small>{t("companies.currentValue")}: {company.sales_channels.join(", ") || `（${t("common.none")}）`}</small>
      </div>
      {canEdit && (
        <div className="form-actions">
          <button type="submit" className="btn-primary" disabled={!channelsDirty || channelsSubmitting}>
            {channelsSubmitting ? t("common.saving") : t("companies.saveChannels")}
          </button>
        </div>
      )}
    </form>
  );
}
