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
import { NAV_ICONS, PAGE_ICONS, PlatformIcon, STATUS_ICONS } from "../constants/icons";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { ICON } from "../constants/iconSizes";
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
// プラットフォームタブ定数
// ---------------------------------------------------------------------------

const PLATFORM_TABS = [
  { key: "all",       labelKey: "inbox.tabAll" },
  { key: "messenger", labelKey: "inbox.tabMessenger" },
  { key: "instagram", labelKey: "inbox.tabInstagram" },
] as const;

// ---------------------------------------------------------------------------
// リードステータス分類定数
// ---------------------------------------------------------------------------

// フォローアップフィルターから除外するステータス（返信しても意味がない相手）
const FOLLOWUP_EXCLUDED = new Set(["失注", "対象外"]);

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

// Phase 1-E F24-S5: lib/messages.ts の libPlatformLabel に集約。後方互換のため alias 維持。
const platformLabel = libPlatformLabel;

// ---------------------------------------------------------------------------
// グローバルスタイル（<style> タグ経由で挿入）
// ---------------------------------------------------------------------------

const INBOX_STYLES = `
/* ======= Inbox Meta Design (ADR-063) ======= */

/* 全体ラッパー（flex row: 左＋中央エリア | 右パネル） */
.inbox-wrapper {
  display: flex;
  flex-direction: row;
  height: 100%;
  overflow: hidden;
  font-family: 'SF Pro Text', 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  background: transparent;
  /* Meta実測値でCSS変数をスコープ上書き（ライトモード） */
  --accent:         rgb(10, 120, 190);
  --link-active-bg: rgb(225, 237, 247);
  --text-primary:   rgb(28, 43, 51);
  --border:         rgb(218, 221, 225);
  --avatar-bg:      rgb(241, 244, 247);
  --indicator:      rgb(24, 118, 242);
}
/* ダークモード時は dark 値に戻す */
html.force-dark .inbox-wrapper {
  --accent:         #818cf8;
  --link-active-bg: #1e3a8a;
  --text-primary:   #f1f5f9;
  --border:         #334155;
  --avatar-bg:      #334155;
  --indicator:      #818cf8;
}

/* 左＋中央エリア（ヘッダー・タブ・カラム）— タブバーはここまで */
.inbox-main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

/* 受信箱タイトルエリア（seamless統合 — Meta風 / 背景透明でグラデーション透過） */
.inbox-area-header {
  padding: var(--space-4) var(--space-6) var(--space-2);
  flex-shrink: 0;
  background: transparent;
}
.inbox-area-title {
  font-size: var(--font-xl);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 2px;
  line-height: 1.2;
}
.inbox-area-subtitle {
  font-size: var(--font-sm);
  color: var(--text-muted);
  margin: 0;
}

/* 全幅タブバー（3カラムの上・コンテンツエリア全幅） — Meta実測: h=36, bg=transparent */
.inbox-full-tab-bar {
  display: flex;
  align-items: center;
  background: transparent;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 0 var(--space-2);
  height: 36px;
  box-sizing: border-box;
}
.inbox-full-tab-bar::-webkit-scrollbar { display: none; }
/* Meta実測: padding=8px 12px, border-radius=4px, font-size=14px, fw=400 */
.inbox-full-tab {
  height: 36px;
  padding: 0 var(--space-3);
  border: none;
  border-bottom: none;
  background: transparent;
  font-size: var(--font-base);
  font-weight: 400;
  color: var(--text-primary);
  cursor: pointer;
  white-space: nowrap;
  border-radius: var(--radius-sm);
  transition: background 0.1s, color 0.1s;
  font-family: inherit;
  display: flex;
  align-items: center;
  line-height: 1;
}
.inbox-full-tab:hover:not(.active) {
  background: rgba(0, 0, 0, 0.05);
  color: var(--accent);
}
/* Meta実測: active bg=link-active-bg, color=accent, fw=700 */
.inbox-full-tab.active {
  background: var(--link-active-bg);
  color: var(--accent);
  font-weight: 700;
}

/* 3カラムコンテンツエリア */
.inbox-columns {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ---- 左パネル ---- */
.inbox-left-panel {
  width: 443px;
  flex-shrink: 0;
  flex-grow: 0;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
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
  gap: var(--space-2);
  padding: var(--space-2) var(--space-10px) var(--space-1);
  flex-shrink: 0;
}
.inbox-search-input {
  flex: 1;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-pill);
  border: none;
  background: var(--bg-subtle);
  font-size: var(--font-base);
  color: var(--text-primary);
  outline: none;
  box-sizing: border-box;
}
.inbox-search-input::placeholder {
  color: var(--text-secondary);
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
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg-surface);
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
  white-space: nowrap;
}
.inbox-manage-btn:hover { background: var(--bg-subtle); }
.inbox-manage-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: 180px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  z-index: var(--z-topbar);
  overflow: hidden;
}
.inbox-manage-item {
  display: block;
  width: 100%;
  padding: var(--space-10px) var(--space-14px);
  border: none;
  background: transparent;
  text-align: left;
  font-size: var(--font-sm);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
}
.inbox-manage-item:hover { background: var(--bg-subtle); }

/* サブフィルターピル（Meta実測: 未読/フォローアップ） */
.inbox-sub-filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-3) var(--space-2);
  flex-shrink: 0;
}
/* Meta実測: 非アクティブ bg=transparent, color=rgb(28,43,51), fs=14px, fw=400, padding=8px 12px, br=4px */
.inbox-sub-filter-pill {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  border: none;
  font-size: var(--font-base);
  font-weight: 400;
  background: transparent;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
  font-family: inherit;
  white-space: nowrap;
  line-height: 1.5;
}
/* Meta実測: アクティブ bg=rgb(225,237,247), color=rgb(10,120,190), fw=700 */
.inbox-sub-filter-pill.active {
  background: var(--link-active-bg);
  color: var(--accent);
  font-weight: 700;
}
.inbox-sub-filter-pill:hover:not(.active) {
  background: rgba(0, 0, 0, 0.05);
}

/* 会話リスト */
.inbox-conversation-list {
  flex: 1;
  overflow-y: auto;
}

/* 会話アイテム — Meta実測: padding=12px 0 12px 12px, h=92px, borderなし */
.conv-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0 var(--space-3) var(--space-3);
  width: 100%;
  min-height: 92px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s;
  font-family: inherit;
  box-sizing: border-box;
  position: relative;
}
/* Meta実測: hover/selected = rgba(0,0,0,0.05) オーバーレイ */
.conv-item:hover { background: rgba(0, 0, 0, 0.05); }
.conv-item.selected { background: rgba(0, 0, 0, 0.05); }
/* 選択中インジケータ = 2px右端ストリップ */
.conv-item.selected::after {
  content: '';
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--indicator);
}

/* アバター */
.conv-avatar-wrap {
  position: relative;
  flex-shrink: 0;
}
.conv-avatar {
  width: var(--icon-xl);
  height: var(--icon-xl);
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-base);
  font-weight: 700;
  user-select: none;
}
.conv-platform-dot {
  position: absolute;
  bottom: -2px;
  right: -2px;
  width: var(--icon-base);
  height: var(--icon-base);
  border-radius: var(--radius-full);
  border: 2px solid var(--bg-surface);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  line-height: 0;
}

/* 会話情報 */
.conv-info { flex: 1; min-width: 0; }
.conv-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--space-6px);
}
/* 名前 14px/fw400(既読)/fw700(未読) */
.conv-name {
  font-size: var(--font-base);
  font-weight: 400;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-name.unread { font-weight: 700; }
/* 時刻 12px */
.conv-time {
  font-size: var(--font-xs);
  color: var(--text-muted);
  flex-shrink: 0;
}
.conv-preview {
  display: flex;
  align-items: center;
  gap: var(--space-6px);
  margin-top: var(--space-2px);
}
/* プレビュー 12px/fw400(既読) / fw700(未読) */
.conv-preview-text {
  font-size: var(--font-xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.conv-preview-text.unread {
  color: var(--text-primary);
  font-weight: 700;
}
.conv-unread-badge {
  background: var(--accent);
  color: var(--on-accent);
  border-radius: var(--radius-xl);
  padding: 1px 6px;
  font-size: var(--font-2xs);
  font-weight: 700;
  flex-shrink: 0;
}
.conv-platform-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  color: var(--text-secondary);
  flex-shrink: 0;
}

/* ---- 中央パネル ---- */
.inbox-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  min-width: 0;
}
/* Meta実測: padding=12px 0, border-bottom=1px solid rgba(203,210,217,0.6), h=81px */
.inbox-center-header {
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid rgba(203, 210, 217, 0.6);
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
  min-height: 81px;
  box-sizing: border-box;
}
.inbox-center-title {
  font-size: var(--font-md);
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
}
.inbox-platform-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: var(--radius-xl);
  font-size: var(--font-2xs);
  font-weight: 600;
}
.inbox-messages {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.inbox-msg-row { display: flex; }
.inbox-msg-row.outbound { justify-content: flex-end; }
.inbox-msg-row.inbound { justify-content: flex-start; }
/* Meta実測: バブル 16px / padding=8px 12px */
.msg-bubble {
  max-width: 70%;
  padding: var(--space-2) var(--space-3);
  font-size: var(--font-md);
  line-height: 1.45;
  word-break: break-word;
  white-space: pre-wrap;
}
/* outbound バブル */
.msg-bubble.outbound {
  background: var(--bubble-outbound-bg);
  color: var(--on-accent);
  border-radius: 20.8px;
}
/* inbound バブル */
.msg-bubble.inbound {
  background: var(--bubble-inbound-bg);
  color: var(--text-primary);
  border-radius: 20.8px 20.8px 20.8px 4.8px;
}
.msg-bubble.failed {
  background: var(--danger-bg);
  color: var(--danger-text);
  border: 2px solid var(--danger);
  border-radius: var(--radius-xl);
}
.msg-time {
  font-size: var(--font-2xs);
  opacity: 0.7;
  margin-top: var(--space-1);
  text-align: right;
}
.msg-time.inbound { text-align: left; }

/* 送信エリア — Meta実測: 白角丸カード(br=8px) + 左側に送信者アバター */
.inbox-send-area {
  padding: 4px 12px 12px;
  flex-shrink: 0;
  background: var(--bg-surface);
}
/* 白い角丸ボックス（Meta実測: bg=white, br=8px, border=1px solid border-color） */
.send-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* 上段: 送信者アバター + 入力エリア */
.send-top-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: 10px 10px 6px;
}
/* 入力ラップ（Meta実測: br=18px → --radius-pill=20px 吸収済み ±2px許容） */
.send-input-wrap {
  flex: 1;
  min-width: 0;
  background: var(--bg-subtle);
  border-radius: var(--radius-pill);
  padding: var(--space-2) var(--space-14px);
  box-sizing: border-box;
}
.inbox-textarea {
  width: 100%;
  border: none;
  padding: 0;
  font-size: var(--font-base);
  resize: none;
  font-family: inherit;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  box-sizing: border-box;
  line-height: 1.4;
}
.inbox-textarea:disabled { cursor: not-allowed; opacity: 0.6; }
/* 下段: 送信ボタン */
.send-bottom-row {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding: 0 var(--space-10px) var(--space-10px);
}
.inbox-send-btn {
  padding: var(--space-2) var(--space-5);
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--on-accent);
  border: none;
  font-size: var(--font-base);
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: background 0.1s;
}
.inbox-send-btn:hover:not(:disabled) { background: var(--accent-hover); }
.inbox-send-btn:disabled {
  background: var(--bg-active);
  color: var(--text-secondary);
  cursor: not-allowed;
}

/* 空状態 */
.inbox-empty-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  font-size: var(--font-base);
  gap: var(--space-3);
}
.inbox-empty-icon svg { width: var(--icon-xl); height: var(--icon-xl); }

/* ---- 右パネル ---- */
.inbox-right-panel {
  width: var(--drawer-width);
  flex-shrink: 0;
  flex-grow: 0;
  background: var(--bg-surface);
  border-left: 1px solid var(--inbox-separator);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

/* カルテカード（右パネル内 — Metaに合わせフラット構成） */
.right-panel-card {
  background: var(--bg-surface);
  width: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  align-items: center;
}
/* Meta実測: 右パネルアバター 52×52px */
.right-panel-avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-xl);
  font-weight: 700;
  margin-bottom: var(--space-2);
  user-select: none;
}
.right-panel-name {
  font-size: var(--font-lg);
  font-weight: 700;
  color: var(--text-primary);
  text-align: center;
  margin: 0;
}
.right-panel-code {
  font-size: var(--font-xs);
  color: var(--text-secondary);
  margin-top: var(--space-1);
  text-align: center;
}
.right-panel-status {
  margin-top: var(--space-10px);
  padding: var(--space-1) var(--space-14px);
  border-radius: var(--radius-pill);
  background: var(--link-active-bg);
  color: var(--accent);
  font-size: var(--font-xs);
  font-weight: 600;
}
/* Meta実測: セクションはフラット — border-bottom 線区切りのみ、カードなし */
.right-panel-section {
  background: transparent;
  border-bottom: 1px solid var(--border);
  padding: var(--space-4) var(--space-3);
  box-sizing: border-box;
  width: 100%;
}
.right-panel-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-2px);
  padding: var(--space-10px) 0;
  border-bottom: 1px solid var(--bg-subtle);
}
.right-panel-label {
  font-size: var(--font-2xs);
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.02em;
}
.right-panel-value {
  font-size: var(--font-sm);
  color: var(--text-primary);
  font-weight: 500;
  word-break: break-word;
}
/* プロフィールを見る */
.right-panel-link {
  margin: var(--space-3) 0 var(--space-4);
  display: inline-block;
  padding: 0;
  border-radius: 0;
  background: transparent;
  color: var(--link);
  font-size: var(--font-base);
  font-weight: 400;
  text-decoration: none;
  transition: opacity 0.1s;
}
.right-panel-link:hover { opacity: 0.75; }
.right-panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  font-size: var(--font-base);
  text-align: center;
  padding: var(--space-4);
}

/* ヘッダーラッパー */
.right-panel-header {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--space-4) var(--space-3);
  box-sizing: border-box;
}

/* カード化により隣接セレクタ不要（削除済み） */

/* 英語名 */
.right-panel-en-name {
  font-size: var(--font-2xs);
  color: var(--text-secondary);
  margin: 2px 0 0;
  text-align: center;
}

/* 見込度バッジ */
.right-panel-rank {
  margin-top: 6px;
  padding: 3px 12px;
  border-radius: var(--radius-pill);
  font-size: var(--font-2xs);
  font-weight: 700;
  background: var(--rank-bg);
  color: var(--rank-text);
}

/* セクションタイトル */
.right-panel-section-title {
  font-size: var(--font-md);
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 10px;
  padding-bottom: 0;
}

/* 長文メモ */
.right-panel-memo {
  font-size: var(--font-xs);
  color: var(--text-primary);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg-subtle);
  border-radius: var(--radius-md);
  padding: 8px 10px;
  margin-top: var(--space-1);
  margin-bottom: 6px;
}

/* メモ内サブラベル */
.right-panel-memo-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-top: 8px;
}

/* エラー・ローディング */
.inbox-error-banner {
  padding: var(--space-2) var(--space-3);
  background: var(--danger-bg);
  color: var(--danger-text);
  border: 1px solid var(--danger);
  border-radius: var(--radius-lg);
  font-size: var(--font-sm);
  margin: 8px 12px;
}
.inbox-send-error {
  padding: 6px 10px;
  border-radius: var(--radius-lg);
  background: var(--danger-bg);
  color: var(--danger-text);
  border: 1px solid var(--danger);
  font-size: var(--font-xs);
  margin-bottom: 6px;
}

/* ============================================================
   レスポンシブ対応
   --breakpoint-lg: 1024px / --breakpoint-md: 768px / --breakpoint-sm: 480px
   ============================================================ */

/* タブレット横（1024px以下）: 3カラム → 比率指定に変更 */
@media (max-width: 1024px) {
  .inbox-left-panel  { width: 35%; min-width: 220px; }
  .inbox-right-panel { width: 25%; min-width: 180px; }
}

/* タブレット縦・スマートフォン横（768px以下）: 縦積みレイアウト */
@media (max-width: 768px) {
  .inbox-wrapper {
    flex-direction: column;
    overflow-x: hidden;
    overflow-y: auto;
  }
  /* HIGH-1修正: 子要素のoverflow:hiddenが縦スクロールを塞ぐため解除 */
  .inbox-main-area { overflow: visible; }
  .inbox-columns   { flex-direction: column; overflow: visible; }

  .inbox-left-panel {
    width: 100%;
    max-height: 40vh;
    flex-shrink: 0;
    border-right: none;
    border-bottom: 1px solid var(--border);
    overflow-y: auto;
  }
  .inbox-center {
    width: 100%;
    flex: 1;
    min-height: 300px;
  }
  .inbox-right-panel {
    width: 100%;
    max-height: 35vh;
    flex-shrink: 0;
    border-left: none;
    border-top: 1px solid var(--border);
    overflow-y: auto;
  }
  .msg-bubble { max-width: 85%; }
}

/* スマートフォン縦（480px以下）: 右パネル非表示・余白縮小 */
@media (max-width: 480px) {
  .inbox-area-header { padding: var(--space-2) var(--space-3) var(--space-1); }
  .inbox-search-row  { padding: var(--space-2) var(--space-2) var(--space-1); }
  .inbox-left-panel  { max-height: 45vh; }
  .inbox-right-panel { display: none; }
  .msg-bubble { max-width: 90%; }
  .inbox-send-btn { padding: var(--space-2) var(--space-4); }
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
  const [platformTab, setPlatformTab] = useState<string>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [followUpOnly, setFollowUpOnly] = useState(false);
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
        platform: platformTab === "all" ? undefined : platformTab as PlatformFilter,
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
  }, [platformTab, unreadOnly, pageIdFilter]);

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
        // 対象外を常に非表示（LeadsPage のアーカイブタブで確認）
        return c.lead_status !== "対象外";
      })
      .filter((c) => {
        if (!unreadOnly) return true;
        return (c.unread_count ?? 0) > 0;
      })
      .filter((c) => {
        if (!followUpOnly) return true;
        // 顧客が最後にメッセージを送った会話（返信待ち）、かつ失注/対象外は除外
        return c.last_message_direction === "inbound"
          && !FOLLOWUP_EXCLUDED.has(c.lead_status ?? "");
      })
      .filter((c) => {
        if (!searchQuery) return true;
        const q = searchQuery.toLowerCase();
        return (
          (c.customer_name ?? "").toLowerCase().includes(q) ||
          (c.last_message_text ?? "").toLowerCase().includes(q)
        );
      });
  }, [conversations, unreadOnly, followUpOnly, searchQuery]);

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
        {/* 左+中央エリア（ヘッダー+タブ+カラム） */}
        <div className="inbox-main-area">

        {/* 受信箱タイトル（seamless統合 — Meta風） */}
        <div className="inbox-area-header">
          <h1 className="inbox-area-title">{t("inbox.title")}</h1>
          <p className="inbox-area-subtitle">{t("inbox.subtitle")}</p>
        </div>

        {/* プラットフォームタブバー（全幅） */}
        <div className="inbox-full-tab-bar">
          {PLATFORM_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={`inbox-full-tab${platformTab === tab.key ? " active" : ""}`}
              onClick={() => setPlatformTab(tab.key)}
            >
              {t(tab.labelKey)}
            </button>
          ))}
        </div>

        {/* 3カラムコンテンツ */}
        <div className="inbox-columns">

        {/* ============================== 左パネル ============================== */}
        <aside className="inbox-left-panel">
          {/* アクセシビリティ用タイトル（視覚的・意味論的に非表示：h1が全幅ヘッダーに移動済み） */}
          <h2 className="inbox-panel-title" aria-hidden="true">{t("inbox.title")}</h2>

          {/* 検索 + 管理ボタン + ユーティリティ（topbar移設分） */}
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
                <NAV_ICONS.filter size={13} />
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
            <div style={{ padding: "4px 12px 6px" }}>
              <select
                value={pageIdFilter}
                onChange={(e) => onPageFilterChange(e.target.value)}
                aria-label="Filter by Page"
                style={{
                  width: "100%",
                  padding: "4px 8px",
                  fontSize: "var(--font-xs)",
                  borderRadius: 16,
                  border: "1px solid var(--border)",
                  background: "var(--bg-surface)",
                  color: "var(--text-primary)",
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
                      <span className="conv-platform-dot">
                        <PlatformIcon platform={conv.platform} size={18} />
                      </span>
                    </div>

                    {/* 会話情報 */}
                    <div className="conv-info">
                      <div className="conv-header">
                        <span className={`conv-name${(conv.unread_count ?? 0) > 0 ? " unread" : ""}`}>
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
              <div className="inbox-empty-icon" aria-hidden="true">
                <PAGE_ICONS.inboxEmpty size={ICON.xl} />
              </div>
              <p>{t("inbox.selectConversation")}</p>
            </div>
          ) : (
            <>
              {/* ヘッダ */}
              <header className="inbox-center-header">
                {/* Meta実測: ヘッダーアバター 48×48px 円形 */}
                <div className="conv-avatar" style={{ flexShrink: 0 }}>
                  {getInitials(
                    messagesData?.lead?.customer_name
                    || selectedConversation?.customer_name
                  )}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h2 className="inbox-center-title">
                    {messagesData?.lead?.customer_name
                      || selectedConversation?.customer_name
                      || `Lead #${selectedLeadId}`}
                  </h2>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-2px)" }}>
                    {messagesData?.lead?.lead_code && (
                      <span style={{ fontSize: "var(--font-xs)", color: "var(--text-secondary)" }}>
                        {messagesData.lead.lead_code}
                      </span>
                    )}
                    {selectedPlatform && (
                      <span
                        className="inbox-platform-badge"
                        style={
                          selectedPlatform === "messenger"
                            ? { background: "var(--link-active-bg)", color: "var(--accent)" }
                            : selectedPlatform === "instagram"
                              ? { background: "var(--instagram-bg)", color: "var(--instagram-text)" }
                              : { background: "var(--bg-subtle)", color: "var(--text-secondary)" }
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
                    fontSize: "var(--font-xs)",
                    color: "var(--accent)",
                    textDecoration: "none",
                    padding: "var(--space-1) var(--space-10px)",
                    borderRadius: "var(--radius-xl)",
                    background: "var(--link-active-bg)",
                    fontWeight: "var(--font-weight-semi)",
                    flexShrink: 0,
                  }}
                >
                  {t("inbox.lead")}
                </a>
              </header>

              {/* メッセージリスト */}
              <div ref={messageListRef} className="inbox-messages">
                {msgLoading && !messagesData && (
                  <div style={{ textAlign: "center", color: "var(--text-secondary)", padding: "var(--space-4)" }}>
                    {t("common.loading")}
                  </div>
                )}
                {msgError && (
                  <div className="inbox-error-banner">{msgError}</div>
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
                          <div style={{ fontSize: "var(--font-2xs)", opacity: 0.85, marginBottom: "var(--space-1)", fontWeight: "var(--font-weight-semi)" }}>
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

        {/* ============================== 右パネル (商談カルテ) ============================== */}
        <aside className="inbox-right-panel">
          {selectedLeadId === null ? (
            <div className="right-panel-empty">
              <p>{t("inbox.selectConversation")}</p>
            </div>
          ) : leadDetail ? (
            <div className="right-panel-card">
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
                    {t("leads.rank")} {leadDetail.prospect_rank}
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
                      {leadDetail.competitor_check
                        ? <><STATUS_ICONS.check size={ICON.sm} aria-hidden="true" />{" "}{t("leads.competitorDone")}</>
                        : t("leads.competitorNotDone")}
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
            </div>
          ) : (
            <div className="right-panel-empty">
              <p>{t("inbox.loadingProfile")}</p>
            </div>
          )}
        </aside>

      </div>{/* /inbox-wrapper */}
    </>
  );
}
