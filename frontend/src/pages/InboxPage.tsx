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
import { useInboxSSE } from "../hooks/useInboxSSE";
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

const POLL_INTERVAL_MS = 30_000;
const POLL_MAX_INTERVAL_MS = 300_000;
const POLL_BACKOFF_FACTOR = 2;

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
  padding-left: var(--space-6);  /* 他ページと同じ 24px 左余白 */
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
  padding: var(--space-4) var(--space-6) 0 0;  /* 左は wrapper の 24px に委譲、下余白は .page-subtitle に委譲 */
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

/* 全幅タブバー（3カラムの上・コンテンツエリア全幅） */
.inbox-full-tab-bar {
  display: flex;
  align-items: center;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 0 var(--space-2);
  height: var(--height-tab-bar);
  box-sizing: border-box;
}
.inbox-full-tab-bar::-webkit-scrollbar { display: none; }
/* タブボタン: 54pxバー内で36px高さ（中央寄せ） */
.inbox-full-tab {
  height: var(--height-tab-item);
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
  transition: background var(--transition-micro), color var(--transition-micro);
  font-family: inherit;
  display: flex;
  align-items: center;
  line-height: 1;
}
.inbox-full-tab:hover:not(.active) {
  background: var(--color-hover-overlay);
  color: var(--accent);
}
/* active bg=link-active-bg, color=accent, fw=700 */
.inbox-full-tab.active {
  background: var(--link-active-bg);
  color: var(--accent);
  font-weight: 700;
  border-radius: var(--radius-md);
}

/* 3カラムコンテンツエリア */
.inbox-columns {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* ---- 左パネル ---- */
.inbox-left-panel {
  width: var(--width-inbox-panel);
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
  transition: background var(--transition-micro);
  white-space: nowrap;
}
.inbox-manage-btn:hover { background: var(--bg-subtle); }
.inbox-manage-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  min-width: var(--min-width-dropdown);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-dropdown);
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
  transition: background var(--transition-micro);
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
  transition: background var(--transition-micro), color var(--transition-micro);
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
  background: var(--color-hover-overlay);
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
  min-height: var(--min-height-conv-item);
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-micro);
  font-family: inherit;
  box-sizing: border-box;
  position: relative;
}
/* Meta実測: hover/selected = rgba(0,0,0,0.05) オーバーレイ */
.conv-item:hover { background: var(--color-hover-overlay); }
.conv-item.selected { background: var(--color-hover-overlay); }
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
  font-size: var(--font-2xs);
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
  border-bottom: 1px solid var(--color-separator-subtle);
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
  padding: var(--space-2px) var(--space-2);
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
  opacity: var(--opacity-muted);
  margin-top: var(--space-1);
  text-align: right;
}
.msg-time.inbound { text-align: left; }

/* 送信エリア — Meta実測: 白角丸カード(br=8px) + 左側に送信者アバター */
.inbox-send-area {
  padding: var(--space-1) var(--space-3) var(--space-3);
  flex-shrink: 0;
  background: var(--bg-surface);
}
/* 白い角丸ボックス（Meta実測: bg=white, br=8px → 12px に拡大） */
.send-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
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
.inbox-textarea:disabled { cursor: not-allowed; opacity: var(--opacity-disabled); }
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
  transition: background var(--transition-micro);
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
  margin-left: var(--space-14px);
  margin-right: var(--space-6);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  border-top-left-radius: var(--radius-sm);
  border-top-right-radius: var(--radius-sm);
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
/* Meta実測: 右パネルアバター 40×40px（コンパクトヘッダー用） */
.right-panel-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--font-base);
  font-weight: 700;
  flex-shrink: 0;
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
  transition: opacity var(--transition-micro);
}
.right-panel-link:hover { opacity: var(--opacity-hover); }
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
  font-size: var(--font-2xs);
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
   ブレークポイント定義: constants/breakpoints.ts / tokens.css を参照

   [3段階]
   モバイル     : max-width: 767px   スマートフォン  (未実装・スタブのみ)
   タブレット   : 768px-1023px       タブレット縦/横 (カルテをドロワーに)
   デスクトップ : min-width: 1024px  ノートPC以上   (カルテ常時表示)
   ============================================================ */

