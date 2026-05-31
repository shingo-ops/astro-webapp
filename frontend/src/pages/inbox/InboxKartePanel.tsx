import { useTranslation } from "react-i18next";
import { NAV_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import { getInitials } from "./inbox.types";
import type { LeadDetail, KarteTabKey } from "./inbox.types";

interface CardForm {
  nickname?: string | null;
  customer_name?: string | null;
  email?: string | null;
  phone?: string | null;
  company_name?: string | null;
  status?: string | null;
  temperature?: string | null;
  next_action_date?: string | null;
  next_action?: string | null;
  estimated_scale?: string | null;
  monthly_forecast?: string | number | null;
  per_order_amount?: string | number | null;
  monthly_frequency?: string | number | null;
  customer_type?: string | null;
  response_speed?: string | null;
  country?: string | null;
  target_titles?: string | null;
  challenge?: string | null;
  sales_form?: string | null;
  competitor_check?: boolean | null;
  notes?: string | null;
  meeting_memo?: string | null;
  cs_memo?: string | null;
  messenger_link?: string | null;
  discord_id?: string | null;
}

interface ConversationSummary {
  lead_id: number;
  profile_picture_url?: string | null;
}

interface Props {
  selectedLeadId: number | null;
  leadDetail: LeadDetail | null;
  cardForm: CardForm;
  cardSaveStatus: "idle" | "saving" | "saved" | "error";
  cardSaveError: string | null;
  karteTab: KarteTabKey;
  setKarteTab: (tab: KarteTabKey) => void;
  showKartePanel: boolean;
  closeKartePanel: () => void;
  setShowProfileModal: (v: boolean) => void;
  inboxSettings: { showRightPanel: boolean };
  selectedConversation: ConversationSummary | null;
  avatarErrors: Set<number>;
  handleAvatarError: (id: number) => void;
  handleCardFieldChange: (field: keyof LeadDetail, value: unknown) => void;
  handleCardFieldBlur: () => void;
}

export function InboxKartePanel({
  selectedLeadId, leadDetail, cardForm, cardSaveStatus, cardSaveError,
  karteTab, setKarteTab, showKartePanel, closeKartePanel, setShowProfileModal,
  inboxSettings, selectedConversation, avatarErrors, handleAvatarError,
  handleCardFieldChange, handleCardFieldBlur,
}: Props) {
  const { t } = useTranslation();

  return (
    <aside
      className={`inbox-right-panel${showKartePanel ? " karte-open" : ""}`}
      style={{ display: inboxSettings.showRightPanel ? undefined : "none" }}
    >
      {selectedLeadId === null ? (
        <div className="right-panel-empty">
          <p>{t("inbox.selectConversation")}</p>
        </div>
      ) : leadDetail ? (
        <div className="right-panel-card">
          {/* モバイル専用: 閉じるボタン行 */}
          <div className="karte-close-row">
            <span className="karte-close-title">{t("inbox.karteToggle")}</span>
            <button type="button" className="karte-close-btn" onClick={closeKartePanel}
              aria-label={t("common.close")} data-tooltip={t("common.close")}>
              <NAV_ICONS.close size={ICON.md} weight="fill" aria-hidden="true" />
            </button>
          </div>

          {/* ヘッダー */}
          <div className="right-panel-header">
            <div className="right-panel-avatar">
              {selectedConversation?.profile_picture_url && !avatarErrors.has(selectedConversation.lead_id) ? (
                <img
                  src={selectedConversation.profile_picture_url}
                  alt={t("inbox.avatarAlt")}
                  style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }}
                  onError={() => handleAvatarError(selectedConversation.lead_id)}
                />
              ) : (
                getInitials(cardForm.nickname || cardForm.customer_name || leadDetail.nickname || leadDetail.customer_name)
              )}
            </div>
            <div className="right-panel-header-info">
              <span className="right-panel-display-name">
                {cardForm.nickname || leadDetail.nickname || cardForm.customer_name || leadDetail.customer_name}
              </span>
              <button type="button" className="right-panel-link" onClick={() => setShowProfileModal(true)}>
                {t("inbox.viewProfile")} →
              </button>
            </div>
          </div>

          {/* 保存ステータス */}
          <div className="right-panel-save-indicator">
            {cardSaveStatus === "saving" && <span>{t("common.saving")}</span>}
            {cardSaveStatus === "saved" && <span className="saved">{t("common.saved")}</span>}
            {cardSaveStatus === "error" && <span className="error">{cardSaveError}</span>}
          </div>

          {/* タブバー */}
          <div className="right-panel-tabs">
            {(["deal", "contact", "company"] as KarteTabKey[]).map((tab) => (
              <button key={tab} type="button"
                className={`right-panel-tab${karteTab === tab ? " active" : ""}`}
                onClick={() => setKarteTab(tab)}>
                {t(`inbox.karte${tab.charAt(0).toUpperCase()}${tab.slice(1)}`)}
              </button>
            ))}
          </div>

          <div className="right-panel-tab-content">
            <KarteTabContent
              tab={karteTab}
              leadDetail={leadDetail}
              cardForm={cardForm}
              handleCardFieldChange={handleCardFieldChange}
              handleCardFieldBlur={handleCardFieldBlur}
            />
          </div>
        </div>
      ) : (
        <div className="right-panel-empty">
          <p>{t("inbox.loadingProfile")}</p>
        </div>
      )}
    </aside>
  );
}

