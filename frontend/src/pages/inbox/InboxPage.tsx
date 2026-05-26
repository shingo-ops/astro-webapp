/**
 * Inbox ページ（Phase 1-D Sprint 4 / Sprint 5 / Sprint 6 / Sprint 7 redesign）。
 *
 * Meta Business Suite 風の 3 カラムレイアウト。
 *
 * 変更履歴:
 *   2026-04-30: Sprint 4 初版（送信ボタン disabled）
 *   2026-04-30: Sprint 5 — lib/messages.ts ヘルパ経由に切替 + 送信機能 enable
 *   2026-05-21: Sprint 6 — Meta Business Suite 風 UI に全面再設計
 *       - 3 カラムレイアウト（左: 会話リスト, 中央: メッセージ, 右: 顧客カルテ）
 *       - All / Leads / Converted / Customers タブ（lead_status ベース）
 *       - プラットフォームフィルタをピル型に変更
 *       - イニシャルアバター + プラットフォームドット
 *       - バブルデザイン: outbound 紫(#7C3AED) / inbound グレー(#E4E6EB)
 *       - 右パネル: GET /leads/{id} で顧客詳細を表示
 *   2026-05-21: Sprint 7 — Meta インボックス忠実再現
 *       - タブを左パネル最上部に移動（検索の上）
 *       - 検索 + 管理ボタンを横並びに配置
 *       - 管理ドロップダウン（全て既読にする）
 *       - パネルタイトルを視覚的に非表示化（スクリーンリーダー用に保持）
 */

import "./InboxPage.css";
import { useNavigate } from "react-router-dom";
import { INBOX_ACTION_ICONS, NAV_ICONS, PAGE_ICONS, PlatformIcon } from "../../constants/icons";
import { PageLayout } from "../../components/PageLayout";
import { ICON } from "../../constants/iconSizes";
import { PlatformFilter } from "../../lib/messages";
import { STATUS_TABS, formatAbsolute, getInitials, relativeTime } from "./inbox.types";
import type { LeadDetail, StatusTabKey } from "./inbox.types";
import { useInboxState } from "./useInboxState";

// ---------------------------------------------------------------------------
// メイン
// ---------------------------------------------------------------------------

