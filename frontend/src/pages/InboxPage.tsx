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

import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import {
  Conversation,
  MessagesResponse,
  MessagingWindow,
  PlatformFilter,
  getMessages,
  inferPlatform,
  listConversations,
  markRead as apiMarkRead,
  platformLabel as libPlatformLabel,
  sendMessage,
} from "../lib/messages";

// ---------------------------------------------------------------------------
// 設定
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 10_000;

// ---------------------------------------------------------------------------
// リードステータス分類定数
// ---------------------------------------------------------------------------

// タブ別ステータス定義
// leads    → 営業進行中リード
// converted → 案件化（商談開始）
// customers → 既存顧客（成約済み）
// ※ 追客（短期）/ 追客（長期）/ 対象外 は「すべて」タブのみに表示（ADR-062 で 追客タブ追加予定）
const LEADS_STATUSES = ["新規", "コンタクト中", "AI対応中", "提案中", "保留", "失注"];
const CONVERTED_STATUSES = ["案件化"];
const CUSTOMERS_STATUSES = ["既存顧客"];

type LeadStatusFilter = "all" | "leads" | "converted" | "customers";

// ---------------------------------------------------------------------------
// LeadDetail 型（GET /leads/{id} のレスポンス）
// ---------------------------------------------------------------------------

interface LeadDetail {
  id: number;
  lead_code: string | null;
  customer_name: string;
  company_name: string | null;
  email: string | null;
  phone: string | null;
  status: string;
  temperature: string | null;
  estimated_scale: string | null;
  customer_type: string | null;
  response_speed: string | null;
  monthly_forecast: string | null;
  prospect_rank: string | null;
  notes: string | null;
  // ADR-015 商談カルテフィールド
  next_action: string | null;
  next_action_date: string | null;
  challenge: string | null;
  meeting_memo: string | null;
  meeting_impression: string | null;
  cs_memo: string | null;
  sales_form: string | null;
  competitor_check: boolean | null;
  per_order_amount: string | null;
  monthly_frequency: string | null;
  english_name: string | null;
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** ISO/SQLite 互換の datetime 文字列を Date に変換（無効値なら null）。 */
function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso.replace(" ", "T"));
  return isNaN(d.getTime()) ? null : d;
}

/** 現時刻を起点に「N 分前」「N 時間前」等の相対表記。 */
function relativeTime(iso: string | null): string {
  const d = parseDate(iso);
  if (!d) return "—";
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}h ago`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString("en-US", { month: "2-digit", day: "2-digit" });
}

/** `2026-04-30 14:25` 形式の絶対時刻（吹き出しの hover タイトル用）。 */
function formatAbsolute(iso: string | null): string {
  const d = parseDate(iso);
  if (!d) return "—";
  return d.toLocaleString("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/** イニシャルアバター文字（最大 2 文字）。 */
function getInitials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/** プラットフォームのグラデーション背景（ドット用）。 */
function platformGradient(platform: string | null): string {
  if (platform === "messenger") {
    return "linear-gradient(90deg, #08f, #a033ff 55.81%, #ff5c87 109.33%)";
  }
  if (platform === "instagram") {
    return "linear-gradient(135deg, #ffd600, #ff7a00, #ff0169, #d300c5 75%)";
  }
  return "#999";
}

// Phase 1-E F24-S5: lib/messages.ts の libPlatformLabel に集約。後方互換のため alias 維持。
const platformLabel = libPlatformLabel;

// ---------------------------------------------------------------------------
// グローバルスタイル（<style> タグ経由で挿入）
// ---------------------------------------------------------------------------

const INBOX_STYLES = `
/* ======= Inbox Meta Design (ADR-063) ======= */

/* 全体ラッパー（flex column） */
.inbox-wrapper {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px);
  overflow: hidden;
  font-family: 'SF Pro Text', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: #E9EBEE;
}

/* ページヘッダー（Meta 風: タイトル + サブタイトル） */
.inbox-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px 12px;
  background: #fff;
  border-bottom: 1px solid #dadde1;
  flex-shrink: 0;
}
.inbox-page-title {
  font-size: 20px;
  font-weight: 700;
  color: #1c1e21;
  margin: 0 0 4px;
  line-height: 1.2;
}
.inbox-page-subtitle {
  font-size: 13px;
  color: #65676B;
  margin: 0;
}