// ---------------------------------------------------------------------------
// タブコンテンツ（contact / company / deal）
// ---------------------------------------------------------------------------

function KarteTabContent({
  tab, leadDetail, cardForm, handleCardFieldChange, handleCardFieldBlur,
}: {
  tab: KarteTabKey;
  leadDetail: LeadDetail;
  cardForm: CardForm;
  handleCardFieldChange: (field: keyof LeadDetail, value: unknown) => void;
  handleCardFieldBlur: () => void;
}) {
  const { t } = useTranslation();

  if (tab === "contact") {
    return (
      <div className="right-panel-section">
        <div className="right-panel-row">
          <span className="right-panel-label">{t("leads.email")}</span>
          <input className="right-panel-field" type="email"
            value={cardForm.email ?? ""}
            onChange={(e) => handleCardFieldChange("email", e.target.value)}
            onBlur={handleCardFieldBlur} />
        </div>
        <div className="right-panel-row">
          <span className="right-panel-label">{t("leads.phone")}</span>
          <input className="right-panel-field" type="tel"
            value={cardForm.phone ?? ""}
            onChange={(e) => handleCardFieldChange("phone", e.target.value)}
            onBlur={handleCardFieldBlur} />
        </div>
        <div className="right-panel-row">
          <span className="right-panel-label">{t("leads.messengerLink")}</span>
          <input className="right-panel-field" type="url"
            value={cardForm.messenger_link ?? ""}
            onChange={(e) => handleCardFieldChange("messenger_link", e.target.value)}
            onBlur={handleCardFieldBlur} placeholder="https://m.me/..." />
        </div>
        <div className="right-panel-row">
          <span className="right-panel-label">{t("leads.discordId")}</span>
          <input className="right-panel-field" type="text"
            value={cardForm.discord_id ?? ""}
            onChange={(e) => handleCardFieldChange("discord_id", e.target.value)}
            onBlur={handleCardFieldBlur} placeholder="username#0000" />
        </div>
      </div>
    );
  }

  if (tab === "company") {
    return (
      <div className="right-panel-section">
        <div className="right-panel-row">
          <span className="right-panel-label">{t("leads.companyName")}</span>
          <input className="right-panel-field" type="text"
            value={cardForm.company_name ?? ""}
            onChange={(e) => handleCardFieldChange("company_name", e.target.value)}
            onBlur={handleCardFieldBlur} />
        </div>
      </div>
    );
  }

  // deal tab
  return (
    <div className="right-panel-section">
      <div className="right-panel-group-heading">{t("inbox.sectionNextAction")}</div>
      <div className="right-panel-memo-label">{t("leads.nextAction")}</div>
      <textarea className="right-panel-field" rows={3} value={cardForm.next_action ?? ""}
        onChange={(e) => handleCardFieldChange("next_action", e.target.value)}
        onBlur={handleCardFieldBlur} placeholder={t("leads.nextAction")} />
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.nextActionDate")}</span>
        <input className="right-panel-field" type="date" value={cardForm.next_action_date ?? ""}
          onChange={(e) => handleCardFieldChange("next_action_date", e.target.value || null)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.responseSpeed")}</span>
        <select className="right-panel-field" value={cardForm.response_speed ?? ""}
          onChange={(e) => handleCardFieldChange("response_speed", e.target.value || null)} onBlur={handleCardFieldBlur}>
          <option value="">—</option>
          <option value="24h以内">{t("leads.responseSpeed_24h")}</option>
          <option value="3日以内">{t("leads.responseSpeed_3days")}</option>
          <option value="3日超">{t("leads.responseSpeed_over3days")}</option>
        </select>
      </div>
      <div className="right-panel-memo-label">{t("leads.challenge")}</div>
      <textarea className="right-panel-field" rows={3} value={cardForm.challenge ?? ""}
        onChange={(e) => handleCardFieldChange("challenge", e.target.value)}
        onBlur={handleCardFieldBlur} placeholder={t("leads.challenge")} />
      <div className="right-panel-group-heading">{t("inbox.sectionCustomer")}</div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.nickname")}</span>
        <input className="right-panel-field" type="text" value={cardForm.nickname ?? ""}
          onChange={(e) => handleCardFieldChange("nickname", e.target.value)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.country")}</span>
        <input className="right-panel-field" type="text" value={cardForm.country ?? ""}
          onChange={(e) => handleCardFieldChange("country", e.target.value)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.targetTitles")}</span>
        <input className="right-panel-field" type="text" value={cardForm.target_titles ?? ""}
          onChange={(e) => handleCardFieldChange("target_titles", e.target.value)}
          onBlur={handleCardFieldBlur} placeholder="Pokemon, One Piece, ..." />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.salesForm")}</span>
        <input className="right-panel-field" type="text" value={cardForm.sales_form ?? ""}
          onChange={(e) => handleCardFieldChange("sales_form", e.target.value)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.customerType")}</span>
        <select className="right-panel-field" value={cardForm.customer_type ?? ""}
          onChange={(e) => handleCardFieldChange("customer_type", e.target.value || null)} onBlur={handleCardFieldBlur}>
          <option value="">—</option>
          <option value="信頼重視">{t("leads.customerType_trust")}</option>
          <option value="価格重視">{t("leads.customerType_price")}</option>
        </select>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.temperature")}</span>
        <select className="right-panel-field" value={cardForm.temperature ?? ""}
          onChange={(e) => handleCardFieldChange("temperature", e.target.value || null)} onBlur={handleCardFieldBlur}>
          <option value="">—</option>
          <option value="Hot">Hot</option>
          <option value="Warm">Warm</option>
          <option value="Cold">Cold</option>
        </select>
      </div>
      <div className="right-panel-group-heading">{t("inbox.sectionScale")}</div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.estimatedScale")}</span>
        <select className="right-panel-field" value={cardForm.estimated_scale ?? ""}
          onChange={(e) => handleCardFieldChange("estimated_scale", e.target.value || null)} onBlur={handleCardFieldBlur}>
          <option value="">—</option>
          <option value="Small">Small</option>
          <option value="Medium">Medium</option>
          <option value="Large">Large</option>
        </select>
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.monthlyForecast")}</span>
        <input className="right-panel-field" type="number" min="0" value={cardForm.monthly_forecast ?? ""}
          onChange={(e) => handleCardFieldChange("monthly_forecast", e.target.value || null)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.perOrderAmount")}</span>
        <input className="right-panel-field" type="number" min="0" value={cardForm.per_order_amount ?? ""}
          onChange={(e) => handleCardFieldChange("per_order_amount", e.target.value || null)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.monthlyFrequency")}</span>
        <input className="right-panel-field" type="number" min="0" value={cardForm.monthly_frequency ?? ""}
          onChange={(e) => handleCardFieldChange("monthly_frequency", e.target.value || null)} onBlur={handleCardFieldBlur} />
      </div>
      <div className="right-panel-row">
        <span className="right-panel-label">{t("leads.competitorCheck")}</span>
        <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
          <input type="checkbox" checked={cardForm.competitor_check ?? false}
            onChange={(e) => {
              handleCardFieldChange("competitor_check", e.target.checked);
              setTimeout(handleCardFieldBlur, 0);
            }} />
          <span className="right-panel-value">
            {cardForm.competitor_check ? t("leads.competitorDone") : t("leads.competitorNotDone")}
          </span>
        </label>
      </div>
      <div className="right-panel-group-heading">{t("inbox.sectionMemo")}</div>
      <div className="right-panel-memo-label">{t("leads.meetingMemo")}</div>
      <textarea className="right-panel-field" rows={3} value={cardForm.meeting_memo ?? ""}
        onChange={(e) => handleCardFieldChange("meeting_memo", e.target.value)}
        onBlur={handleCardFieldBlur} placeholder={t("leads.meetingMemo")} />
      <div className="right-panel-memo-label">{t("leads.csMemo")}</div>
      <textarea className="right-panel-field" rows={3} value={cardForm.cs_memo ?? ""}
        onChange={(e) => handleCardFieldChange("cs_memo", e.target.value)}
        onBlur={handleCardFieldBlur} placeholder={t("leads.csMemo")} />
    </div>
  );
}
