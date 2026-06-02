import { useTranslation } from "react-i18next";
import { INBOX_ACTION_ICONS, NAV_ICONS, PlatformIcon, SQUIRCLE_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { Conversation } from "../../lib/messages";
import { getInitials, relativeTime } from "./inbox.types";

interface Props {
  // 管理ドロップダウン
  manageRef: React.RefObject<HTMLDivElement>;
  manageOpen: boolean;
  selectMode: boolean;
  toggleSelectMode: () => void;
  handleMarkAllRead: () => void;
  // フィルタ
  unreadOnly: boolean;
  setUnreadOnly: (fn: (v: boolean) => boolean) => void;
  followUpOnly: boolean;
  setFollowUpOnly: (fn: (v: boolean) => boolean) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  pageIdFilter: string;
  availablePageIds: string[];
  onPageFilterChange: (pid: string) => void;
  // 一括選択
  selectedLeadIds: Set<number>;
  isAllSelected: boolean;
  toggleSelectAll: () => void;
  handleBulkMarkRead: () => void;
  handleBulkMarkUnread: () => void;
  handleBulkExclude: () => void;
  handleBulkDelete: () => void;
  // 会話リスト
  convLoading: boolean;
  convError: string;
  filteredConversations: Conversation[];
  loadConversations: () => void;
  selectedLeadId: number | null;
  avatarErrors: Set<number>;
  handleAvatarError: (id: number) => void;
  selectLead: (id: number) => void;
  toggleSelectConv: (id: number) => void;
}

export function InboxConversationList({
  manageRef, manageOpen, selectMode, toggleSelectMode, handleMarkAllRead,
  unreadOnly, setUnreadOnly, followUpOnly, setFollowUpOnly,
  searchQuery, setSearchQuery, pageIdFilter, availablePageIds, onPageFilterChange,
  selectedLeadIds, isAllSelected, toggleSelectAll,
  handleBulkMarkRead, handleBulkMarkUnread, handleBulkExclude, handleBulkDelete,
  convLoading, convError, filteredConversations, loadConversations,
  selectedLeadId, avatarErrors, handleAvatarError, selectLead, toggleSelectConv,
}: Props) {
  const { t } = useTranslation();

  return (
    <aside className="inbox-left-panel">
      {/* 検索 + 管理ボタン */}
      <div className="inbox-search-row">
        <div className="inbox-search-wrap">
          <NAV_ICONS.search size={14} weight="fill" className="inbox-search-icon" aria-hidden="true" />
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
            <NAV_ICONS.filter size={13} weight="fill" />
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

      {/* 一括アクションバー */}
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
          <button type="button" className="inbox-bulk-action" onClick={handleBulkMarkRead}
            disabled={selectedLeadIds.size === 0} title={t("inbox.markAllRead")} aria-label={t("inbox.markAllRead")}>
            <INBOX_ACTION_ICONS.markRead size={14} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-bulk-action" onClick={handleBulkMarkUnread}
            disabled={selectedLeadIds.size === 0} title={t("inbox.markUnread")} aria-label={t("inbox.markUnread")}>
            <INBOX_ACTION_ICONS.markUnread size={14} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-bulk-action" onClick={handleBulkExclude}
            disabled={selectedLeadIds.size === 0} title={t("inbox.exclude")} aria-label={t("inbox.exclude")}>
            <INBOX_ACTION_ICONS.exclude size={14} weight="fill" aria-hidden="true" />
          </button>
          <button type="button" className="inbox-bulk-action inbox-bulk-delete" onClick={handleBulkDelete}
            disabled={selectedLeadIds.size === 0} title={t("inbox.deleteLead")} aria-label={t("inbox.deleteLead")}>
            <INBOX_ACTION_ICONS.delete size={14} weight="fill" aria-hidden="true" />
          </button>
        </div>
      )}

      {/* サブフィルターピル */}
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

      {/* Page フィルタ */}
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
        {convError.length > 0 && (
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
                {selectMode && (
                  <span aria-hidden="true" className={`conv-select-check${isBulkChecked ? " checked" : ""}`} />
                )}
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
                  <span className={`conv-platform-dot icon-frame${SQUIRCLE_ICONS.has(conv.platform ?? "") ? " conv-platform-dot--squircle" : ""}`}>
                    <PlatformIcon platform={conv.platform} size={ICON.base} />
                  </span>
                </div>
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
  );
}