/* 全幅タブバー（3カラムの上・コンテンツエリア全幅） */
.inbox-full-tab-bar {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #dadde1;
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 0 8px;
}
.inbox-full-tab-bar::-webkit-scrollbar { display: none; }
.inbox-full-tab {
  height: 52px;
  padding: 0 20px;
  border: none;
  border-bottom: 3px solid transparent;
  margin-bottom: -1px;
  background: transparent;
  font-size: 15px;
  font-weight: 600;
  color: #65676B;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.1s, border-color 0.1s;
  font-family: inherit;
}
.inbox-full-tab:hover {
  color: #0064E0;
  background: rgba(0, 0, 0, 0.03);
}
.inbox-full-tab.active {
  color: #0064E0;
  border-bottom-color: #0064E0;
}

/* 3カラムコンテンツエリア */
.inbox-columns {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ---- 左パネル ---- */
.inbox-left-panel {
  width: 340px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #dadde1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* パネルタイトル（スクリーンリーダー専用 — 視覚的に非表示） */
.inbox-panel-title {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0,0,0,0);
  white-space: nowrap;
  border: 0;
}

/* 検索 + 管理ボタン行 */
.inbox-search-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 4px;
  flex-shrink: 0;
}
.inbox-search-input {
  flex: 1;
  min-width: 0;
  padding: 8px 12px;
  border-radius: 20px;
  border: none;
  background: #F0F2F5;
  font-size: 14px;
  color: #1c1e21;
  outline: none;
  box-sizing: border-box;
}
.inbox-search-input::placeholder {
  color: #65676B;
}

/* 管理ボタン */
.inbox-manage-wrap {
  position: relative;
  flex-shrink: 0;
}
.inbox-manage-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 6px;
  border: 1px solid #dadde1;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  color: #1c1e21;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
  white-space: nowrap;
}
.inbox-manage-btn:hover { background: #F0F2F5; }
.inbox-manage-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 180px;
  background: #fff;
  border: 1px solid #dadde1;
  border-radius: 8px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  z-index: 100;
  overflow: hidden;
}
.inbox-manage-item {
  display: block;
  width: 100%;
  padding: 10px 14px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 13px;
  color: #1c1e21;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
}
.inbox-manage-item:hover { background: #F0F2F5; }

/* プラットフォームフィルタバー */
.inbox-platform-bar {
  display: flex;
  gap: 6px;
  padding: 6px 12px 8px;
  border-bottom: 1px solid #dadde1;
  align-items: center;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.inbox-platform-tab {
  padding: 4px 12px;
  border-radius: 20px;
  border: 1px solid #dadde1;
  font-size: 12px;
  background: transparent;
  color: #65676B;
  cursor: pointer;
  transition: all 0.1s;
  font-family: inherit;
}
.inbox-platform-tab.active {
  background: #E7F3FF;
  color: #0866FF;
  border-color: #0866FF;
  font-weight: 600;
}
.inbox-unread-check {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #65676B;
  cursor: pointer;
  white-space: nowrap;
}

/* 会話リスト */
.inbox-conversation-list {
  flex: 1;
  overflow-y: auto;
}

/* 会話アイテム */
.conv-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  width: 100%;
  border: none;
  border-bottom: 1px solid #F0F2F5;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s;
  font-family: inherit;
  box-sizing: border-box;
}
.conv-item:hover { background: rgba(0, 0, 0, 0.04); }
.conv-item.selected { background: #E7F3FF; }

/* アバター */
.conv-avatar-wrap {
  position: relative;
  flex-shrink: 0;
}
.conv-avatar {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #E4E6EB;
  color: #1c1e21;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  font-weight: 700;
  user-select: none;
}
.conv-platform-dot {
  position: absolute;
  bottom: -1px;
  right: -1px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid #fff;
}

/* 会話情報 */
.conv-info { flex: 1; min-width: 0; }
.conv-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 6px;
}
.conv-name {
  font-size: 14px;
  font-weight: 600;
  color: #1c1e21;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-time {
  font-size: 11px;
  color: #65676B;
  flex-shrink: 0;
}
.conv-preview {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
}
.conv-preview-text {
  font-size: 13px;
  color: #65676B;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.conv-preview-text.unread {
  color: #1c1e21;
  font-weight: 600;
}
.conv-unread-badge {
  background: #1877F2;
  color: #fff;
  border-radius: 10px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}
.conv-platform-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: #F0F2F5;
  color: #65676B;
  flex-shrink: 0;
}