/* デスクトップ直下（<=1023px）: 3カラム → 比率指定に変更 */
/* タブレット + モバイル共通。カルテドロワーは下の @media ブロックで定義 */
@media (max-width: 1023px) {
  .inbox-left-panel  { width: 35%; min-width: 220px; }
  .inbox-right-panel { width: 25%; min-width: 180px; }
}

/* モバイル専用（<=767px）: スマートフォンレイアウト */
/* TODO: スマホ専用レイアウト実装予定（現在はタブレットと同じドロワー挙動）*/
@media (max-width: 767px) {
  /* 実装時にここに追加する */
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
  .inbox-wrapper    { padding-left: var(--space-3); }  /* モバイルは 12px に縮小 */
  .inbox-area-header { padding: var(--space-2) var(--space-3) var(--space-1) 0; }
  .inbox-search-row  { padding: var(--space-2) var(--space-2) var(--space-1); }
  .inbox-left-panel  { max-height: 45vh; }
  .inbox-right-panel { display: none; }
  .msg-bubble { max-width: 90%; }
  .inbox-send-btn { padding: var(--space-2) var(--space-4); }
}

/* ====== モバイル: カルテ ドロワー ====== */
/* デフォルト（デスクトップ）では非表示 */
.karte-toggle-btn { display: none; }
.karte-close-row  { display: none; }
.karte-overlay    { display: none; }

/* タブレット・スマートフォン（≤1024px）: ドロワー方式に切り替え */
@media (max-width: 1024px) {
  /* 「カルテ」トグルボタン: 会話ヘッダーに表示 */
  .karte-toggle-btn {
    display: flex; align-items: center; gap: var(--space-1);
    background: var(--link-active-bg); border: none;
    border-radius: var(--radius-xl);
    padding: var(--space-1) var(--space-10px);
    font-size: var(--font-xs); color: var(--accent);
    font-weight: var(--font-weight-semi); cursor: pointer; flex-shrink: 0;
    transition: opacity var(--transition-micro);
  }
  .karte-toggle-btn:hover { opacity: var(--opacity-dim); }

  /* 右パネルをフルハイト固定オーバーレイに変換 */
  .inbox-right-panel {
    position: fixed !important;
    top: 0; right: 0; bottom: 0;
    width: 360px !important; max-width: 92vw !important;
    max-height: none !important;
    margin: 0 !important;
    border-left: 1px solid var(--border) !important;
    border-top: none !important; border-radius: 0 !important;
    z-index: var(--z-drawer);
    transform: translateX(100%);
    transition: transform var(--transition-slow);
    box-shadow: var(--shadow-xl);
  }
  .inbox-right-panel.karte-open {
    transform: translateX(0);
  }

  /* バックドロップ: パネル背後の半透明オーバーレイ */
  .karte-overlay {
    display: block;
    position: fixed; inset: 0;
    z-index: var(--z-backdrop);
    background: rgba(0, 0, 0, 0.4);
    animation: fadeIn var(--duration-base) ease;
  }

  /* パネル上部の閉じるボタン行 */
  .karte-close-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: var(--space-3) var(--space-3) var(--space-2);
    border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .karte-close-title {
    font-size: var(--font-sm); font-weight: 600; color: var(--text-primary);
  }
  .karte-close-btn {
    display: flex; align-items: center; justify-content: center;
    background: none; border: none; cursor: pointer;
    color: var(--text-muted); border-radius: var(--radius-sm);
    padding: var(--space-1);
    transition: color var(--transition-micro), background var(--transition-micro);
  }
  .karte-close-btn:hover { color: var(--text-primary); background: var(--bg-hover); }
}

