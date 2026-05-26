import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { INBOX_ACTION_ICONS, NAV_ICONS, PAGE_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { Conversation, MessagesResponse } from "../../lib/messages";
import { formatAbsolute, getInitials, relativeTime } from "./inbox.types";

interface Props {
  selectedLeadId: number | null;
  selectedConversation: Conversation | null;
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
  trimmedDraft: string;
  submitSend: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
}

export function InboxMessageThread({
  selectedLeadId, selectedConversation, messagesData, msgLoading, msgError,
  avatarErrors, handleAvatarError,
  handleMarkUnread, handleExclude, handleDeleteLead,
  showKartePanel, openKartePanel, closeKartePanel, inboxSettings,
  messageListRef,
  draft, setDraft, sending, sendError, sendDisabled, canSend, trimmedDraft,
  submitSend, handleKeyDown,
}: Props) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

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
        </h3>
        <div className="inbox-header-actions">
          <button type="button" className="inbox-header-action-btn"
            onClick={handleMarkUnread}
            aria-label={t("inbox.markUnread")} data-tooltip={t("inbox.markUnread")}>
            <INBOX_ACTION_ICONS.markUnread size={ICON.base} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-header-action-btn"
            onClick={handleExclude}
            aria-label={t("inbox.exclude")} data-tooltip={t("inbox.exclude")}>
            <INBOX_ACTION_ICONS.exclude size={ICON.base} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-header-action-btn danger"
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
                <div className={`msg-time${outbound ? "" : " inbound"}`}>
                  {relativeTime(msg.created_at)}
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
                placeholder={canSend ? t("inbox.messagePlaceholder") : t("inbox.sendDisabled7d")}
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
                !canSend
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
