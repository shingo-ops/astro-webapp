/**
 * Meta Inbox 関連 API クライアント（Phase 1-D Sprint 5）。
 *
 * spec §5-3 / §5-4 / §5-5 / §5-6 の endpoint をラップする。
 * Sprint 4 までは InboxPage 内で `api.get('/conversations'...)` のように
 * path 直書きしていたが、Sprint 5 で送信処理を増やす際に重複を避けるため
 * 集約した（Sprint 4 Reviewer F5 follow-up）。
 *
 * すべての関数は ApiError を素のまま投げる。呼び出し側は
 *   import { ApiError } from "../lib/api";
 *   try { await sendMessage(...) } catch (e) { if (e instanceof ApiError) ... }
 * のように扱う。
 */

import { api } from "./api";

// ---------------------------------------------------------------------------
// 型定義
// ---------------------------------------------------------------------------

export interface Conversation {
  lead_id: number;
  lead_code: string | null;
  customer_name: string | null;
  /** リードステータス（例: 新規、既存顧客 など）。紐付きリードがない場合 null */
  lead_status: string | null | undefined;
  platform: "messenger" | "instagram" | string;
  /** Phase 1-E F14-S5: Messenger 受信のみ Page ID。IG は当面 null */
  page_id: string | null;
  last_message_text: string | null;
  last_message_at: string | null;
  last_message_direction: "inbound" | "outbound" | string;
  unread_count: number;
  messaging_window_expires_at: string | null;
  /** プラットフォームAPIから取得したアバター画像URL。取得不可・キャッシュ未生成の場合null */
  profile_picture_url?: string | null;
}

export interface ConversationsResponse {
  conversations: Conversation[];
  next_cursor: string | null;
}

export interface Message {
  id: number;
  platform: string;
  sender_id: string | null;
  sender_name: string | null;
  message_text: string | null;
  direction: "inbound" | "outbound" | string;
  message_id: string | null;
  recipient_id: string | null;
  messaging_type: string | null;
  message_tag: string | null;
  sent_by_staff_id: number | null;
  error_code: string | null;
  error_message: string | null;
  seen_at: string | null;
  seen_by_staff_id: number | null;
  created_at: string | null;
}

export interface MessagingWindow {
  last_inbound_at: string | null;
  expires_at: string | null;
  can_send_response: boolean;
  requires_human_agent_tag: boolean;
  can_send_at_all: boolean;
}

export interface MessagesResponse {
  messages: Message[];
  lead: {
    id: number;
    lead_code: string | null;
    customer_name: string | null;
    platform: string | null;
    source: string | null;
  };
  messaging_window: MessagingWindow;
}

export interface MarkReadResponse {
  marked_count: number;
}

export interface SendMessageRequest {
  text: string;
}

export interface SendMessageResponse {
  id: number;
  message_id: string | null;
  messaging_type: string | null;
  message_tag: string | null;
  sent_at: string | null;
  lead_id: number;
  platform: string;
}

export type PlatformFilter = "all" | "messenger" | "instagram" | "discord";

// ---------------------------------------------------------------------------
// 表示ヘルパ（Phase 1-E F24-S5: platform 推論を一箇所に集約）
// ---------------------------------------------------------------------------

/**
 * lead 情報と conversation 情報から platform を推論する。
 *
 * GET /messages レスポンスの `lead.platform` を最優先、なければ会話一覧の
 * `conversation.platform` を fallback する。両方とも null なら null を返す。
 *
 * Phase 1-E F24-S5: InboxPage の `messagesData?.lead?.platform || selectedConversation?.platform`
 * 散在を解消するため lib/messages.ts に集約。
 */
export function inferPlatform(
  lead: { platform: string | null } | null | undefined,
  conversation: { platform: string | null } | null | undefined,
): string | null {
  return lead?.platform ?? conversation?.platform ?? null;
}

/** platform 値を表示ラベルに正規化。 */
export function platformLabel(p: string | null): string {
  if (p === "messenger") return "Messenger";
  if (p === "instagram") return "Instagram";
  if (p === "discord") return "Discord";
  return p || "—";
}

// ---------------------------------------------------------------------------
// API ヘルパ
// ---------------------------------------------------------------------------

/**
 * GET /api/v1/conversations
 *
 * @param filter - { platform, unread_only } のサブセット
 */
export async function listConversations(
  filter: {
    platform?: PlatformFilter;
    unread_only?: boolean;
    /** Phase 1-E F14-S5: Page ID で絞り込み（指定時、IG メッセージは除外される） */
    page_id?: string;
  } = {},
): Promise<ConversationsResponse> {
  const params = new URLSearchParams();
  if (filter.platform && filter.platform !== "all") {
    params.set("platform", filter.platform);
  }
  if (filter.unread_only) {
    params.set("unread_only", "true");
  }
  if (filter.page_id) {
    params.set("page_id", filter.page_id);
  }
  const qs = params.toString();
  return api.get<ConversationsResponse>(
    `/conversations${qs ? `?${qs}` : ""}`,
  );
}

/**
 * GET /api/v1/leads/{lead_id}/messages
 */
export async function getMessages(leadId: number): Promise<MessagesResponse> {
  return api.get<MessagesResponse>(`/leads/${leadId}/messages`);
}

/**
 * POST /api/v1/leads/{lead_id}/messages/mark-read
 */
export async function markRead(leadId: number): Promise<MarkReadResponse> {
  return api.post<MarkReadResponse>(`/leads/${leadId}/messages/mark-read`, {});
}

/**
 * POST /api/v1/leads/{lead_id}/messages
 *
 * 24h ルール判定はサーバー側で行うため、フロントは text だけ送る。
 * messaging_type は常に HUMAN_AGENT をサーバーが自動付与する（ADR-035）。
 * 失敗時は ApiError を throw。
 */
export async function sendMessage(
  leadId: number,
  request: SendMessageRequest,
): Promise<SendMessageResponse> {
  return api.post<SendMessageResponse>(
    `/leads/${leadId}/messages`,
    { text: request.text },
  );
}
