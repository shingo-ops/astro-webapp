import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { INBOX_ACTION_ICONS, NAV_ICONS, PAGE_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { Conversation, MessagesResponse } from "../../lib/messages";
import { translateMessage } from "../../lib/messages";
import { formatAbsolute, getInitials, relativeTime } from "./inbox.types";
import type { LeadDetail } from "./inbox.types";

interface Props {
  selectedLeadId: number | null;
  selectedConversation: Conversation | null;
  leadDetail: LeadDetail | null;
  messagesData: MessagesResponse | null;
  msgLoading: boolean;
  msgError: string | null;
  avatarErrors: Set<number>;
  handleAvatarError: (id: number) => void;
  handleMarkUnread: () => void;
  handleExclude: () => void;
  handleDeleteLead: () => void;
  showKartePanel: boolean;
  openKartePanel: () => void;
  closeKartePanel: () => void;
  inboxSettings: { showRightPanel: boolean };
  messageListRef: React.RefObject<HTMLDivElement>;
  draft: string;
  setDraft: (v: string) => void;
  sending: boolean;
  sendError: string | null;
  sendDisabled: boolean;
  canSend: boolean;
  discordDmChannelMissing: boolean;
  trimmedDraft: string;
  submitSend: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
}

/** Per-message translation state. */
interface TranslationState {
  text: string | null;
  loading: boolean;
  error: string | null;
}

export function InboxMessageThread({
  selectedLeadId, selectedConversation, leadDetail, messagesData, msgLoading, msgError,
  avatarErrors, handleAvatarError,
  handleMarkUnread, handleExclude, handleDeleteLead,
  showKartePanel, openKartePanel, closeKartePanel, inboxSettings,
  messageListRef,
  draft, setDraft, sending, sendError, sendDisabled, canSend, discordDmChannelMissing,
  trimmedDraft, submitSend, handleKeyDown,
}: Props) {
  const { t, i18n } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Translation state: keyed by message_id
  const [translations, setTranslations] = useState<Record<string, TranslationState>>({});

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  // Reset translations when conversation changes
  useEffect(() => {
    setTranslations({});
  }, [selectedLeadId]);

  const handleTranslate = useCallback(async (messageId: string | null) => {
    if (!messageId || !selectedLeadId) return;

    // If already translated, toggle off
    if (translations[messageId]?.text) {
      setTranslations((prev) => {
        const updated = { ...prev };
        delete updated[messageId];
        return updated;
      });
      return;
    }

    // 翻訳先は常に UI 言語（ADR-088: オペレーターが読める言語に揃える）
    const targetLanguage = i18n.language ?? "ja";

    setTranslations((prev) => ({
      ...prev,
      [messageId]: { text: null, loading: true, error: null },
    }));

    try {
      const result = await translateMessage(selectedLeadId, messageId, targetLanguage);
      setTranslations((prev) => ({
        ...prev,
        [messageId]: { text: result.translated_text, loading: false, error: null },
      }));
    } catch (err: unknown) {
      let errorMsg = t("inbox.translationError");
      if (err && typeof err === "object" && "status" in err) {
        const status = (err as { status: number }).status;
        if (status === 429) {
          errorMsg = t("inbox.translationBudgetExceeded");
        }
      }
      setTranslations((prev) => ({
        ...prev,
        [messageId]: { text: null, loading: false, error: errorMsg },
      }));
    }
  }, [selectedLeadId, translations, i18n.language, t]);

  if (selectedLeadId === null) {
    return (
      <main className="inbox-center">
        <div className="empty-state">
          <div className="empty-state-icon" aria-hidden="true">
            <PAGE_ICONS.inboxEmpty size={ICON.xl} weight="fill" />
          </div>
          <p>{t("inbox.selectConversation")}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="inbox-center">
      {/* ヘッダ */}
      <header className="inbox-center-header">
        <div className="conv-avatar" style={{ flexShrink: 0 }}>
          {selectedConversation?.profile_picture_url && !avatarErrors.has(selectedConversation.lead_id) ? (
            <img
              src={selectedConversation.profile_picture_url}
              alt={t("inbox.avatarAlt")}
              style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }}
              onError={() => handleAvatarError(selectedConversation.lead_id)}
            />
          ) : (
            getInitials(
              messagesData?.lead?.customer_name
              || selectedConversation?.customer_name
            )
          )}
        </div>
        <h3 className="inbox-center-title" style={{ flex: 1, minWidth: 0 }}>
          {messagesData?.lead?.customer_name
            || selectedConversation?.customer_name
            || `Lead #${selectedLeadId}`}
          {/* AC1.6: Discord 未連携バッジ */}
          {messagesData?.lead?.platform === "discord" && !leadDetail?.discord_user_id && (
            <span className="discord-unlinked-badge" title={t("inbox.discordNotLinked")}>
              {t("inbox.discordNotLinked")}
            </span>
          )}
        </h3>
        <div className="inbox-thread-actions">
          <button type="button" className="inbox-thread-action-btn"
            onClick={handleMarkUnread}
            aria-label={t("inbox.markUnread")} data-tooltip={t("inbox.markUnread")}>
            <INBOX_ACTION_ICONS.markUnread size={ICON.base} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-thread-action-btn"
            onClick={handleExclude}
            aria-label={t("inbox.exclude")} data-tooltip={t("inbox.exclude")}>
            <INBOX_ACTION_ICONS.exclude size={ICON.base} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-thread-action-btn danger"
            onClick={handleDeleteLead}
            aria-label={t("inbox.deleteLead")} data-tooltip={t("inbox.deleteLead")}>
            <INBOX_ACTION_ICONS.delete size={ICON.base} weight="fill" aria-hidden="true" />
          </button>
        </div>
        {inboxSettings.showRightPanel && (
          <button type="button" className="karte-toggle-btn"
            onClick={() => showKartePanel ? closeKartePanel() : openKartePanel()}
            aria-label={t("inbox.karteToggle")}>
            <PAGE_ICONS.kartePanel size={ICON.base} weight="fill" aria-hidden="true" />
            {t("inbox.karteToggle")}
          </button>
        )}
        <div ref={menuRef} className="inbox-header-menu-wrap">
          <button
            type="button"
            className="inbox-header-menu-btn"
            onClick={() => setMenuOpen(v => !v)}
            aria-label={t("inbox.moreActions")}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
          >
            <NAV_ICONS.more size={ICON.base} weight="bold" aria-hidden="true" />
          </button>
          {menuOpen && (
            <div role="menu" className="inbox-header-menu">
              <button role="menuitem" className="inbox-header-menu-item"
                onClick={() => { handleMarkUnread(); setMenuOpen(false); }}>
                <INBOX_ACTION_ICONS.markUnread size={ICON.base} weight="fill" aria-hidden="true" />
                {t("inbox.markUnread")}
              </button>
              <button role="menuitem" className="inbox-header-menu-item"
                onClick={() => { handleExclude(); setMenuOpen(false); }}>
                <INBOX_ACTION_ICONS.exclude size={ICON.base} weight="fill" aria-hidden="true" />
                {t("inbox.exclude")}
              </button>
              <button role="menuitem" className="inbox-header-menu-item danger"
                onClick={() => { handleDeleteLead(); setMenuOpen(false); }}>
                <INBOX_ACTION_ICONS.delete size={ICON.base} weight="fill" aria-hidden="true" />
                {t("inbox.deleteLead")}
              </button>
              {inboxSettings.showRightPanel && (
                <button role="menuitem" className="inbox-header-menu-item"
                  onClick={() => { showKartePanel ? closeKartePanel() : openKartePanel(); setMenuOpen(false); }}>
                  <PAGE_ICONS.kartePanel size={ICON.base} weight="fill" aria-hidden="true" />
                  {t("inbox.karteToggle")}
                </button>
              )}
            </div>
          )}
        </div>
      </header>

      {/* メッセージリスト */}
      <div ref={messageListRef} className="inbox-messages">
        {msgLoading && !messagesData && (
          <div style={{ textAlign: "center", color: "var(--text-secondary)", padding: "var(--space-4)" }}>
            {t("common.loading")}
          </div>
        )}
        {msgError && (
          <div className="error-banner">{msgError}</div>
        )}
        {messagesData && messagesData.messages.length === 0 && !msgError && (
          <div style={{ textAlign: "center", color: "var(--text-secondary)", padding: "var(--space-8)" }}>
            {t("inbox.noMessages")}
          </div>
        )}
        {messagesData?.messages.map((msg) => {
          const outbound = msg.direction === "outbound";
          const failed = !!msg.error_code;
          const translationState = msg.message_id ? translations[msg.message_id] : undefined;
          return (
            <div key={msg.id} className={`inbox-msg-row${outbound ? " outbound" : " inbound"}`}>
              <div
                role={failed ? "alert" : undefined}
                className={`msg-bubble${failed ? " failed" : outbound ? " outbound" : " inbound"}`}
                title={
                  failed
                    ? `Send failed: ${msg.error_code}${msg.error_message ? ` — ${msg.error_message}` : ""}`
                    : formatAbsolute(msg.created_at)
                }
              >
                {msg.message_tag && !failed && (
                  <div style={{ fontSize: "var(--font-2xs)", opacity: "var(--opacity-secondary)", marginBottom: "var(--space-1)", fontWeight: "var(--font-weight-semi)" }}>
                    {msg.message_tag === "HUMAN_AGENT" ? "Human Agent" : msg.message_tag}
                  </div>
                )}
                {failed && (
                  <div style={{ fontSize: "var(--font-2xs)", fontWeight: "var(--font-weight-semi)", marginBottom: "var(--space-1)" }}>
                    Send failed ({msg.error_code})
                  </div>
                )}
                <div>{msg.message_text || "(no body)"}</div>

                {/* Translation section */}
                {translationState?.loading && (
                  <div className="msg-translation msg-translation--loading">
                    {t("inbox.translating")}
                  </div>
                )}
                {translationState?.error && (
                  <div className="msg-translation msg-translation--error">
                    {translationState.error}
                  </div>
                )}
                {translationState?.text && (
                  <div className="msg-translation">
                    <span className="msg-translation-text">{translationState.text}</span>
                    <span className="msg-translation-badge">{t("inbox.translatedBy")}</span>
                  </div>
                )}

                <div className={`msg-time${outbound ? "" : " inbound"}`}>
                  {relativeTime(msg.created_at)}
                  {/* Translate button */}
                  {msg.message_id && msg.message_text && !failed && (
                    <button
                      type="button"
                      className="msg-translate-btn"
                      onClick={() => handleTranslate(msg.message_id)}
                      aria-label={translationState?.text ? t("inbox.showOriginal") : t("inbox.translate")}
                      title={translationState?.text ? t("inbox.showOriginal") : t("inbox.translate")}
                      disabled={translationState?.loading}
                    >
                      <INBOX_ACTION_ICONS.translate size={14} weight="fill" aria-hidden="true" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 送信エリア */}
      <div className="inbox-send-area">
        {sendError && (
          <div className="inbox-send-error" role="alert">
            Send error: {sendError}
          </div>
        )}
        <div className="send-card">
          <div className="send-top-row">
            <div className="conv-avatar" style={{ width: 'var(--size-thread-avatar)', height: 'var(--size-thread-avatar)', fontSize: "var(--font-xs)", flexShrink: 0 }}>
              Me
            </div>
            <div className="send-input-wrap">
              <textarea
                className="inbox-textarea"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  discordDmChannelMissing
                    ? t("inbox.discordDmChannelMissing")
                    : canSend
                      ? t("inbox.messagePlaceholder")
                      : t("inbox.sendDisabled7d")
                }
                rows={2}
                disabled={!canSend || sending}
              />
            </div>
          </div>
          <div className="send-bottom-row">
            <button
              type="button"
              className="inbox-send-btn"
              onClick={submitSend}
              disabled={sendDisabled}
              title={
                discordDmChannelMissing
                  ? t("inbox.discordDmChannelMissing")
                  : !canSend
                    ? t("inbox.sendDisabled7d")
                    : trimmedDraft.length === 0
                      ? t("inbox.messagePlaceholder")
                      : t("inbox.send")
              }
            >
              {sending ? t("inbox.sending") : t("inbox.send")}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