/* ---- 中央パネル ---- */
.inbox-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  min-width: 0;
}
.inbox-center-header {
  padding: 12px 16px;
  border-bottom: 1px solid #dadde1;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
.inbox-center-title {
  font-size: 16px;
  font-weight: 700;
  color: #1c1e21;
  margin: 0;
}
.inbox-platform-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}
.inbox-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.inbox-msg-row { display: flex; }
.inbox-msg-row.outbound { justify-content: flex-end; }
.inbox-msg-row.inbound { justify-content: flex-start; }
.msg-bubble {
  max-width: 70%;
  padding: 8px 12px;
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
  white-space: pre-wrap;
}
.msg-bubble.outbound {
  background: #7C3AED;
  color: #fff;
  border-radius: 18px 18px 4px 18px;
}
.msg-bubble.inbound {
  background: #E4E6EB;
  color: #1c1e21;
  border-radius: 18px 18px 18px 4px;
}
.msg-bubble.failed {
  background: #fdecea;
  color: #a50e0e;
  border: 2px solid #a50e0e;
  border-radius: 12px;
}
.msg-time {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 4px;
  text-align: right;
}
.msg-time.inbound { text-align: left; }

/* 送信エリア */
.inbox-send-area {
  border-top: 1px solid #dadde1;
  padding: 10px 16px;
  flex-shrink: 0;
  background: #fff;
}
.inbox-textarea {
  width: 100%;
  border: 1px solid #dadde1;
  border-radius: 20px;
  padding: 10px 16px;
  font-size: 14px;
  resize: none;
  font-family: inherit;
  outline: none;
  background: #F0F2F5;
  color: #1c1e21;
  box-sizing: border-box;
  line-height: 1.4;
}
.inbox-textarea:focus { border-color: #0866FF; background: #fff; }
.inbox-textarea:disabled { background: #F0F2F5; cursor: not-allowed; }
.inbox-send-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
.inbox-send-btn {
  padding: 8px 20px;
  border-radius: 20px;
  background: #0866FF;
  color: #fff;
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
}
.inbox-send-btn:hover:not(:disabled) { background: #0756d6; }
.inbox-send-btn:disabled {
  background: #E4E6EB;
  color: #65676B;
  cursor: not-allowed;
}

/* 空状態 */
.inbox-empty-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #65676B;
  font-size: 15px;
  gap: 12px;
}
.inbox-empty-icon { font-size: 48px; }

/* ---- 右パネル ---- */
.inbox-right-panel {
  width: 300px;
  flex-shrink: 0;
  background: #fff;
  border-left: 1px solid #dadde1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px 16px;
  overflow-y: auto;
}
.right-panel-avatar {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #E4E6EB;
  color: #1c1e21;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  font-weight: 700;
  margin-bottom: 12px;
  user-select: none;
}
.right-panel-name {
  font-size: 17px;
  font-weight: 700;
  color: #1c1e21;
  text-align: center;
  margin: 0;
}
.right-panel-code {
  font-size: 12px;
  color: #65676B;
  margin-top: 4px;
  text-align: center;
}
.right-panel-status {
  margin-top: 10px;
  padding: 4px 14px;
  border-radius: 20px;
  background: #E7F3FF;
  color: #0866FF;
  font-size: 12px;
  font-weight: 600;
}
.right-panel-section {
  width: 100%;
  margin-top: 20px;
}
.right-panel-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 0;
  border-bottom: 1px solid #F0F2F5;
}
.right-panel-label {
  font-size: 11px;
  color: #65676B;
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.right-panel-value {
  font-size: 13px;
  color: #1c1e21;
  font-weight: 500;
  word-break: break-word;
}
.right-panel-link {
  margin-top: 20px;
  display: inline-block;
  padding: 8px 20px;
  border-radius: 20px;
  background: #E7F3FF;
  color: #0866FF;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transition: background 0.1s;
}
.right-panel-link:hover { background: #d0e8ff; }
.right-panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #65676B;
  font-size: 14px;
  text-align: center;
  padding: 16px;
}

/* ヘッダーラッパー */
.right-panel-header {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 4px;
}

/* 英語名 */
.right-panel-en-name {
  font-size: 11px;
  color: #65676B;
  margin: 2px 0 0;
  text-align: center;
}

/* 見込度バッジ */
.right-panel-rank {
  margin-top: 6px;
  padding: 3px 12px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 700;
  background: #FFF3E0;
  color: #E65100;
}

/* セクションタイトル */
.right-panel-section-title {
  font-size: 11px;
  font-weight: 700;
  color: #65676B;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding-bottom: 6px;
  border-bottom: 1px solid #dadde1;
  margin-bottom: 2px;
}

/* 長文メモ */
.right-panel-memo {
  font-size: 12px;
  color: #1c1e21;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: #F0F2F5;
  border-radius: 6px;
  padding: 8px 10px;
  margin-top: 4px;
  margin-bottom: 6px;
}

/* メモ内サブラベル */
.right-panel-memo-label {
  font-size: 10px;
  font-weight: 700;
  color: #65676B;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-top: 8px;
}

/* エラー・ローディング */
.inbox-error-banner {
  padding: 8px 12px;
  background: #fdecea;
  color: #a50e0e;
  border: 1px solid #f5c2c2;
  border-radius: 8px;
  font-size: 13px;
  margin: 8px 12px;
}
.inbox-send-error {
  padding: 6px 10px;
  border-radius: 8px;
  background: #fdecea;
  color: #a50e0e;
  border: 1px solid #f5c2c2;
  font-size: 12px;
  margin-bottom: 6px;
}
`;

// ---------------------------------------------------------------------------
// メイン
// ---------------------------------------------------------------------------

export default function InboxPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialLeadIdRaw = searchParams.get("lead_id");
  const initialLeadId = initialLeadIdRaw && !isNaN(Number(initialLeadIdRaw))
    ? Number(initialLeadIdRaw)
    : null;

  // 会話リスト
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [convError, setConvError] = useState("");

  // フィルタ
  const [leadStatusFilter, setLeadStatusFilter] = useState<LeadStatusFilter>("all");
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Phase 1-E F14-S5: Page フィルタ
  const initialPageId = searchParams.get("page_id") || "";
  const [pageIdFilter, setPageIdFilter] = useState<string>(initialPageId);
  const [availablePageIds, setAvailablePageIds] = useState<string[]>([]);

  // 選択中会話
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(initialLeadId);
  const [messagesData, setMessagesData] = useState<MessagesResponse | null>(null);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");

  // 右パネル (顧客カルテ)
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);

  // 入力欄
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");

  // 管理ドロップダウン
  const [manageOpen, setManageOpen] = useState(false);
  const manageRef = useRef<HTMLDivElement | null>(null);

  // スクロール用 ref
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const skipNextPollRef = useRef(false);

  // ---------------------------------------------------------------------------
  // データ取得
  // ---------------------------------------------------------------------------

  const loadConversations = useCallback(async () => {
    setConvError("");
    try {
      const data = await listConversations({
        platform: platformFilter,
        unread_only: unreadOnly,
        page_id: pageIdFilter || undefined,
      });
      setConversations(data.conversations || []);
    } catch (e) {
      const msg = e instanceof ApiError
        ? e.message
        : e instanceof Error ? e.message : "Failed to load conversations";
      setConvError(msg);
    } finally {
      setConvLoading(false);
    }
  }, [platformFilter, unreadOnly, pageIdFilter]);

  // Page ID ドロップダウン用（フィルタなしで初回取得）
  useEffect(() => {
    let cancelled = false;
    listConversations({}).then((data) => {
      if (cancelled) return;
      const ids = Array.from(
        new Set(
          (data.conversations || [])
            .map((c) => c.page_id)
            .filter((p): p is string => !!p),
        ),
      ).sort();
      setAvailablePageIds(ids);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const loadMessages = useCallback(async (leadId: number) => {
    setMsgError("");
    setMsgLoading(true);
    try {
      const data = await getMessages(leadId);
      setMessagesData(data);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setMsgError("Lead not found.");
      } else {
        const msg = e instanceof ApiError
          ? e.message
          : e instanceof Error ? e.message : "Failed to load messages";
        setMsgError(msg);
      }
      setMessagesData(null);
    } finally {
      setMsgLoading(false);
    }
  }, []);

  const loadLeadDetail = useCallback(async (leadId: number) => {
    try {
      const data = await api.get<LeadDetail>(`/leads/${leadId}`);
      setLeadDetail(data);
    } catch {
      setLeadDetail(null);
    }
  }, []);

  const markRead = useCallback(async (leadId: number) => {
    try {
      const res = await apiMarkRead(leadId);
      if (res.marked_count > 0) {
        setConversations((prev) =>
          prev.map((c) => c.lead_id === leadId ? { ...c, unread_count: 0 } : c)
        );
      }
    } catch {
      // 既読化失敗は致命的ではないので無視
    }
  }, []);

  // ---------------------------------------------------------------------------
  // 初回 + filter 変更時の会話リスト取得
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setConvLoading(true);
    loadConversations();
  }, [loadConversations]);

  // ---------------------------------------------------------------------------
  // 10s polling
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const id = setInterval(() => {
      if (skipNextPollRef.current) {
        skipNextPollRef.current = false;
        return;
      }
      loadConversations();
      if (selectedLeadId !== null) {
        loadMessages(selectedLeadId);
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadConversations, loadMessages, selectedLeadId]);

  // ---------------------------------------------------------------------------
  // lead 選択時 → メッセージ取得 + 既読化 + URL 更新 + 右パネル
  // ---------------------------------------------------------------------------

  const selectLead = useCallback((leadId: number) => {
    setSelectedLeadId(leadId);
    setDraft("");
    setSendError("");
    const params = new URLSearchParams(searchParams);
    params.set("lead_id", String(leadId));
    setSearchParams(params, { replace: true });
  }, [searchParams, setSearchParams]);

  const onPageFilterChange = useCallback((value: string) => {
    setPageIdFilter(value);
    setSelectedLeadId(null);
    setLeadDetail(null);
    const params = new URLSearchParams(searchParams);
    if (value) {
      params.set("page_id", value);
    } else {
      params.delete("page_id");
    }
    params.delete("lead_id");
    setSearchParams(params, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (selectedLeadId === null) {
      setMessagesData(null);
      setLeadDetail(null);
      return;
    }
    loadMessages(selectedLeadId);
    markRead(selectedLeadId);
    loadLeadDetail(selectedLeadId);
  }, [selectedLeadId, loadMessages, markRead, loadLeadDetail]);

  // メッセージリスト末尾へ自動スクロール
  useEffect(() => {
    if (!messagesData) return;
    const el = messageListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messagesData]);

  // ---------------------------------------------------------------------------
  // フィルタリング（useMemo）
  // ---------------------------------------------------------------------------

  const filteredConversations = useMemo(() => {
    return conversations
      .filter((c) => {
        if (leadStatusFilter === "all") return true;
        if (leadStatusFilter === "leads") {
          return c.lead_status != null && LEADS_STATUSES.includes(c.lead_status);
        }
        if (leadStatusFilter === "converted") {
          return c.lead_status != null && CONVERTED_STATUSES.includes(c.lead_status);
        }
        if (leadStatusFilter === "customers") {
          return c.lead_status != null && CUSTOMERS_STATUSES.includes(c.lead_status);
        }
        return true;
      })
      .filter((c) => {
        if (!searchQuery) return true;
        const q = searchQuery.toLowerCase();
        return (
          (c.customer_name ?? "").toLowerCase().includes(q) ||
          (c.last_message_text ?? "").toLowerCase().includes(q)
        );
      });
  }, [conversations, leadStatusFilter, searchQuery]);

  // ---------------------------------------------------------------------------
  // 送信
  // ---------------------------------------------------------------------------

  const messagingWindow: MessagingWindow | undefined = messagesData?.messaging_window;
  const canSend = !!messagingWindow?.can_send_at_all;
  const trimmedDraft = draft.trim();
  const sendDisabled = sending || !canSend || trimmedDraft.length === 0 || selectedLeadId === null;

  const submitSend = useCallback(async () => {
    if (sendDisabled || selectedLeadId === null) return;
    setSendError("");
    setSending(true);
    try {
      await sendMessage(selectedLeadId, { text: trimmedDraft });
      setDraft("");
      skipNextPollRef.current = true;
      await loadMessages(selectedLeadId);
      loadConversations();
    } catch (e) {
      if (e instanceof ApiError) {
        setSendError(e.message || "Send failed");
      } else if (e instanceof Error) {
        setSendError(e.message);
      } else {
        setSendError("Send failed");
      }
    } finally {
      setSending(false);
    }
  }, [sendDisabled, selectedLeadId, trimmedDraft, loadMessages, loadConversations]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submitSend();
    }
  }, [submitSend]);

  // ---------------------------------------------------------------------------
  // 選択中会話
  // ---------------------------------------------------------------------------

  const selectedConversation = useMemo(
    () => conversations.find((c) => c.lead_id === selectedLeadId) || null,
    [conversations, selectedLeadId],
  );

  const selectedPlatform = inferPlatform(messagesData?.lead, selectedConversation);

  // ---------------------------------------------------------------------------
  // リードステータスタブ
  // ---------------------------------------------------------------------------

  const leadStatusTabs: { key: LeadStatusFilter; label: string }[] = [
    { key: "all", label: t("inbox.tabAll") },
    { key: "leads", label: t("inbox.tabLeads") },
    { key: "converted", label: t("inbox.tabConverted") },
    { key: "customers", label: t("inbox.tabCustomers") },
  ];

  // 管理ドロップダウン: click-outside で閉じる
  useEffect(() => {
    if (!manageOpen) return;
    const handler = (e: MouseEvent) => {
      if (manageRef.current && !manageRef.current.contains(e.target as Node)) {
        setManageOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [manageOpen]);

  // 全て既読にする（現在フィルタ済みの未読会話を一括既読化）
  const handleMarkAllRead = useCallback(async () => {
    setManageOpen(false);
    const unreadConvs = filteredConversations.filter((c) => c.unread_count > 0);
    await Promise.all(unreadConvs.map((c) => markRead(c.lead_id)));
  }, [filteredConversations, markRead]);

  // ---------------------------------------------------------------------------
  // 描画
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* グローバルスタイル注入 */}
      <style>{INBOX_STYLES}</style>

      <div className="inbox-wrapper">
        {/* ページヘッダー（Meta 風: タイトル + サブタイトル） */}
        <div className="inbox-page-header">
          <div>
            <h1 className="inbox-page-title">{t("inbox.title")}</h1>
            <p className="inbox-page-subtitle">{t("inbox.subtitle")}</p>
          </div>
        </div>

        {/* 全幅タブバー（リードステータスフィルタ） */}
        <div className="inbox-full-tab-bar" role="tablist" aria-label={t("inbox.title")}>
          {leadStatusTabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={leadStatusFilter === tab.key}
              className={`inbox-full-tab${leadStatusFilter === tab.key ? " active" : ""}`}
              onClick={() => setLeadStatusFilter(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 3カラムコンテンツ */}
        <div className="inbox-columns">

        {/* ============================== 左パネル ============================== */}
        <aside className="inbox-left-panel">
          {/* アクセシビリティ用タイトル（視覚的・意味論的に非表示：h1が全幅ヘッダーに移動済み） */}
          <h2 className="inbox-panel-title" aria-hidden="true">{t("inbox.title")}</h2>

          {/* 検索 + 管理ボタン */}
          <div className="inbox-search-row">
            <input
              type="text"
              className="inbox-search-input"
              placeholder={t("common.search")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <div className="inbox-manage-wrap" ref={manageRef}>
              <button
                type="button"
                className="inbox-manage-btn"
                onClick={() => setManageOpen((v) => !v)}
                aria-expanded={manageOpen}
              >
                <SlidersHorizontal size={13} />
                {t("inbox.manage")}
              </button>
              {manageOpen && (
                <div className="inbox-manage-dropdown" role="menu">
                  <button
                    type="button"
                    className="inbox-manage-item"
                    role="menuitem"
                    onClick={handleMarkAllRead}
                  >
                    {t("inbox.markAllRead")}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* 3. プラットフォームフィルタ + 未読チェック */}
          <div className="inbox-platform-bar">
            {(["all", "messenger", "instagram"] as PlatformFilter[]).map((p) => (
              <button
                key={p}
                type="button"
                className={`inbox-platform-tab${platformFilter === p ? " active" : ""}`}
                onClick={() => setPlatformFilter(p)}
              >
                {p === "all" ? t("inbox.all") : platformLabel(p)}
              </button>
            ))}
            <label className="inbox-unread-check">
              <input
                type="checkbox"
                checked={unreadOnly}
                onChange={(e) => setUnreadOnly(e.target.checked)}
              />
              {t("inbox.unread")}
            </label>
          </div>

          {/* Page フィルタ（複数 Page 時） */}
          {(availablePageIds.length > 1 || !!pageIdFilter) && (
            <div style={{ padding: "4px 12px 6px" }}>
              <select
                value={pageIdFilter}
                onChange={(e) => onPageFilterChange(e.target.value)}
                aria-label="Filter by Page"
                style={{
                  width: "100%",
                  padding: "4px 8px",
                  fontSize: "12px",
                  borderRadius: 16,
                  border: "1px solid #dadde1",
                  background: "white",
                  fontFamily: "inherit",
                }}
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
              <div className="inbox-error-banner">
                {convError}
                <button
                  type="button"
                  style={{ marginLeft: 8, fontSize: 12, cursor: "pointer" }}
                  onClick={() => loadConversations()}
                >
                  {t("common.reload")}
                </button>
              </div>
            )}
            {convLoading ? (
              <div style={{ padding: 24, textAlign: "center", color: "#65676B", fontSize: 14 }}>
                {t("common.loading")}
              </div>
            ) : filteredConversations.length === 0 ? (
              <div style={{ padding: 24, textAlign: "center", color: "#65676B", fontSize: 14 }}>
                {unreadOnly ? t("inbox.noUnread") : t("inbox.noMessages")}
                {!unreadOnly && (
                  <div style={{ marginTop: 8, fontSize: 12 }}>
                    {t("inbox.channelsHint")}{" "}
                    <a href="/channels" style={{ color: "#0866FF" }}>{t("inbox.channelsLink")}</a>
                  </div>
                )}
              </div>
            ) : (
              filteredConversations.map((conv) => {
                const isSelected = conv.lead_id === selectedLeadId;
                return (
                  <button
                    key={conv.lead_id}
                    type="button"
                    className={`conv-item conversation-item${isSelected ? " selected" : ""}`}
                    onClick={() => selectLead(conv.lead_id)}
                  >
                    {/* アバター */}
                    <div className="conv-avatar-wrap">
                      <div className="conv-avatar">
                        {getInitials(conv.customer_name)}
                      </div>
                      <div
                        className="conv-platform-dot"
                        style={{ background: platformGradient(conv.platform) }}
                      />
                    </div>

                    {/* 会話情報 */}
                    <div className="conv-info">
                      <div className="conv-header">
                        <span className="conv-name">
                          {conv.customer_name ?? conv.lead_code ?? `Lead #${conv.lead_id}`}
                        </span>
                        <span className="conv-time">{relativeTime(conv.last_message_at)}</span>
                      </div>
                      <div className="conv-preview">
                        {/* platform バッジ（E2E 検証 + アクセシビリティ） */}
                        {conv.platform && (
                          <span className="badge conv-platform-badge">
                            {platformLabel(conv.platform)}
                          </span>
                        )}
                        <span className={`conv-preview-text${conv.unread_count > 0 ? " unread" : ""}`}>
                          {conv.last_message_direction === "outbound" && (
                            <span style={{ opacity: 0.7 }}>You: </span>
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
            <div className="inbox-empty-center">
              <div className="inbox-empty-icon">💬</div>
              <p>{t("inbox.selectConversation")}</p>
            </div>
          ) : (
            <>
              {/* ヘッダ */}
              <header className="inbox-center-header">
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h2 className="inbox-center-title">
                    {messagesData?.lead?.customer_name
                      || selectedConversation?.customer_name
                      || `Lead #${selectedLeadId}`}
                  </h2>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
                    {messagesData?.lead?.lead_code && (
                      <span style={{ fontSize: 12, color: "#65676B" }}>
                        {messagesData.lead.lead_code}
                      </span>
                    )}
                    {selectedPlatform && (
                      <span
                        className="inbox-platform-badge"
                        style={
                          selectedPlatform === "messenger"
                            ? { background: "#E7F3FF", color: "#0866FF" }
                            : selectedPlatform === "instagram"
                              ? { background: "#FCE3F0", color: "#C13584" }
                              : { background: "#eee", color: "#555" }
                        }
                      >
                        {platformLabel(selectedPlatform)}
                      </span>
                    )}
                  </div>
                </div>
                <a
                  href={`/leads?lead_id=${selectedLeadId}`}
                  style={{
                    fontSize: 12,
                    color: "#0866FF",
                    textDecoration: "none",
                    padding: "4px 10px",
                    borderRadius: 12,
                    background: "#E7F3FF",
                    fontWeight: 600,
                    flexShrink: 0,
                  }}
                >
                  {t("inbox.lead")}
                </a>
              </header>

              {/* メッセージリスト */}
              <div ref={messageListRef} className="inbox-messages">
                {msgLoading && !messagesData && (
                  <div style={{ textAlign: "center", color: "#65676B", padding: 16 }}>
                    {t("common.loading")}
                  </div>
                )}
                {msgError && (
                  <div className="inbox-error-banner">{msgError}</div>
                )}
                {messagesData && messagesData.messages.length === 0 && !msgError && (
                  <div style={{ textAlign: "center", color: "#65676B", padding: 32 }}>
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
                          <div style={{ fontSize: 11, opacity: 0.85, marginBottom: 4, fontWeight: 600 }}>
                            {msg.message_tag === "HUMAN_AGENT" ? "Human Agent" : msg.message_tag}
                          </div>
                        )}
                        {failed && (
                          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
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
                <div className="inbox-send-row">
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
            </>
          )}
        </main>

        {/* ============================== 右パネル (商談カルテ) ============================== */}
        <aside className="inbox-right-panel">
          {selectedLeadId === null ? (
            <div className="right-panel-empty">
              <p>{t("inbox.selectConversation")}</p>
            </div>
          ) : leadDetail ? (
            <>
              {/* ヘッダー */}
              <div className="right-panel-header">
                <div className="right-panel-avatar">
                  {getInitials(leadDetail.customer_name)}
                </div>
                <h3 className="right-panel-name">{leadDetail.customer_name}</h3>
                {leadDetail.english_name && (
                  <p className="right-panel-en-name">{leadDetail.english_name}</p>
                )}
                <p className="right-panel-code">{leadDetail.lead_code}</p>
                <div className="right-panel-status">{leadDetail.status || "—"}</div>
                {leadDetail.prospect_rank && (
                  <div className={`right-panel-rank rank-${leadDetail.prospect_rank.replace("+", "plus")}`}>
                    ランク {leadDetail.prospect_rank}
                  </div>
                )}
              </div>

              {/* セクション1: 連絡先 */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionContact")}</div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.companyName")}</span>
                  <span className="right-panel-value">{leadDetail.company_name || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.email")}</span>
                  <span className="right-panel-value">{leadDetail.email || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.phone")}</span>
                  <span className="right-panel-value">{leadDetail.phone || "—"}</span>
                </div>
              </div>

              {/* セクション2: 商談情報 */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionDeal")}</div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.temperature")}</span>
                  <span className="right-panel-value">{leadDetail.temperature || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.estimatedScale")}</span>
                  <span className="right-panel-value">{leadDetail.estimated_scale || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.customerType")}</span>
                  <span className="right-panel-value">{leadDetail.customer_type || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.responseSpeed")}</span>
                  <span className="right-panel-value">{leadDetail.response_speed || "—"}</span>
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.monthlyForecast")}</span>
                  <span className="right-panel-value">
                    {leadDetail.monthly_forecast
                      ? `¥${Number(leadDetail.monthly_forecast).toLocaleString()}`
                      : "—"}
                  </span>
                </div>
                {leadDetail.per_order_amount && (
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.perOrderAmount")}</span>
                    <span className="right-panel-value">
                      ¥{Number(leadDetail.per_order_amount).toLocaleString()}
                    </span>
                  </div>
                )}
                {leadDetail.sales_form && (
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.salesForm")}</span>
                    <span className="right-panel-value">{leadDetail.sales_form}</span>
                  </div>
                )}
                {leadDetail.competitor_check !== null && (
                  <div className="right-panel-row">
                    <span className="right-panel-label">{t("leads.competitorCheck")}</span>
                    <span className="right-panel-value">
                      {leadDetail.competitor_check ? "✓ 済" : "未"}
                    </span>
                  </div>
                )}
              </div>

              {/* セクション3: 次回アクション */}
              {(leadDetail.next_action || leadDetail.next_action_date) && (
                <div className="right-panel-section">
                  <div className="right-panel-section-title">{t("inbox.sectionNextAction")}</div>
                  {leadDetail.next_action_date && (
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.nextActionDate")}</span>
                      <span className="right-panel-value">{leadDetail.next_action_date}</span>
                    </div>
                  )}
                  {leadDetail.next_action && (
                    <div className="right-panel-memo">{leadDetail.next_action}</div>
                  )}
                </div>
              )}

              {/* セクション4: 課題・ニーズ */}
              {leadDetail.challenge && (
                <div className="right-panel-section">
                  <div className="right-panel-section-title">{t("inbox.sectionChallenge")}</div>
                  <div className="right-panel-memo">{leadDetail.challenge}</div>
                </div>
              )}

              {/* セクション5: メモ */}
              {(leadDetail.notes || leadDetail.meeting_memo || leadDetail.cs_memo) && (
                <div className="right-panel-section">
                  <div className="right-panel-section-title">{t("inbox.sectionMemo")}</div>
                  {leadDetail.notes && (
                    <>
                      <div className="right-panel-memo-label">{t("leads.notes")}</div>
                      <div className="right-panel-memo">{leadDetail.notes}</div>
                    </>
                  )}
                  {leadDetail.meeting_memo && (
                    <>
                      <div className="right-panel-memo-label">{t("leads.meetingMemo")}</div>
                      <div className="right-panel-memo">{leadDetail.meeting_memo}</div>
                    </>
                  )}
                  {leadDetail.meeting_impression && (
                    <div className="right-panel-row">
                      <span className="right-panel-label">{t("leads.meetingImpression")}</span>
                      <span className="right-panel-value">{leadDetail.meeting_impression}</span>
                    </div>
                  )}
                  {leadDetail.cs_memo && (
                    <>
                      <div className="right-panel-memo-label">{t("leads.csMemo")}</div>
                      <div className="right-panel-memo">{leadDetail.cs_memo}</div>
                    </>
                  )}
                </div>
              )}

              <a href={`/leads?lead_id=${leadDetail.id}`} className="right-panel-link">
                {t("inbox.viewLead")} →
              </a>
            </>
          ) : (
            <div className="right-panel-empty">
              <p>{t("inbox.loadingProfile")}</p>
            </div>
          )}
        </aside>

        </div>{/* /inbox-columns */}
      </div>{/* /inbox-wrapper */}
    </>
  );
}