/* ====== カルテ常時編集フィールド ====== */
.right-panel-field {
  width: 100%; box-sizing: border-box;
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2);
  font-size: var(--font-sm); color: var(--text-primary);
  font-family: inherit;
  transition: border-color var(--transition-micro);
}
.right-panel-field:focus { outline: none; border-color: var(--accent); }
textarea.right-panel-field { resize: vertical; min-height: 60px; }
.right-panel-name-field {
  font-weight: 600; font-size: var(--font-base); text-align: center;
  border: 1px solid transparent; background: transparent;
}
.right-panel-name-field:hover,
.right-panel-name-field:focus { background: var(--bg-primary); border-color: var(--border); }
.right-panel-en-name-field {
  font-size: var(--font-xs); color: var(--text-muted); text-align: center;
  border: 1px solid transparent; background: transparent;
}
.right-panel-en-name-field:hover,
.right-panel-en-name-field:focus { background: var(--bg-primary); border-color: var(--border); }
.right-panel-save-indicator {
  font-size: var(--font-xs); color: var(--text-muted);
  min-height: 16px; text-align: right; padding: 0 var(--space-3);
  margin-bottom: var(--space-1);
}
.right-panel-save-indicator .saved { color: var(--success-bg); }
.right-panel-save-indicator .error  { color: var(--danger-bg); }

/* ====== 受信箱タイトル行（ギアアイコン） ====== */
.inbox-area-title-row {
  display: flex; align-items: center; gap: var(--space-2);
}
.inbox-settings-btn {
  display: flex; align-items: center; justify-content: center;
  background: none; border: none; cursor: pointer;
  color: var(--text-muted); border-radius: var(--radius-sm);
  padding: var(--space-1);
  transition: color var(--transition-micro), background var(--transition-micro);
}
.inbox-settings-btn:hover { color: var(--text-primary); background: var(--bg-hover); }

/* ====== 受信箱設定モーダル ====== */
.inbox-settings-overlay {
  position: fixed; inset: 0; z-index: var(--z-modal);
  background: rgba(0,0,0,var(--opacity-overlay));
  display: flex; align-items: center; justify-content: center;
}
.inbox-settings-modal {
  background: var(--bg-surface); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: var(--space-6);
  min-width: 320px; max-width: 480px; width: 90%;
  box-shadow: var(--shadow-lg);
}
.inbox-settings-modal-title {
  font-size: var(--font-lg); font-weight: 600; color: var(--text-primary);
  margin: 0 0 var(--space-4);
}
.inbox-settings-section-title {
  font-size: var(--font-xs); font-weight: 600; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: 0.05em;
  margin-bottom: var(--space-2);
}
.inbox-settings-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--space-2) 0; border-bottom: 1px solid var(--border);
}
.inbox-settings-label { font-size: var(--font-sm); color: var(--text-primary); }
.inbox-settings-select {
  background: var(--bg-primary); border: 1px solid var(--border);
  border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2);
  font-size: var(--font-sm); color: var(--text-primary);
  cursor: pointer;
}
.inbox-settings-close-btn {
  margin-top: var(--space-5); width: 100%;
  background: var(--accent); color: var(--on-accent);
  border: none; border-radius: var(--radius-sm); padding: var(--space-2) var(--space-4);
  font-size: var(--font-sm); font-weight: 500; cursor: pointer;
  transition: opacity var(--transition-micro);
}
.inbox-settings-close-btn:hover { opacity: var(--opacity-dim); }

