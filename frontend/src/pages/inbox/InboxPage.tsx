/**
 * Inbox ページ（Phase 1-D Sprint 4 / Sprint 5 / Sprint 6 / Sprint 7 redesign）。
 *
 * Meta Business Suite 風の 3 カラムレイアウト。
 * コンポーネント構成:
 *   InboxConversationList  — 左パネル（タブ + 会話一覧）
 *   InboxMessageThread     — 中央パネル（メッセージスレッド + 送信エリア）
 *   InboxKartePanel        — 右パネル（商談カルテ）
 *   InboxSettingsModal     — 受信箱設定モーダル
 *   InboxProfileModal      — プロフィールモーダル
 */

import "./InboxPage.css";
import { useNavigate } from "react-router-dom";
import { NAV_ICONS } from "../../constants/icons";
import { PageLayout } from "../../components/PageLayout";
import { ICON } from "../../constants/iconSizes";
import { useInboxState } from "./useInboxState";
import { STATUS_TABS } from "./inbox.types";
import type { PlatformFilter } from "../../lib/messages";
import { InboxConversationList } from "./InboxConversationList";
import { InboxMessageThread } from "./InboxMessageThread";
import { InboxKartePanel } from "./InboxKartePanel";
import { InboxSettingsModal } from "./InboxSettingsModal";
import { InboxProfileModal } from "./InboxProfileModal";

export default function InboxPage() {
  const state = useInboxState();
  const {
    t,
    inboxSettings, showSettings, setShowSettings, updateInboxSetting,
    selectedLeadId, leadDetail, cardForm, cardSaveStatus, cardSaveError,
    showKartePanel, openKartePanel, closeKartePanel,
    showProfileModal, setShowProfileModal,
    profileModalTab, setProfileModalTab, profileModalRef,
    handleCardFieldChange, handleCardFieldBlur,
    karteTab, setKarteTab,
    selectedConversation, avatarErrors, handleAvatarError,
  } = state;

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
          {/* 左+中央エリア */}
          <div className="inbox-main-area">
            {/* ステータスタブ + プラットフォームフィルタ */}
            <div className="inbox-full-tab-bar">
              {STATUS_TABS.map((tab) => (
                <button key={tab.key} type="button"
                  className={`inbox-full-tab${state.statusTab === tab.key ? " active" : ""}`}
                  onClick={() => state.setStatusTab(tab.key)}>
                  {t(tab.labelKey)}
                </button>
              ))}
              <select
                className="inbox-platform-select"
                value={state.platformFilter}
                onChange={(e) => state.setPlatformFilter(e.target.value as PlatformFilter)}
                aria-label={t("inbox.platformFilter")}
              >
                <option value="all">{t("inbox.platformAll")}</option>
                <option value="messenger">{t("inbox.platformMessenger")}</option>
                <option value="instagram">{t("inbox.platformInstagram")}</option>
              </select>
            </div>

            <div className="inbox-columns">
              <InboxConversationList
                unreadOnly={state.unreadOnly}
                setUnreadOnly={state.setUnreadOnly}
                followUpOnly={state.followUpOnly}
                setFollowUpOnly={state.setFollowUpOnly}
                searchQuery={state.searchQuery}
                setSearchQuery={state.setSearchQuery}
                pageIdFilter={state.pageIdFilter}
                availablePageIds={state.availablePageIds}
                onPageFilterChange={state.onPageFilterChange}
                manageRef={state.manageRef}
                manageOpen={state.manageOpen}
                selectMode={state.selectMode}
                toggleSelectMode={state.toggleSelectMode}
                handleMarkAllRead={state.handleMarkAllRead}
                selectedLeadIds={state.selectedLeadIds}
                isAllSelected={state.isAllSelected}
                toggleSelectAll={state.toggleSelectAll}
                handleBulkMarkRead={state.handleBulkMarkRead}
                handleBulkMarkUnread={state.handleBulkMarkUnread}
                handleBulkExclude={state.handleBulkExclude}
                handleBulkDelete={state.handleBulkDelete}
                convLoading={state.convLoading}
                convError={state.convError}
                filteredConversations={state.filteredConversations}
                loadConversations={state.loadConversations}
                selectedLeadId={selectedLeadId}
                avatarErrors={avatarErrors}
                handleAvatarError={handleAvatarError}
                selectLead={state.selectLead}
                toggleSelectConv={state.toggleSelectConv}
              />

              <InboxMessageThread
                selectedLeadId={selectedLeadId}
                selectedConversation={selectedConversation}
                messagesData={state.messagesData}
                msgLoading={state.msgLoading}
                msgError={state.msgError}
                avatarErrors={avatarErrors}
                handleAvatarError={handleAvatarError}
                handleMarkUnread={state.handleMarkUnread}
                handleExclude={state.handleExclude}
                handleDeleteLead={state.handleDeleteLead}
                showKartePanel={showKartePanel}
                openKartePanel={openKartePanel}
                closeKartePanel={closeKartePanel}
                inboxSettings={inboxSettings}
                messageListRef={state.messageListRef}
                draft={state.draft}
                setDraft={state.setDraft}
                sending={state.sending}
                sendError={state.sendError}
                sendDisabled={state.sendDisabled}
                canSend={state.canSend}
                trimmedDraft={state.trimmedDraft}
                submitSend={state.submitSend}
                handleKeyDown={state.handleKeyDown}
              />
            </div>
          </div>

          {/* モバイルドロワーバックドロップ */}
          {showKartePanel && inboxSettings.showRightPanel && (
            <div className="karte-overlay" onClick={closeKartePanel} aria-hidden="true" />
          )}

          <InboxKartePanel
            selectedLeadId={selectedLeadId}
            leadDetail={leadDetail}
            cardForm={cardForm}
            cardSaveStatus={cardSaveStatus}
            cardSaveError={cardSaveError}
            karteTab={karteTab}
            setKarteTab={setKarteTab}
            showKartePanel={showKartePanel}
            closeKartePanel={closeKartePanel}
            setShowProfileModal={setShowProfileModal}
            inboxSettings={inboxSettings}
            selectedConversation={selectedConversation}
            avatarErrors={avatarErrors}
            handleAvatarError={handleAvatarError}
            handleCardFieldChange={handleCardFieldChange}
            handleCardFieldBlur={handleCardFieldBlur}
          />
        </div>
      </PageLayout>

      {/* 受信箱設定モーダル */}
      {showSettings && (
        <InboxSettingsModal
          inboxSettings={inboxSettings}
          updateInboxSetting={updateInboxSetting}
          onClose={() => setShowSettings(false)}
        />
      )}

      {/* プロフィールモーダル */}
      {showProfileModal && leadDetail && (
        <InboxProfileModal
          leadDetail={leadDetail}
          cardForm={cardForm}
          cardSaveStatus={cardSaveStatus}
          cardSaveError={cardSaveError}
          profileModalTab={profileModalTab}
          setProfileModalTab={setProfileModalTab}
          profileModalRef={profileModalRef}
          selectedConversation={selectedConversation}
          avatarErrors={avatarErrors}
          handleAvatarError={handleAvatarError}
          handleCardFieldChange={handleCardFieldChange}
          handleCardFieldBlur={handleCardFieldBlur}
          onClose={() => setShowProfileModal(false)}
        />
      )}
    </>
  );
}
