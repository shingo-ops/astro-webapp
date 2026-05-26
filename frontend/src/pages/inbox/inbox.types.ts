/**
 * InboxPage 共有型定義・定数・ヘルパー関数
 *
 * InboxPage.tsx から抽出（STEP 3-C）。
 * UI コンポーネント・カスタムフックから共通参照する。
 */

// ---------------------------------------------------------------------------
// ポーリング設定
// ---------------------------------------------------------------------------

export const POLL_INTERVAL_MS = 30_000;
export const POLL_MAX_INTERVAL_MS = 300_000;
export const POLL_BACKOFF_FACTOR = 2;

// ---------------------------------------------------------------------------
// ステータスタブ定数（商談進捗ベース）
// ---------------------------------------------------------------------------

export const STATUS_TABS = [
  { key: "all",      labelKey: "inbox.tabAll",      statuses: null as null | string[] },
  { key: "lead",     labelKey: "inbox.tabLead",     statuses: ["新規"] },
  { key: "deal",     labelKey: "inbox.tabDeal",     statuses: ["商談中"] },
  { key: "existing", labelKey: "inbox.tabExisting", statuses: ["既存顧客"] },
  { key: "followup", labelKey: "inbox.tabFollowUp", statuses: ["追客（短期）", "追客（長期）"] },
  { key: "archive",  labelKey: "inbox.tabArchive",  statuses: ["失注", "対象外"] },
] as const;

export type StatusTabKey = "all" | "lead" | "deal" | "existing" | "followup" | "archive";
export type KarteTabKey = "contact" | "company" | "deal";

// ---------------------------------------------------------------------------
// リードステータス分類定数
// ---------------------------------------------------------------------------

// フォローアップフィルターから除外するステータス（返信しても意味がない相手）
export const FOLLOWUP_EXCLUDED = new Set(["失注", "対象外"]);

// ---------------------------------------------------------------------------
// LeadDetail 型（GET /leads/{id} のレスポンス）
// ---------------------------------------------------------------------------

export interface LeadDetail {
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
  nickname: string | null;
  country: string | null;
  target_titles: string | null;
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

/** ISO/SQLite 互換の datetime 文字列を Date に変換（無効値なら null）。 */
export function parseDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso.replace(" ", "T"));
  return isNaN(d.getTime()) ? null : d;
}

/** 現時刻を起点に「N 分前」「N 時間前」等の相対表記。 */
export function relativeTime(iso: string | null): string {
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
export function formatAbsolute(iso: string | null): string {
  const d = parseDate(iso);
  if (!d) return "—";
  return d.toLocaleString("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

/** イニシャルアバター文字（最大 2 文字）。 */
export function getInitials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

// ---------------------------------------------------------------------------
// 受信箱設定 (localStorage)
// ---------------------------------------------------------------------------

export const INBOX_SETTINGS_KEY = "inbox_settings";
export const DRAFT_KEY = (leadId: number) => `cartedit_draft_${leadId}`;

export interface InboxSettings {
  showRightPanel: boolean;
  defaultTab: StatusTabKey;
  defaultUnreadOnly: boolean;
  browserNotifications: boolean;
  soundEnabled: boolean;
}

export const DEFAULT_INBOX_SETTINGS: InboxSettings = {
  showRightPanel: true,
  defaultTab: "all",
  defaultUnreadOnly: false,
  browserNotifications: false,
  soundEnabled: false,
};

export function readInboxSettings(): InboxSettings {
  try {
    const raw = localStorage.getItem(INBOX_SETTINGS_KEY);
    return raw ? { ...DEFAULT_INBOX_SETTINGS, ...JSON.parse(raw) } : DEFAULT_INBOX_SETTINGS;
  } catch {
    return DEFAULT_INBOX_SETTINGS;
  }
}