export default function InboxPage() {
  const {
    t,
    // 会話リスト
    convLoading, convError, filteredConversations, loadConversations,
    // 受信箱設定
    inboxSettings, showSettings, setShowSettings, updateInboxSetting,
    // フィルタ
    statusTab, setStatusTab, platformFilter, setPlatformFilter, unreadOnly, setUnreadOnly,
    followUpOnly, setFollowUpOnly, searchQuery, setSearchQuery, pageIdFilter, availablePageIds, onPageFilterChange,
    // 選択中会話
    selectedLeadId, selectedConversation, messagesData, msgLoading, msgError,
    avatarErrors, handleAvatarError, selectLead,
    // 顧客カルテ
    leadDetail, cardForm, cardSaveStatus, cardSaveError, karteTab, setKarteTab,
    showKartePanel, openKartePanel, closeKartePanel, showProfileModal, setShowProfileModal,
    profileModalTab, setProfileModalTab, profileModalRef, handleCardFieldChange, handleCardFieldBlur,
    // 送信エリア
    draft, setDraft, sending, sendError, sendDisabled, canSend, trimmedDraft,
    submitSend, handleKeyDown,
    // 管理ドロップダウン
    manageOpen, setManageOpen, manageRef, handleMarkAllRead, handleMarkUnread, handleExclude, handleDeleteLead,
    // 一括選択
    selectMode, selectedLeadIds, isAllSelected,
    toggleSelectMode, toggleSelectConv, toggleSelectAll,
    handleBulkMarkRead, handleBulkMarkUnread, handleBulkExclude, handleBulkDelete,
    // スクロール ref
    messageListRef,
  } = useInboxState();

  const navigate = useNavigate();

  const headerActions = (
    <div className="inbox-header-btns">
      <button
        type="button"
        className="inbox-faq-btn icon-frame"
        onClick={() => navigate("/faq")}
        aria-label={t("faq.title")}
        data-tooltip={t("faq.title")}
      >
        FAQ
      </button>
      <button
        type="button"
        className="inbox-settings-btn icon-frame"
        onClick={() => setShowSettings(true)}
        aria-label={t("inbox.settings.title")}
        data-tooltip={t("inbox.settings.tooltip")}
      >
        <NAV_ICONS.settings size={ICON.base} weight="fill" aria-hidden="true" />
      </button>
    </div>
  );

  return (
    <>
      <PageLayout navKey="nav.leadChat" subtitleKey="inbox.subtitle" noScroll headerAction={headerActions}>
      <div className="inbox-wrapper">
        {/* 左+中央エリア（タブ+カラム） */}
        <div className="inbox-main-area">

        {/* ステータスタブバー（商談進捗ベース） */}
        <div className="inbox-full-tab-bar">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`inbox-full-tab${statusTab === tab.key ? " active" : ""}`}
              onClick={() => setStatusTab(tab.key)}
            >
              {t(tab.labelKey)}
            </button>
          ))}
          <select
            className="inbox-platform-select"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value as PlatformFilter)}
            aria-label={t("inbox.platformFilter")}
          >
            <option value="all">{t("inbox.platformAll")}</option>
            <option value="messenger">{t("inbox.platformMessenger")}</option>
            <option value="instagram">{t("inbox.platformInstagram")}</option>
          </select>
        </div>

        {/* 3カラムコンテンツ */}
        <div className="inbox-columns">

        {/* ============================== 左パネル ============================== */}
        <aside className="inbox-left-panel">
          {/* 検索 + 管理ボタン + ユーティリティ（topbar移設分） */}
          <div className="inbox-search-row">
            <div className="inbox-search-wrap">
              <NAV_ICONS.search size={14} className="inbox-search-icon" aria-hidden="true" />
              <input
                type="text"
                className="search-input-field inbox-search-input"
                placeholder={t("common.search")}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <div className="inbox-manage-wrap" ref={manageRef}>
              <button
                type="button"
                className={`inbox-manage-btn${selectMode ? " active" : ""}`}
                onClick={toggleSelectMode}
                aria-pressed={selectMode}
              >
                <NAV_ICONS.filter size={13} />
                {t("inbox.manage")}
              </button>
              {!selectMode && manageOpen && (
                <div className="dropdown-menu" role="menu">
                  <button
                    type="button"
                    className="dropdown-item"
                    role="menuitem"
                    onClick={handleMarkAllRead}
                  >
                    {t("inbox.markAllRead")}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 一括アクションバー（選択モード時） */}
          {selectMode && (
            <div className="inbox-bulk-bar">
              <input
                type="checkbox"
                className="inbox-bulk-check-all"
                checked={isAllSelected}
                onChange={toggleSelectAll}
                aria-label={t("inbox.selectAll")}
              />
              <span className="inbox-bulk-count">
                {t("inbox.selectedCount", { count: selectedLeadIds.size })}
              </span>
              <button
                type="button"
                className="inbox-bulk-action"
                onClick={handleBulkMarkRead}
                disabled={selectedLeadIds.size === 0}
                title={t("inbox.markAllRead")}
                aria-label={t("inbox.markAllRead")}
              >
                <INBOX_ACTION_ICONS.markRead size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="inbox-bulk-action"
                onClick={handleBulkMarkUnread}
                disabled={selectedLeadIds.size === 0}
                title={t("inbox.markUnread")}
                aria-label={t("inbox.markUnread")}
              >
                <INBOX_ACTION_ICONS.markUnread size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="inbox-bulk-action"
                onClick={handleBulkExclude}
                disabled={selectedLeadIds.size === 0}
                title={t("inbox.exclude")}
                aria-label={t("inbox.exclude")}
              >
                <INBOX_ACTION_ICONS.exclude size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="inbox-bulk-action inbox-bulk-delete"
                onClick={handleBulkDelete}
                disabled={selectedLeadIds.size === 0}
                title={t("inbox.deleteLead")}
                aria-label={t("inbox.deleteLead")}
              >
                <INBOX_ACTION_ICONS.delete size={14} aria-hidden="true" />
              </button>
            </div>
          )}

          {/* サブフィルターピル（未読 / フォローアップ / アーカイブ） */}
          <div className="inbox-sub-filter-bar">
            <button
              type="button"
              className={`inbox-sub-filter-pill${unreadOnly ? " active" : ""}`}
              onClick={() => setUnreadOnly((v) => !v)}
            >
              {t("inbox.filterUnread")}
            </button>
            <button
              type="button"
              className={`inbox-sub-filter-pill${followUpOnly ? " active" : ""}`}
              onClick={() => setFollowUpOnly((v) => !v)}
            >
              {t("inbox.filterFollowUp")}
            </button>
          </div>

          {/* Page フィルタ（複数 Page 時） */}
          {(availablePageIds.length > 1 || !!pageIdFilter) && (
            <div className="inbox-page-filter-wrap">
              <select
                value={pageIdFilter}
                onChange={(e) => onPageFilterChange(e.target.value)}
                aria-label="Filter by Page"
                className="inbox-page-filter-select"
              >
                <option value="">{t("inbox.allPages")}</option>
                {availablePageIds.map((pid) => (
                  <option key={pid} value={pid}>Page: {pid}</option>
                ))}
              </select>
            </div>
          )}

          {/* 会話リスト */}
          <div className="inbox-conversation-list">
            {convError && (
              <div className="error-banner">
                {t("inbox.fetchError")}
                <button
                  type="button"
                  style={{ marginLeft: "var(--space-2)", fontSize: "var(--font-xs)", cursor: "pointer" }}
                  onClick={() => loadConversations()}
                >
                  {t("common.reload")}
                </button>
              </div>
            )}
            {convLoading ? (
              <div style={{ padding: "var(--space-6)", textAlign: "center", color: "var(--text-secondary)", fontSize: "var(--font-base)" }}>
                {t("common.loading")}
              </div>
            ) : filteredConversations.length === 0 ? (
              <div style={{ padding: "var(--space-6)", textAlign: "center", color: "var(--text-secondary)", fontSize: "var(--font-base)" }}>
                {unreadOnly ? t("inbox.noUnread") : t("inbox.noMessages")}
                {!unreadOnly && (
                  <div style={{ marginTop: "var(--space-2)", fontSize: "var(--font-xs)" }}>
                    {t("inbox.channelsHint")}{" "}
                    <a href="/channels" style={{ color: "var(--accent)" }}>{t("inbox.channelsLink")}</a>
                  </div>
                )}
              </div>
            ) : (
              filteredConversations.map((conv) => {
                const isSelected = conv.lead_id === selectedLeadId;
                const isBulkChecked = selectedLeadIds.has(conv.lead_id);
                return (
                  <button
                    key={conv.lead_id}
                    type="button"
                    role={selectMode ? "checkbox" : undefined}
                    aria-checked={selectMode ? isBulkChecked : undefined}
                    className={`conv-item conversation-item${isSelected ? " selected" : ""}${selectMode && isBulkChecked ? " bulk-selected" : ""}`}
                    onClick={() => selectMode ? toggleSelectConv(conv.lead_id) : selectLead(conv.lead_id)}
                  >
                    {/* 選択モード: チェックボックス */}
                    {selectMode && (
                      <span
                        aria-hidden="true"
                        className={`conv-select-check${isBulkChecked ? " checked" : ""}`}
                      />
                    )}
                    {/* アバター */}
                    <div className="conv-avatar-wrap">
                      <div className="conv-avatar">
                        {conv.profile_picture_url && !avatarErrors.has(conv.lead_id) ? (
                          <img
                            src={conv.profile_picture_url}
                            alt={t("inbox.avatarAlt")}
                            style={{ width: "100%", height: "100%", borderRadius: "50%", objectFit: "cover" }}
                            onError={() => handleAvatarError(conv.lead_id)}
                          />
                        ) : (
                          getInitials(conv.customer_name)
                        )}
                      </div>
                      <span className="conv-platform-dot icon-frame">
                        <PlatformIcon platform={conv.platform} size={ICON.base} />
                      </span>
                    </div>

                    {/* 会話情報 */}
                    <div className="conv-info">
                      <div className="conv-header">
                        <span className={`conv-name${(conv.unread_count ?? 0) > 0 ? " unread" : ""}`}>
                          {conv.customer_name ?? `Lead #${conv.lead_id}`}
                        </span>
                        {conv.lead_status && (
                          <span className="conv-status-badge">{conv.lead_status}</span>
                        )}
                        <span className="conv-time">{relativeTime(conv.last_message_at)}</span>
                      </div>
                      <div className="conv-preview">
                        <span className={`conv-preview-text${conv.unread_count > 0 ? " unread" : ""}`}>
                          {conv.last_message_direction === "outbound" && (
                            <span style={{ opacity: "var(--opacity-muted)" }}>You: </span>
                          )}
                          {conv.last_message_text ?? ""}
                        </span>
                        {conv.unread_count > 0 && (
                          <span className="badge conv-unread-badge">{conv.unread_count}</span>
                        )}
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* ============================== 中央パネル ============================== */}
        <main className="inbox-center">
          {selectedLeadId === null ? (
            <div className="empty-state">
              <div className="empty-state-icon" aria-hidden="true">
                <PAGE_ICONS.inboxEmpty size={ICON.xl} />
              </div>
              <p>{t("inbox.selectConversation")}</p>
            </div>
          ) : (
            <>
              {/* ヘッダ */}
              <header className="inbox-center-header">
                {/* ヘッダーアバター 48×48px 円形 */}
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
                {/* Metaスタイル: ヘッダーアクションアイコン群（未読・対象外・削除） */}
                <div className="inbox-header-actions">
                  <button
                    type="button"
                    className="inbox-header-action-btn"
                    onClick={handleMarkUnread}
                    aria-label={t("inbox.markUnread")}
                    data-tooltip={t("inbox.markUnread")}
                  >
                    <INBOX_ACTION_ICONS.markUnread size={ICON.base} weight="fill" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="inbox-header-action-btn"
                    onClick={handleExclude}
                    aria-label={t("inbox.exclude")}
                    data-tooltip={t("inbox.exclude")}
                  >
                    <INBOX_ACTION_ICONS.exclude size={ICON.base} weight="fill" aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="inbox-header-action-btn danger"
                    onClick={handleDeleteLead}
                    aria-label={t("inbox.deleteLead")}
                    data-tooltip={t("inbox.deleteLead")}
                  >
                    <INBOX_ACTION_ICONS.delete size={ICON.base} weight="fill" aria-hidden="true" />
                  </button>
                </div>
                {/* モバイル専用カルテトグルボタン（デスクトップでは CSS で非表示） */}
                {inboxSettings.showRightPanel && (
                  <button
                    type="button"
                    className="karte-toggle-btn"
                    onClick={() => showKartePanel ? closeKartePanel() : openKartePanel()}
                    aria-label={t("inbox.karteToggle")}
                  >
                    <PAGE_ICONS.kartePanel size={ICON.base} aria-hidden="true" />
                    {t("inbox.karteToggle")}
                  </button>
                )}
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
                    <div
                      key={msg.id}
                      className={`inbox-msg-row${outbound ? " outbound" : " inbound"}`}
                    >
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

              {/* 送信エリア — Meta実測: 白角丸カード + アバター左配置 */}
              <div className="inbox-send-area">
                {sendError && (
                  <div className="inbox-send-error" role="alert">
                    Send error: {sendError}
                  </div>
                )}
                <div className="send-card">
                  {/* 上段: 送信者アバター + 入力欄 */}
                  <div className="send-top-row">
                    <div className="conv-avatar" style={{ width: 36, height: 36, fontSize: "var(--font-xs)", flexShrink: 0 }}>
                      Me
                    </div>
                    <div className="send-input-wrap">
                      <textarea
                        className="inbox-textarea"
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={
                          canSend
                            ? t("inbox.messagePlaceholder")
                            : t("inbox.sendDisabled7d")
                        }
                        rows={2}
                        disabled={!canSend || sending}
                      />
                    </div>
                  </div>
                  {/* 下段: 送信ボタン */}
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
            </>
          )}
        </main>
        </div>{/* /inbox-columns */}
        </div>{/* /inbox-main-area */}

        {/* モバイルドロワーバックドロップ */}
        {showKartePanel && inboxSettings.showRightPanel && (
          <div className="karte-overlay" onClick={closeKartePanel} aria-hidden="true" />
        )}

        {/* ============================== 右パネル (商談カルテ) ============================== */}
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
              {/* モバイルドロワー専用: 閉じるボタン行（デスクトップでは CSS で非表示） */}
              <div className="karte-close-row">
                <span className="karte-close-title">{t("inbox.karteToggle")}</span>
                <button
                  type="button"
                  className="karte-close-btn"
                  onClick={closeKartePanel}
                  aria-label={t("common.close")}
                  data-tooltip={t("common.close")}
                >
                  <NAV_ICONS.close size={ICON.md} aria-hidden="true" />
                </button>
              </div>
              {/* ヘッダー（アバター左 + 表示名・リンク右） */}
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

              {/* 保存ステータスインジケーター */}
              <div className="right-panel-save-indicator">
                {cardSaveStatus === "saving" && <span>{t("common.saving")}</span>}
                {cardSaveStatus === "saved" && <span className="saved">{t("common.saved")}</span>}
                {cardSaveStatus === "error" && <span className="error">{cardSaveError}</span>}
              </div>

              {/* タブバー */}
              <div className="right-panel-tabs">
                <button
                  type="button"
                  className={`right-panel-tab${karteTab === "deal" ? " active" : ""}`}
                  onClick={() => setKarteTab("deal")}
                >{t("inbox.karteDeal")}</button>
                <button
                  type="button"
                  className={`right-panel-tab${karteTab === "contact" ? " active" : ""}`}
                  onClick={() => setKarteTab("contact")}
                >{t("inbox.karteContact")}</button>
                <button
                  type="button"
                  className={`right-panel-tab${karteTab === "company" ? " active" : ""}`}
                  onClick={() => setKarteTab("company")}
                >{t("inbox.karteCompany")}</button>
              </div>

              {/* タブコンテンツ */}
              <div className="right-panel-tab-content">

                {/* Tab 1: 連絡先 */}
                {karteTab === "contact" && (
                  <div className="right-panel-section">
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.nickname")}</span>
                      <input className="right-panel-field" type="text"
                        value={cardForm.nickname ?? ""}
                        onChange={(e) => handleCardFieldChange("nickname", e.target.value)}
                        onBlur={handleCardFieldBlur}
                        placeholder={t("leads.nickname")} />
                    </div>
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
                  </div>
                )}

                {/* Tab 2: 会社情報 */}
                {karteTab === "company" && (
                  <div className="right-panel-section">
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.companyName")}</span>
                      <input className="right-panel-field" type="text"
                        value={cardForm.company_name ?? ""}
                        onChange={(e) => handleCardFieldChange("company_name", e.target.value)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                  </div>
                )}

                {/* Tab 3: 商談情報 */}
                {karteTab === "deal" && (
                  <div className="right-panel-section">
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("inbox.platformName")}</span>
                      <span className="right-panel-value">{leadDetail.customer_name}</span>
                    </div>

                    <hr className="right-panel-divider" />

                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.status")}</span>
                      <select className="right-panel-field"
                        value={cardForm.status ?? ""}
                        onChange={(e) => handleCardFieldChange("status", e.target.value)}
                        onBlur={handleCardFieldBlur}>
                        <option value="新規">{t("leads.status_new")}</option>
                        <option value="商談中">{t("leads.status_negotiating")}</option>
                        <option value="既存顧客">{t("leads.status_existing_customer")}</option>
                        <option value="追客（短期）">{t("leads.status_follow_up_short")}</option>
                        <option value="追客（長期）">{t("leads.status_follow_up_long")}</option>
                        <option value="失注">{t("leads.status_lost")}</option>
                        <option value="対象外">{t("leads.status_out_of_scope")}</option>
                      </select>
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.temperature")}</span>
                      <select className="right-panel-field"
                        value={cardForm.temperature ?? ""}
                        onChange={(e) => handleCardFieldChange("temperature", e.target.value || null)}
                        onBlur={handleCardFieldBlur}>
                        <option value="">—</option>
                        <option value="Hot">Hot</option>
                        <option value="Warm">Warm</option>
                        <option value="Cold">Cold</option>
                      </select>
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.nextActionDate")}</span>
                      <input className="right-panel-field" type="date"
                        value={cardForm.next_action_date ?? ""}
                        onChange={(e) => handleCardFieldChange("next_action_date", e.target.value || null)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                    <textarea className="right-panel-field" rows={3}
                      value={cardForm.next_action ?? ""}
                      onChange={(e) => handleCardFieldChange("next_action", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.nextAction")} />

                    <hr className="right-panel-divider" />

                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.estimatedScale")}</span>
                      <select className="right-panel-field"
                        value={cardForm.estimated_scale ?? ""}
                        onChange={(e) => handleCardFieldChange("estimated_scale", e.target.value || null)}
                        onBlur={handleCardFieldBlur}>
                        <option value="">—</option>
                        <option value="Small">Small</option>
                        <option value="Medium">Medium</option>
                        <option value="Large">Large</option>
                      </select>
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.monthlyForecast")}</span>
                      <input className="right-panel-field" type="number" min="0"
                        value={cardForm.monthly_forecast ?? ""}
                        onChange={(e) => handleCardFieldChange("monthly_forecast", e.target.value || null)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.perOrderAmount")}</span>
                      <input className="right-panel-field" type="number" min="0"
                        value={cardForm.per_order_amount ?? ""}
                        onChange={(e) => handleCardFieldChange("per_order_amount", e.target.value || null)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.monthlyFrequency")}</span>
                      <input className="right-panel-field" type="number" min="0"
                        value={cardForm.monthly_frequency ?? ""}
                        onChange={(e) => handleCardFieldChange("monthly_frequency", e.target.value || null)}
                        onBlur={handleCardFieldBlur} />
                    </div>

                    <hr className="right-panel-divider" />

                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.customerType")}</span>
                      <select className="right-panel-field"
                        value={cardForm.customer_type ?? ""}
                        onChange={(e) => handleCardFieldChange("customer_type", e.target.value || null)}
                        onBlur={handleCardFieldBlur}>
                        <option value="">—</option>
                        <option value="信頼重視">{t("leads.customerType_trust")}</option>
                        <option value="価格重視">{t("leads.customerType_price")}</option>
                      </select>
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.responseSpeed")}</span>
                      <select className="right-panel-field"
                        value={cardForm.response_speed ?? ""}
                        onChange={(e) => handleCardFieldChange("response_speed", e.target.value || null)}
                        onBlur={handleCardFieldBlur}>
                        <option value="">—</option>
                        <option value="24h以内">{t("leads.responseSpeed_24h")}</option>
                        <option value="3日以内">{t("leads.responseSpeed_3days")}</option>
                        <option value="3日超">{t("leads.responseSpeed_over3days")}</option>
                      </select>
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.country")}</span>
                      <input className="right-panel-field" type="text"
                        value={cardForm.country ?? ""}
                        onChange={(e) => handleCardFieldChange("country", e.target.value)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.targetTitles")}</span>
                      <input className="right-panel-field" type="text"
                        value={cardForm.target_titles ?? ""}
                        onChange={(e) => handleCardFieldChange("target_titles", e.target.value)}
                        onBlur={handleCardFieldBlur}
                        placeholder="Pokemon, One Piece, ..." />
                    </div>
                    <textarea className="right-panel-field" rows={3}
                      value={cardForm.challenge ?? ""}
                      onChange={(e) => handleCardFieldChange("challenge", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.challenge")} />
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.salesForm")}</span>
                      <input className="right-panel-field" type="text"
                        value={cardForm.sales_form ?? ""}
                        onChange={(e) => handleCardFieldChange("sales_form", e.target.value)}
                        onBlur={handleCardFieldBlur} />
                    </div>
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.competitorCheck")}</span>
                      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                        <input type="checkbox"
                          checked={cardForm.competitor_check ?? false}
                          onChange={(e) => {
                            handleCardFieldChange("competitor_check", e.target.checked);
                            setTimeout(handleCardFieldBlur, 0);
                          }} />
                        <span className="right-panel-value">
                          {cardForm.competitor_check ? t("leads.competitorDone") : t("leads.competitorNotDone")}
                        </span>
                      </label>
                    </div>

                    <hr className="right-panel-divider" />

                    <div className="right-panel-memo-label">{t("leads.notes")}</div>
                    <textarea className="right-panel-field" rows={3}
                      value={cardForm.notes ?? ""}
                      onChange={(e) => handleCardFieldChange("notes", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.notes")} />
                    <div className="right-panel-memo-label">{t("leads.meetingMemo")}</div>
                    <textarea className="right-panel-field" rows={3}
                      value={cardForm.meeting_memo ?? ""}
                      onChange={(e) => handleCardFieldChange("meeting_memo", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.meetingMemo")} />
                    <div className="right-panel-memo-label">{t("leads.csMemo")}</div>
                    <textarea className="right-panel-field" rows={3}
                      value={cardForm.cs_memo ?? ""}
                      onChange={(e) => handleCardFieldChange("cs_memo", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.csMemo")} />
                  </div>
                )}

              </div>

            </div>
          ) : (
            <div className="right-panel-empty">
              <p>{t("inbox.loadingProfile")}</p>
            </div>
          )}
        </aside>

      </div>{/* /inbox-wrapper */}
      </PageLayout>

      {/* ============================== 受信箱設定モーダル ============================== */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="inbox-settings-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="inbox-settings-modal-title">{t("inbox.settings.title")}</h3>

            <div className="inbox-settings-section-title">{t("inbox.settings.display")}</div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.showRightPanel")}</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={inboxSettings.showRightPanel}
                  onChange={(e) => updateInboxSetting("showRightPanel", e.target.checked)} />
                <span className="toggle-switch-slider" />
              </label>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.defaultTab")}</span>
              <select className="inbox-settings-select"
                value={inboxSettings.defaultTab}
                onChange={(e) => updateInboxSetting("defaultTab", e.target.value as StatusTabKey)}>
                <option value="all">{t("inbox.settings.defaultTabAll")}</option>
                <option value="lead">{t("inbox.settings.defaultTabLead")}</option>
                <option value="deal">{t("inbox.settings.defaultTabDeal")}</option>
                <option value="existing">{t("inbox.settings.defaultTabExisting")}</option>
                <option value="followup">{t("inbox.settings.defaultTabFollowUp")}</option>
                <option value="archive">{t("inbox.settings.defaultTabArchive")}</option>
              </select>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.defaultUnreadOnly")}</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={inboxSettings.defaultUnreadOnly}
                  onChange={(e) => updateInboxSetting("defaultUnreadOnly", e.target.checked)} />
                <span className="toggle-switch-slider" />
              </label>
            </div>

            <div className="inbox-settings-section-title" style={{ marginTop: "var(--space-4)" }}>
              {t("inbox.settings.notifications")}
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.browserNotifications")}</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={inboxSettings.browserNotifications}
                  onChange={async (e) => {
                    if (e.target.checked) {
                      const perm = await Notification.requestPermission();
                      if (perm === "denied") {
                        alert(t("inbox.settings.browserNotificationsDenied"));
                        return;
                      }
                    }
                    updateInboxSetting("browserNotifications", e.target.checked);
                  }} />
                <span className="toggle-switch-slider" />
              </label>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.soundEnabled")}</span>
              <label className="toggle-switch">
                <input type="checkbox" checked={inboxSettings.soundEnabled}
                  onChange={(e) => updateInboxSetting("soundEnabled", e.target.checked)} />
                <span className="toggle-switch-slider" />
              </label>
            </div>

            <button type="button" className="inbox-settings-close-btn" onClick={() => setShowSettings(false)}>
              {t("common.close")}
            </button>
          </div>
        </div>
      )}

      {/* ============================== プロフィールモーダル ============================== */}
      {showProfileModal && leadDetail && (
        <div
          className="modal-overlay"
          onClick={() => setShowProfileModal(false)}
          role="presentation"
        >
          <div
            ref={profileModalRef}
            className="inbox-profile-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="profile-modal-name"
          >
            <div className="inbox-profile-modal-header">
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
              <span id="profile-modal-name" className="right-panel-display-name">
                {cardForm.nickname || leadDetail.nickname || cardForm.customer_name || leadDetail.customer_name}
              </span>
              <button
                type="button"
                className="inbox-profile-modal-close"
                onClick={() => setShowProfileModal(false)}
                aria-label={t("common.close")}
              >
                <NAV_ICONS.close size={ICON.md} aria-hidden="true" />
              </button>
            </div>
            <div className="right-panel-save-indicator">
              {cardSaveStatus === "saving" && <span>{t("common.saving")}</span>}
              {cardSaveStatus === "saved" && <span className="saved">{t("common.saved")}</span>}
              {cardSaveStatus === "error" && <span className="error">{cardSaveError}</span>}
            </div>
            <div className="right-panel-tabs">
              <button type="button"
                className={`right-panel-tab${profileModalTab === "deal" ? " active" : ""}`}
                onClick={() => setProfileModalTab("deal")}
              >{t("inbox.karteDeal")}</button>
              <button type="button"
                className={`right-panel-tab${profileModalTab === "contact" ? " active" : ""}`}
                onClick={() => setProfileModalTab("contact")}
              >{t("inbox.karteContact")}</button>
              <button type="button"
                className={`right-panel-tab${profileModalTab === "company" ? " active" : ""}`}
                onClick={() => setProfileModalTab("company")}
              >{t("inbox.karteCompany")}</button>
            </div>
            <div className="right-panel-tab-content">
              {profileModalTab === "contact" && (
                <div className="right-panel-section">
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.nickname")}</span>
                    <input className="right-panel-field" type="text"
                      value={cardForm.nickname ?? ""}
                      onChange={(e) => handleCardFieldChange("nickname", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder={t("leads.nickname")} />
                  </div>
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
                </div>
              )}
              {profileModalTab === "company" && (
                <div className="right-panel-section">
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.companyName")}</span>
                    <input className="right-panel-field" type="text"
                      value={cardForm.company_name ?? ""}
                      onChange={(e) => handleCardFieldChange("company_name", e.target.value)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                </div>
              )}
              {profileModalTab === "deal" && (
                <div className="right-panel-section">
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("inbox.platformName")}</span>
                    <span className="right-panel-value">{leadDetail.customer_name}</span>
                  </div>
                  <hr className="right-panel-divider" />
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.status")}</span>
                    <select className="right-panel-field"
                      value={cardForm.status ?? ""}
                      onChange={(e) => handleCardFieldChange("status", e.target.value)}
                      onBlur={handleCardFieldBlur}>
                      <option value="新規">{t("leads.status_new")}</option>
                      <option value="商談中">{t("leads.status_negotiating")}</option>
                      <option value="既存顧客">{t("leads.status_existing_customer")}</option>
                      <option value="追客（短期）">{t("leads.status_follow_up_short")}</option>
                      <option value="追客（長期）">{t("leads.status_follow_up_long")}</option>
                      <option value="失注">{t("leads.status_lost")}</option>
                      <option value="対象外">{t("leads.status_out_of_scope")}</option>
                    </select>
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.temperature")}</span>
                    <select className="right-panel-field"
                      value={cardForm.temperature ?? ""}
                      onChange={(e) => handleCardFieldChange("temperature", e.target.value || null)}
                      onBlur={handleCardFieldBlur}>
                      <option value="">—</option>
                      <option value="Hot">Hot</option>
                      <option value="Warm">Warm</option>
                      <option value="Cold">Cold</option>
                    </select>
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.nextActionDate")}</span>
                    <input className="right-panel-field" type="date"
                      value={cardForm.next_action_date ?? ""}
                      onChange={(e) => handleCardFieldChange("next_action_date", e.target.value || null)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <textarea className="right-panel-field" rows={3}
                    value={cardForm.next_action ?? ""}
                    onChange={(e) => handleCardFieldChange("next_action", e.target.value)}
                    onBlur={handleCardFieldBlur}
                    placeholder={t("leads.nextAction")} />
                  <hr className="right-panel-divider" />
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.estimatedScale")}</span>
                    <select className="right-panel-field"
                      value={cardForm.estimated_scale ?? ""}
                      onChange={(e) => handleCardFieldChange("estimated_scale", e.target.value || null)}
                      onBlur={handleCardFieldBlur}>
                      <option value="">—</option>
                      <option value="Small">Small</option>
                      <option value="Medium">Medium</option>
                      <option value="Large">Large</option>
                    </select>
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.monthlyForecast")}</span>
                    <input className="right-panel-field" type="number" min="0"
                      value={cardForm.monthly_forecast ?? ""}
                      onChange={(e) => handleCardFieldChange("monthly_forecast", e.target.value || null)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.perOrderAmount")}</span>
                    <input className="right-panel-field" type="number" min="0"
                      value={cardForm.per_order_amount ?? ""}
                      onChange={(e) => handleCardFieldChange("per_order_amount", e.target.value || null)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.monthlyFrequency")}</span>
                    <input className="right-panel-field" type="number" min="0"
                      value={cardForm.monthly_frequency ?? ""}
                      onChange={(e) => handleCardFieldChange("monthly_frequency", e.target.value || null)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <hr className="right-panel-divider" />
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.customerType")}</span>
                    <select className="right-panel-field"
                      value={cardForm.customer_type ?? ""}
                      onChange={(e) => handleCardFieldChange("customer_type", e.target.value || null)}
                      onBlur={handleCardFieldBlur}>
                      <option value="">—</option>
                      <option value="信頼重視">{t("leads.customerType_trust")}</option>
                      <option value="価格重視">{t("leads.customerType_price")}</option>
                    </select>
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.responseSpeed")}</span>
                    <select className="right-panel-field"
                      value={cardForm.response_speed ?? ""}
                      onChange={(e) => handleCardFieldChange("response_speed", e.target.value || null)}
                      onBlur={handleCardFieldBlur}>
                      <option value="">—</option>
                      <option value="24h以内">{t("leads.responseSpeed_24h")}</option>
                      <option value="3日以内">{t("leads.responseSpeed_3days")}</option>
                      <option value="3日超">{t("leads.responseSpeed_over3days")}</option>
                    </select>
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.country")}</span>
                    <input className="right-panel-field" type="text"
                      value={cardForm.country ?? ""}
                      onChange={(e) => handleCardFieldChange("country", e.target.value)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.targetTitles")}</span>
                    <input className="right-panel-field" type="text"
                      value={cardForm.target_titles ?? ""}
                      onChange={(e) => handleCardFieldChange("target_titles", e.target.value)}
                      onBlur={handleCardFieldBlur}
                      placeholder="Pokemon, One Piece, ..." />
                  </div>
                  <textarea className="right-panel-field" rows={3}
                    value={cardForm.challenge ?? ""}
                    onChange={(e) => handleCardFieldChange("challenge", e.target.value)}
                    onBlur={handleCardFieldBlur}
                    placeholder={t("leads.challenge")} />
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.salesForm")}</span>
                    <input className="right-panel-field" type="text"
                      value={cardForm.sales_form ?? ""}
                      onChange={(e) => handleCardFieldChange("sales_form", e.target.value)}
                      onBlur={handleCardFieldBlur} />
                  </div>
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.competitorCheck")}</span>
                    <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                      <input type="checkbox"
                        checked={cardForm.competitor_check ?? false}
                        onChange={(e) => {
                          handleCardFieldChange("competitor_check", e.target.checked);
                          setTimeout(handleCardFieldBlur, 0);
                        }} />
                      <span className="right-panel-value">
                        {cardForm.competitor_check ? t("leads.competitorDone") : t("leads.competitorNotDone")}
                      </span>
                    </label>
                  </div>
                  <hr className="right-panel-divider" />
                  <div className="right-panel-memo-label">{t("leads.notes")}</div>
                  <textarea className="right-panel-field" rows={3}
                    value={cardForm.notes ?? ""}
                    onChange={(e) => handleCardFieldChange("notes", e.target.value)}
                    onBlur={handleCardFieldBlur}
                    placeholder={t("leads.notes")} />
                  <div className="right-panel-memo-label">{t("leads.meetingMemo")}</div>
                  <textarea className="right-panel-field" rows={3}
                    value={cardForm.meeting_memo ?? ""}
                    onChange={(e) => handleCardFieldChange("meeting_memo", e.target.value)}
                    onBlur={handleCardFieldBlur}
                    placeholder={t("leads.meetingMemo")} />
                  <div className="right-panel-memo-label">{t("leads.csMemo")}</div>
                  <textarea className="right-panel-field" rows={3}
                    value={cardForm.cs_memo ?? ""}
                    onChange={(e) => handleCardFieldChange("cs_memo", e.target.value)}
                    onBlur={handleCardFieldBlur}
                    placeholder={t("leads.csMemo")} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