/* ====== トグルスイッチ ====== */
.inbox-toggle { position: relative; display: inline-flex; width: 40px; height: 22px; cursor: pointer; }
.inbox-toggle input { opacity: 0; width: 0; height: 0; }
.inbox-toggle-slider {
  position: absolute; inset: 0;
  background: var(--border); border-radius: 11px;
  transition: background var(--transition-micro);
}
.inbox-toggle-slider::before {
  content: ""; position: absolute;
  height: 16px; width: 16px; left: 3px; top: 3px;
  background: var(--bg-surface); border-radius: 50%;
  transition: transform var(--transition-micro);
}
.inbox-toggle input:checked + .inbox-toggle-slider { background: var(--accent); }
.inbox-toggle input:checked + .inbox-toggle-slider::before { transform: translateX(18px); }
`;

// ---------------------------------------------------------------------------
// 受信箱設定 (localStorage)
// ---------------------------------------------------------------------------

const INBOX_SETTINGS_KEY = "inbox_settings";
const DRAFT_KEY = (leadId: number) => `cartedit_draft_${leadId}`;

interface InboxSettings {
  showRightPanel: boolean;
  defaultTab: "all" | "messenger" | "instagram";
  defaultUnreadOnly: boolean;
  browserNotifications: boolean;
  soundEnabled: boolean;
}

const DEFAULT_INBOX_SETTINGS: InboxSettings = {
  showRightPanel: true,
  defaultTab: "all",
  defaultUnreadOnly: false,
  browserNotifications: false,
  soundEnabled: false,
};

function readInboxSettings(): InboxSettings {
  try {
    const raw = localStorage.getItem(INBOX_SETTINGS_KEY);
    return raw ? { ...DEFAULT_INBOX_SETTINGS, ...JSON.parse(raw) } : DEFAULT_INBOX_SETTINGS;
  } catch {
    return DEFAULT_INBOX_SETTINGS;
  }
}

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

  // 受信箱設定
  const [inboxSettings, setInboxSettings] = useState<InboxSettings>(readInboxSettings);
  const [showSettings, setShowSettings] = useState(false);

  // フィルタ（設定のデフォルト値を反映）
  const [platformTab, setPlatformTab] = useState<string>(() => readInboxSettings().defaultTab);
  const [unreadOnly, setUnreadOnly] = useState(() => readInboxSettings().defaultUnreadOnly);
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
  const [cardForm, setCardForm] = useState<Partial<LeadDetail>>({});
  const [cardSaveStatus, setCardSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [cardSaveError, setCardSaveError] = useState("");
  // モバイル時のドロワー開閉（デスクトップ>1024pxでは常時表示のため無視）
  const [showKartePanel, setShowKartePanel] = useState(false);

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
  const pollErrorCountRef = useRef(0);
  // 502/503/ネットワークエラーの連続発生カウント（1回目は抑制、2回目以降にバナー表示）
  const transientErrorCountRef = useRef(0);

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
      transientErrorCountRef.current = 0; // 成功したら一時エラーカウントをリセット
    } catch (e) {
      // タイムアウトによるキャンセルはポーリング中の一時的な中断なのでバナーを出さない
      if (e instanceof Error && e.name === "AbortError") return;

      // 502/503（デプロイ直後の起動中）やネットワークエラーは一時的なインフラ障害として扱う
      // 1回目は黙って再試行（デプロイ29秒ウィンドウをユーザーに見せない）
      // 2回目以降の連続エラーはバナー表示（本物の障害として通知）
      const isTransient =
        (e instanceof ApiError && (e.status === 502 || e.status === 503)) ||
        (e instanceof TypeError) ||
        (e instanceof Error && /^HTTP 50[23]/.test(e.message));

      if (isTransient) {
        transientErrorCountRef.current += 1;
        console.warn(`[InboxPage] transient error #${transientErrorCountRef.current}:`, e instanceof Error ? e.message : e);
        if (transientErrorCountRef.current < 2) return; // 1回目は抑制
        // 2回目以降は本物の障害としてバナー表示
      } else {
        transientErrorCountRef.current = 0;
      }

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
      // localStorage に下書きがあれば黙って復元（Notion方式）
      try {
        const raw = localStorage.getItem(DRAFT_KEY(leadId));
        if (raw) {
          const draft = JSON.parse(raw) as Partial<LeadDetail>;
          setCardForm({ ...data, ...draft });
        } else {
          setCardForm({ ...data });
        }
      } catch {
        setCardForm({ ...data });
      }
    } catch {
      setLeadDetail(null);
      setCardForm({});
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
  // カルテ編集ハンドラー（常時編集 + blur保存 + Notionキャッシュ）
  // ---------------------------------------------------------------------------

  const handleCardFieldChange = useCallback((field: keyof LeadDetail, value: unknown) => {
    setCardForm((prev) => {
      const next = { ...prev, [field]: value };
      if (leadDetail) {
        try {
          localStorage.setItem(DRAFT_KEY(leadDetail.id), JSON.stringify(next));
        } catch { /* quota超過時は無視 */ }
      }
      return next;
    });
  }, [leadDetail]);

  const handleCardFieldBlur = useCallback(async () => {
    if (!leadDetail) return;
    setCardSaveStatus("saving");
    setCardSaveError("");
    try {
      const payload = Object.fromEntries(
        Object.entries(cardForm)
          .filter(([k]) => k !== "id" && k !== "lead_code" && k !== "prospect_rank")
          .map(([k, v]) => [k, v === "" ? null : v])
      );
      const updated = await api.patch<LeadDetail>(`/leads/${leadDetail.id}`, payload);
      setLeadDetail(updated);
      setCardForm({ ...updated });
      localStorage.removeItem(DRAFT_KEY(leadDetail.id));
      setCardSaveStatus("saved");
      setTimeout(() => setCardSaveStatus((s) => s === "saved" ? "idle" : s), 2000);
    } catch (e) {
      setCardSaveStatus("error");
      setCardSaveError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  }, [leadDetail, cardForm]);

  const updateInboxSetting = useCallback(<K extends keyof InboxSettings>(key: K, value: InboxSettings[K]) => {
    setInboxSettings((prev) => {
      const next = { ...prev, [key]: value };
      localStorage.setItem(INBOX_SETTINGS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  // ---------------------------------------------------------------------------
  // 初回 + filter 変更時の会話リスト取得
  // ---------------------------------------------------------------------------

  useEffect(() => {
    setConvLoading(true);
    loadConversations();
  }, [loadConversations]);

  // ---------------------------------------------------------------------------
  // Phase 2 SSE: 新着通知受信 → 即時 loadConversations()
  // ポーリング useEffect は継続（SSE 失敗時のフォールバック）
  // ---------------------------------------------------------------------------

  useInboxSSE({
    onUpdate: useCallback(() => {
      skipNextPollRef.current = true; // SSE 受信直後のポーリングによる二重ロードを防止
      loadConversations();
      if (selectedLeadId !== null) loadMessages(selectedLeadId);
    }, [loadConversations, loadMessages, selectedLeadId]),
  });

  // ---------------------------------------------------------------------------
  // ポーリング（指数バックオフ付き）
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    const schedule = (delay: number): ReturnType<typeof setTimeout> => {
      return setTimeout(async () => {
        if (cancelled) return;
        if (skipNextPollRef.current) {
          skipNextPollRef.current = false;
        } else {
          try {
            await loadConversations();
            if (selectedLeadId !== null) await loadMessages(selectedLeadId);
            pollErrorCountRef.current = 0;
          } catch (err) {
            // AbortError 以外のエラーをカウント（バックオフ計算に使用）
            if (!(err instanceof Error && err.name === "AbortError")) {
              pollErrorCountRef.current += 1;
            }
          }
        }
        if (!cancelled) {
          const nextDelay = Math.min(
            POLL_INTERVAL_MS * Math.pow(POLL_BACKOFF_FACTOR, pollErrorCountRef.current),
            POLL_MAX_INTERVAL_MS,
          );
          schedule(nextDelay);
        }
      }, delay);
    };

    const timerId = schedule(POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timerId);
    };
  }, [loadConversations, loadMessages, selectedLeadId]);

  // ---------------------------------------------------------------------------
  // lead 選択時 → メッセージ取得 + 既読化 + URL 更新 + 右パネル
  // ---------------------------------------------------------------------------

  const selectLead = useCallback((leadId: number) => {
    setSelectedLeadId(leadId);
    setShowKartePanel(false); // モバイルドロワーはリード切替時に閉じる
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
          <div className="inbox-area-title-row">
            <h1 className="inbox-area-title">{t("nav.leadChat")}</h1>
            <button
              type="button"
              className="inbox-settings-btn"
              onClick={() => setShowSettings(true)}
              aria-label={t("inbox.settings.title")}
            >
              <NAV_ICONS.settings size={ICON.md} aria-hidden="true" />
            </button>
          </div>
          <p className="page-subtitle">{t("inbox.subtitle")}</p>
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
          <h2 className="inbox-panel-title" aria-hidden="true">{t("nav.leadChat")}</h2>

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
                  borderRadius: "var(--radius-xl)",
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
                {/* モバイル専用カルテトグルボタン（デスクトップでは CSS で非表示） */}
                {inboxSettings.showRightPanel && (
                  <button
                    type="button"
                    className="karte-toggle-btn"
                    onClick={() => setShowKartePanel((v) => !v)}
                    aria-label={t("inbox.karteToggle")}
                  >
                    <PAGE_ICONS.kartePanel size={ICON.sm} aria-hidden="true" />
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
          <div className="karte-overlay" onClick={() => setShowKartePanel(false)} aria-hidden="true" />
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
                  onClick={() => setShowKartePanel(false)}
                  aria-label={t("common.close")}
                >
                  <NAV_ICONS.close size={ICON.md} aria-hidden="true" />
                </button>
              </div>
              {/* ヘッダー */}
              <div className="right-panel-header">
                <div className="right-panel-avatar">
                  {getInitials(cardForm.customer_name ?? leadDetail.customer_name)}
                </div>
                <input
                  className="right-panel-field right-panel-name-field"
                  type="text"
                  value={cardForm.customer_name ?? ""}
                  onChange={(e) => handleCardFieldChange("customer_name", e.target.value)}
                  onBlur={handleCardFieldBlur}
                  placeholder={t("leads.customerName")}
                />
                <input
                  className="right-panel-field right-panel-en-name-field"
                  type="text"
                  value={cardForm.english_name ?? ""}
                  onChange={(e) => handleCardFieldChange("english_name", e.target.value)}
                  onBlur={handleCardFieldBlur}
                  placeholder={t("leads.englishName")}
                />
                <p className="right-panel-code">{leadDetail.lead_code}</p>
                {leadDetail.prospect_rank && (
                  <div className={`right-panel-rank rank-${leadDetail.prospect_rank.replace("+", "plus")}`}>
                    {t("leads.rank")} {leadDetail.prospect_rank}
                  </div>
                )}
              </div>

              {/* 保存ステータスインジケーター */}
              <div className="right-panel-save-indicator">
                {cardSaveStatus === "saving" && <span>{t("common.saving")}</span>}
                {cardSaveStatus === "saved" && <span className="saved">{t("common.saved")}</span>}
                {cardSaveStatus === "error" && <span className="error">{cardSaveError}</span>}
              </div>

              {/* セクション1: 連絡先 */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionContact")}</div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.companyName")}</span>
                  <input className="right-panel-field" type="text"
                    value={cardForm.company_name ?? ""}
                    onChange={(e) => handleCardFieldChange("company_name", e.target.value)}
                    onBlur={handleCardFieldBlur} />
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

              {/* セクション2: 商談情報 */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionDeal")}</div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.status")}</span>
                  <select className="right-panel-field"
                    value={cardForm.status ?? ""}
                    onChange={(e) => handleCardFieldChange("status", e.target.value)}
                    onBlur={handleCardFieldBlur}>
                    <option value="新規">{t("leads.status_new")}</option>
                    <option value="コンタクト中">{t("leads.status_contact")}</option>
                    <option value="提案中">{t("leads.status_proposal")}</option>
                    <option value="案件化">{t("leads.status_won")}</option>
                    <option value="失注">{t("leads.status_lost")}</option>
                    <option value="保留">{t("leads.status_hold")}</option>
                    <option value="AI対応中">{t("leads.status_ai_collecting")}</option>
                    <option value="既存顧客">{t("leads.status_existing_customer")}</option>
                    <option value="追客（短期）">{t("leads.status_follow_up_short")}</option>
                    <option value="追客（長期）">{t("leads.status_follow_up_long")}</option>
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
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.salesForm")}</span>
                  <input className="right-panel-field" type="text"
                    value={cardForm.sales_form ?? ""}
                    onChange={(e) => handleCardFieldChange("sales_form", e.target.value)}
                    onBlur={handleCardFieldBlur} />
                </div>
                <div className="right-panel-row">
                  <span className="right-panel-label">{t("leads.meetingImpression")}</span>
                  <input className="right-panel-field" type="text"
                    value={cardForm.meeting_impression ?? ""}
                    onChange={(e) => handleCardFieldChange("meeting_impression", e.target.value)}
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
              </div>

              {/* セクション3: 次回アクション */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionNextAction")}</div>
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
              </div>

              {/* セクション4: 課題・ニーズ */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionChallenge")}</div>
                <textarea className="right-panel-field" rows={3}
                  value={cardForm.challenge ?? ""}
                  onChange={(e) => handleCardFieldChange("challenge", e.target.value)}
                  onBlur={handleCardFieldBlur}
                  placeholder={t("leads.challenge")} />
              </div>

              {/* セクション5: メモ */}
              <div className="right-panel-section">
                <div className="right-panel-section-title">{t("inbox.sectionMemo")}</div>
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

      {/* ============================== 受信箱設定モーダル ============================== */}
      {showSettings && (
        <div className="inbox-settings-overlay" onClick={() => setShowSettings(false)}>
          <div className="inbox-settings-modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="inbox-settings-modal-title">{t("inbox.settings.title")}</h2>

            <div className="inbox-settings-section-title">{t("inbox.settings.display")}</div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.showRightPanel")}</span>
              <label className="inbox-toggle">
                <input type="checkbox" checked={inboxSettings.showRightPanel}
                  onChange={(e) => updateInboxSetting("showRightPanel", e.target.checked)} />
                <span className="inbox-toggle-slider" />
              </label>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.defaultTab")}</span>
              <select className="inbox-settings-select"
                value={inboxSettings.defaultTab}
                onChange={(e) => updateInboxSetting("defaultTab", e.target.value as InboxSettings["defaultTab"])}>
                <option value="all">{t("inbox.settings.defaultTabAll")}</option>
                <option value="messenger">{t("inbox.settings.defaultTabMessenger")}</option>
                <option value="instagram">{t("inbox.settings.defaultTabInstagram")}</option>
              </select>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.defaultUnreadOnly")}</span>
              <label className="inbox-toggle">
                <input type="checkbox" checked={inboxSettings.defaultUnreadOnly}
                  onChange={(e) => updateInboxSetting("defaultUnreadOnly", e.target.checked)} />
                <span className="inbox-toggle-slider" />
              </label>
            </div>

            <div className="inbox-settings-section-title" style={{ marginTop: "var(--space-4)" }}>
              {t("inbox.settings.notifications")}
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.browserNotifications")}</span>
              <label className="inbox-toggle">
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
                <span className="inbox-toggle-slider" />
              </label>
            </div>

            <div className="inbox-settings-row">
              <span className="inbox-settings-label">{t("inbox.settings.soundEnabled")}</span>
              <label className="inbox-toggle">
                <input type="checkbox" checked={inboxSettings.soundEnabled}
                  onChange={(e) => updateInboxSetting("soundEnabled", e.target.checked)} />
                <span className="inbox-toggle-slider" />
              </label>
            </div>

            <button type="button" className="inbox-settings-close-btn" onClick={() => setShowSettings(false)}>
              {t("common.close")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
