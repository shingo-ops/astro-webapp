/**
 * Inbox ページ（Phase 1-D Sprint 4 / Sprint 5）。
 *
 * 既存 `/lead-chat` の ComingSoonPage を置き換える。Messenger / Instagram の
 * メッセージ表示 + 返信送信を担当する 2 ペイン構成。
 *
 * 仕様: spec §5-3 / §5-4 / §5-5 / §5-6 / §7-2
 *
 * 主な機能:
 *  - 左ペイン: GET /api/v1/conversations の会話リスト
 *      - platform フィルタ（all / messenger / instagram）
 *      - unread_only トグル
 *      - 最新メッセージ要約 + 未読バッジ + 相対時刻
 *  - 右ペイン: 選択中 lead の GET /api/v1/leads/{id}/messages
 *      - direction で吹き出し位置切替（inbound 左 / outbound 右）
 *      - 24h messaging window のバナー（緑/黄/赤）
 *      - 返信送信フォーム（Sprint 5 で追加）
 *          - Enter で送信、Shift+Enter で改行
 *          - 送信中 loading、成功で textarea クリア + メッセージ再取得
 *          - 7d 超過時は disabled、24h-7d 時は HUMAN_AGENT 注記
 *      - lead 切替時に POST /messages/mark-read で既読化
 *  - 10 秒 polling（会話リスト + 選択中メッセージ）
 *  - URL ?lead_id=XXX で deep link
 *
 * 変更履歴:
 *   2026-04-30: Sprint 4 初版（送信ボタン disabled）
 *   2026-04-30: Sprint 5 — lib/messages.ts ヘルパ経由に切替 + 送信機能 enable
 */

import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import {
  Conversation,
  MessagesResponse,
  MessagingWindow,
  PlatformFilter,
  getMessages,
  listConversations,
  markRead as apiMarkRead,
  sendMessage,
} from "../lib/messages";

// ---------------------------------------------------------------------------
// 設定
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 10_000;

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
  if (diffSec < 60) return "たった今";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}分前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}時間前`;
  const diffDay = Math.floor(diffHour / 24);
  if (diffDay < 7) return `${diffDay}日前`;
  return d.toLocaleDateString("ja-JP", { month: "2-digit", day: "2-digit" });
}

/** `2026-04-30 14:25` 形式の絶対時刻（吹き出しの hover タイトル用）。 */
function formatAbsolute(iso: string | null): string {
  const d = parseDate(iso);
  if (!d) return "—";
  return d.toLocaleString("ja-JP", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function platformLabel(p: string | null): string {
  if (p === "messenger") return "Messenger";
  if (p === "instagram") return "Instagram";
  return p || "—";
}

function platformBadgeStyle(p: string | null): React.CSSProperties {
  if (p === "messenger") {
    return { background: "#E7F3FF", color: "#0866FF", borderColor: "#0866FF" };
  }
  if (p === "instagram") {
    return { background: "#FCE3F0", color: "#C13584", borderColor: "#C13584" };
  }
  return { background: "#eee", color: "#666", borderColor: "#999" };
}

// ---------------------------------------------------------------------------
// メイン
// ---------------------------------------------------------------------------

export default function InboxPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialLeadIdRaw = searchParams.get("lead_id");
  const initialLeadId = initialLeadIdRaw && !isNaN(Number(initialLeadIdRaw))
    ? Number(initialLeadIdRaw)
    : null;

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convLoading, setConvLoading] = useState(true);
  const [convError, setConvError] = useState("");
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
  const [unreadOnly, setUnreadOnly] = useState(false);

  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(initialLeadId);
  const [messagesData, setMessagesData] = useState<MessagesResponse | null>(null);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");

  // 入力欄
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  // Phase 1-E F4-S5: 24h 以内でも明示的に Human Agent Tag を付与する toggle
  // backend は force_human_agent_tag を spec §5-5 で受付済（Sprint 5）
  const [forceHumanAgentTag, setForceHumanAgentTag] = useState(false);

  // メッセージ末尾への自動スクロール用 ref
  const messageListRef = useRef<HTMLDivElement | null>(null);

  // ---------------------------------------------------------------------------
  // データ取得
  // ---------------------------------------------------------------------------

  const loadConversations = useCallback(async () => {
    setConvError("");
    try {
      const data = await listConversations({
        platform: platformFilter,
        unread_only: unreadOnly,
      });
      setConversations(data.conversations || []);
    } catch (e) {
      const msg = e instanceof ApiError
        ? e.message
        : e instanceof Error ? e.message : "会話一覧の取得に失敗しました";
      setConvError(msg);
    } finally {
      setConvLoading(false);
    }
  }, [platformFilter, unreadOnly]);

  const loadMessages = useCallback(async (leadId: number) => {
    setMsgError("");
    setMsgLoading(true);
    try {
      const data = await getMessages(leadId);
      setMessagesData(data);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setMsgError("リードが見つかりませんでした。");
      } else {
        const msg = e instanceof ApiError
          ? e.message
          : e instanceof Error ? e.message : "メッセージの取得に失敗しました";
        setMsgError(msg);
      }
      setMessagesData(null);
    } finally {
      setMsgLoading(false);
    }
  }, []);

  const markRead = useCallback(async (leadId: number) => {
    try {
      const res = await apiMarkRead(leadId);
      // ローカル状態の unread_count も即座に 0 にする
      if (res.marked_count > 0) {
        setConversations(prev =>
          prev.map(c => c.lead_id === leadId ? { ...c, unread_count: 0 } : c)
        );
      }
    } catch {
      // 既読化失敗は致命的では無いので無視（次回再試行）
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
  // 10s polling（会話リスト + 選択中メッセージ）
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const id = setInterval(() => {
      loadConversations();
      if (selectedLeadId !== null) {
        loadMessages(selectedLeadId);
      }
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadConversations, loadMessages, selectedLeadId]);

  // ---------------------------------------------------------------------------
  // lead 選択時 → メッセージ取得 + 既読化 + URL クエリ反映
  // ---------------------------------------------------------------------------

  const selectLead = useCallback((leadId: number) => {
    setSelectedLeadId(leadId);
    setDraft("");
    setSendError("");
    // URL クエリ反映（deep link 維持）
    const params = new URLSearchParams(searchParams);
    params.set("lead_id", String(leadId));
    setSearchParams(params, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (selectedLeadId === null) {
      setMessagesData(null);
      return;
    }
    loadMessages(selectedLeadId);
    // 既読マーク（fire-and-forget）
    markRead(selectedLeadId);
  }, [selectedLeadId, loadMessages, markRead]);

  // メッセージリスト読み込み完了後、最下部にスクロール
  useEffect(() => {
    if (!messagesData) return;
    const el = messageListRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messagesData]);

  // ---------------------------------------------------------------------------
  // 送信（Sprint 5）
  // ---------------------------------------------------------------------------

  const messagingWindow = messagesData?.messaging_window;
  const canSend = !!messagingWindow?.can_send_at_all;
  const trimmedDraft = draft.trim();
  // 入力が空 / 送信中 / 7d 超 / lead 未選択 のとき送信ボタン disabled
  const sendDisabled = sending || !canSend || trimmedDraft.length === 0 || selectedLeadId === null;

  const submitSend = useCallback(async () => {
    if (sendDisabled || selectedLeadId === null) return;
    setSendError("");
    setSending(true);
    try {
      await sendMessage(selectedLeadId, {
        text: trimmedDraft,
        force_human_agent_tag: forceHumanAgentTag || undefined,
      });
      setDraft("");
      // 成功直後に即座にメッセージ再取得（楽観的更新ではなく確実な再描画）
      await loadMessages(selectedLeadId);
      // 会話リストも更新（最終メッセージ要約 / 並び順反映）
      loadConversations();
    } catch (e) {
      if (e instanceof ApiError) {
        setSendError(e.message || "送信に失敗しました");
      } else if (e instanceof Error) {
        setSendError(e.message);
      } else {
        setSendError("送信に失敗しました");
      }
    } finally {
      setSending(false);
    }
  }, [sendDisabled, selectedLeadId, trimmedDraft, forceHumanAgentTag, loadMessages, loadConversations]);

  /** Enter で送信、Shift+Enter で改行（chat UX 標準）。日本語 IME 変換中は無視。 */
  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submitSend();
    }
  }, [submitSend]);

  // ---------------------------------------------------------------------------
  // 描画
  // ---------------------------------------------------------------------------

  const selectedConversation = useMemo(
    () => conversations.find(c => c.lead_id === selectedLeadId) || null,
    [conversations, selectedLeadId],
  );

  return (
    <div
      className="page inbox-page"
      style={{
        display: "flex",
        gap: 0,
        height: "calc(100vh - 80px)",
        overflow: "hidden",
      }}
    >
      {/* ----------------------- 左ペイン: 会話リスト ----------------------- */}
      <aside
        style={{
          width: 320,
          flexShrink: 0,
          borderRight: "1px solid var(--border-color, #e0e0e0)",
          display: "flex",
          flexDirection: "column",
          background: "var(--bg-secondary, #fafafa)",
        }}
      >
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border-color, #e0e0e0)" }}>
          <h2 style={{ margin: "0 0 12px 0", fontSize: "1.1rem" }}>受信トレイ</h2>
          <div style={{ display: "flex", gap: 4, marginBottom: 8, flexWrap: "wrap" }}>
            {(["all", "messenger", "instagram"] as PlatformFilter[]).map(p => (
              <button
                key={p}
                type="button"
                className={platformFilter === p ? "btn-sm btn-primary" : "btn-sm"}
                onClick={() => setPlatformFilter(p)}
                style={{ fontSize: "0.8rem" }}
              >
                {p === "all" ? "すべて" : platformLabel(p)}
              </button>
            ))}
          </div>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={unreadOnly}
              onChange={e => setUnreadOnly(e.target.checked)}
            />
            未読のみ表示
          </label>
        </div>

        <div style={{ flex: 1, overflowY: "auto" }}>
          {convError && (
            <div className="error" style={{ margin: 12 }}>
              {convError}
              <button
                type="button"
                className="btn-sm"
                style={{ marginLeft: 8 }}
                onClick={() => loadConversations()}
              >
                再読み込み
              </button>
            </div>
          )}
          {convLoading ? (
            <div className="loading" style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
              読み込み中...
            </div>
          ) : conversations.length === 0 ? (
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)", fontSize: "0.9rem" }}>
              {unreadOnly
                ? "未読の会話はありません"
                : "まだメッセージがありません。"}
              <br />
              {!unreadOnly && (
                <span style={{ fontSize: "0.8rem" }}>
                  Facebook Page を接続するには{" "}
                  <a href="/channels">Channels 設定</a>
                  {" "}を確認してください。
                </span>
              )}
            </div>
          ) : (
            conversations.map(conv => {
              const isSelected = conv.lead_id === selectedLeadId;
              return (
                <button
                  key={conv.lead_id}
                  type="button"
                  onClick={() => selectLead(conv.lead_id)}
                  className="conversation-item"
                  style={{
                    width: "100%",
                    padding: "12px 16px",
                    border: "none",
                    borderBottom: "1px solid var(--border-color, #e8e8e8)",
                    background: isSelected ? "var(--bg-selected, #e8f0fe)" : "transparent",
                    textAlign: "left",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "space-between" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                      <span
                        className="badge"
                        style={{
                          fontSize: "0.7rem",
                          padding: "2px 6px",
                          borderRadius: 3,
                          border: "1px solid",
                          flexShrink: 0,
                          ...platformBadgeStyle(conv.platform),
                        }}
                      >
                        {platformLabel(conv.platform)}
                      </span>
                      <strong
                        style={{
                          fontSize: "0.95rem",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          minWidth: 0,
                        }}
                      >
                        {conv.customer_name || conv.lead_code || `Lead #${conv.lead_id}`}
                      </strong>
                    </div>
                    {conv.unread_count > 0 && (
                      <span
                        className="badge"
                        style={{
                          background: "#1a73e8",
                          color: "#fff",
                          padding: "2px 8px",
                          borderRadius: 999,
                          fontSize: "0.75rem",
                          flexShrink: 0,
                        }}
                      >
                        {conv.unread_count}
                      </span>
                    )}
                  </div>
                  <div
                    style={{
                      fontSize: "0.85rem",
                      color: "var(--text-muted, #666)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {conv.last_message_direction === "outbound" && (
                      <span style={{ color: "#666" }}>あなた: </span>
                    )}
                    {conv.last_message_text || "(メッセージなし)"}
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--text-muted, #999)" }}>
                    {relativeTime(conv.last_message_at)}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {/* ----------------------- 右ペイン: メッセージ ----------------------- */}
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {selectedLeadId === null ? (
          <div
            style={{
              flex: 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-muted, #888)",
              padding: 32,
              textAlign: "center",
            }}
          >
            左のリストから会話を選択してください。
          </div>
        ) : (
          <>
            {/* ヘッダ */}
            <header
              style={{
                padding: "12px 16px",
                borderBottom: "1px solid var(--border-color, #e0e0e0)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 16,
              }}
            >
              <div>
                <h3 style={{ margin: 0, fontSize: "1.05rem" }}>
                  {messagesData?.lead?.customer_name
                    || selectedConversation?.customer_name
                    || `Lead #${selectedLeadId}`}
                </h3>
                <div style={{ fontSize: "0.8rem", color: "var(--text-muted, #666)", marginTop: 2 }}>
                  {messagesData?.lead?.lead_code && (
                    <span style={{ marginRight: 8 }}>{messagesData.lead.lead_code}</span>
                  )}
                  <span
                    className="badge"
                    style={{
                      fontSize: "0.7rem",
                      padding: "2px 6px",
                      borderRadius: 3,
                      border: "1px solid",
                      ...platformBadgeStyle(messagesData?.lead?.platform || selectedConversation?.platform || null),
                    }}
                  >
                    {platformLabel(messagesData?.lead?.platform || selectedConversation?.platform || null)}
                  </span>
                </div>
              </div>
              <a
                href={`/leads?lead_id=${selectedLeadId}`}
                className="btn-sm"
                style={{ fontSize: "0.8rem" }}
              >
                リード詳細
              </a>
            </header>

            {/* メッセージリスト */}
            <div
              ref={messageListRef}
              style={{
                flex: 1,
                overflowY: "auto",
                padding: 16,
                background: "var(--bg-content, #fff)",
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {msgLoading && !messagesData && (
                <div className="loading" style={{ textAlign: "center", color: "var(--text-muted)" }}>
                  読み込み中...
                </div>
              )}
              {msgError && (
                <div className="error">{msgError}</div>
              )}
              {messagesData && messagesData.messages.length === 0 && !msgError && (
                <div style={{ textAlign: "center", color: "var(--text-muted, #888)", padding: 32 }}>
                  まだメッセージはありません。
                </div>
              )}
              {messagesData?.messages.map(msg => {
                const outbound = msg.direction === "outbound";
                return (
                  <div
                    key={msg.id}
                    style={{
                      display: "flex",
                      justifyContent: outbound ? "flex-end" : "flex-start",
                    }}
                  >
                    <div
                      style={{
                        maxWidth: "70%",
                        padding: "8px 12px",
                        borderRadius: 12,
                        background: outbound ? "#1a73e8" : "#f1f3f4",
                        color: outbound ? "#fff" : "var(--text-primary, #202124)",
                        borderTopRightRadius: outbound ? 4 : 12,
                        borderTopLeftRadius: outbound ? 12 : 4,
                        wordBreak: "break-word",
                        whiteSpace: "pre-wrap",
                      }}
                      title={formatAbsolute(msg.created_at)}
                    >
                      {msg.message_tag && (
                        <div
                          style={{
                            fontSize: "0.7rem",
                            opacity: 0.85,
                            marginBottom: 4,
                            fontWeight: 600,
                          }}
                        >
                          {msg.message_tag === "HUMAN_AGENT" ? "Human Agent" : msg.message_tag}
                        </div>
                      )}
                      <div>{msg.message_text || "(本文なし)"}</div>
                      <div
                        style={{
                          fontSize: "0.7rem",
                          opacity: 0.75,
                          marginTop: 4,
                          textAlign: outbound ? "right" : "left",
                        }}
                      >
                        {relativeTime(msg.created_at)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* messaging window バナー + 入力 */}
            <div
              style={{
                borderTop: "1px solid var(--border-color, #e0e0e0)",
                padding: 12,
                background: "var(--bg-secondary, #fafafa)",
              }}
            >
              {messagingWindow && (
                <MessagingWindowBanner messagingWindow={messagingWindow} />
              )}
              {/* Phase 1-E F4-S5: Human Agent Tag 強制付与 toggle
                  WITHIN_24H 時のみ意味があるオプション。24h 超は自動で HUMAN_AGENT 適用済 */}
              {messagingWindow?.can_send_response && (
                <label
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    fontSize: "0.8rem",
                    marginBottom: 8,
                    cursor: "pointer",
                    color: forceHumanAgentTag ? "#a45a00" : "var(--text-secondary, #666)",
                  }}
                  title="ON にすると 24h 以内でも MESSAGE_TAG=HUMAN_AGENT で送信されます（運用回避用）"
                >
                  <input
                    type="checkbox"
                    checked={forceHumanAgentTag}
                    onChange={e => setForceHumanAgentTag(e.target.checked)}
                    disabled={sending}
                  />
                  Human Agent Tag を強制付与{forceHumanAgentTag ? "（次の送信に適用）" : ""}
                </label>
              )}
              {sendError && (
                <div
                  className="error"
                  role="alert"
                  style={{
                    padding: "6px 10px",
                    borderRadius: 4,
                    background: "#fdecea",
                    color: "#a50e0e",
                    border: "1px solid #a50e0e",
                    fontSize: "0.8rem",
                    marginBottom: 8,
                  }}
                >
                  送信エラー: {sendError}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                <textarea
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={
                    canSend
                      ? "返信を入力（Enter で送信、Shift+Enter で改行）"
                      : "メッセージウィンドウを超過しているため送信できません"
                  }
                  rows={2}
                  disabled={!canSend || sending}
                  style={{
                    flex: 1,
                    padding: 8,
                    borderRadius: 6,
                    border: "1px solid var(--border-color, #ccc)",
                    fontFamily: "inherit",
                    fontSize: "0.9rem",
                    resize: "vertical",
                    background: !canSend ? "#f5f5f5" : "white",
                  }}
                />
                <button
                  type="button"
                  className="btn-primary"
                  onClick={submitSend}
                  disabled={sendDisabled}
                  title={
                    !canSend
                      ? "メッセージウィンドウを超過しているため送信できません"
                      : trimmedDraft.length === 0
                        ? "本文を入力してください"
                        : "送信（Enter）"
                  }
                >
                  {sending ? "送信中..." : "送信"}
                </button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// messaging window バナー
// ---------------------------------------------------------------------------

function MessagingWindowBanner({ messagingWindow }: { messagingWindow: MessagingWindow }) {
  // - 緑: 24h 以内（can_send_response=true）
  // - 黄: 24h-7d（requires_human_agent_tag=true）
  // - 赤: 7d 超 or inbound 履歴なし（can_send_at_all=false）
  let color: { bg: string; fg: string; border: string };
  let text: string;

  if (messagingWindow.can_send_response) {
    color = { bg: "#e6f4ea", fg: "#137333", border: "#137333" };
    text = "通常返信ウィンドウ内（24 時間以内）。返信は RESPONSE タイプで送信されます。";
  } else if (messagingWindow.requires_human_agent_tag) {
    color = { bg: "#fff4e5", fg: "#a45a00", border: "#a45a00" };
    text = "24 時間を超過しています。返信は Human Agent Tag 付きで送信されます（24 時間〜7 日以内）。";
  } else if (!messagingWindow.can_send_at_all) {
    color = { bg: "#fdecea", fg: "#a50e0e", border: "#a50e0e" };
    text = messagingWindow.last_inbound_at
      ? "メッセージウィンドウを超過しています(受信から 7 日以上経過)。返信できません。"
      : "受信履歴がありません。Meta の仕様により最初のメッセージは顧客側から送信される必要があります。";
  } else {
    // 念のため fallback
    color = { bg: "#eee", fg: "#333", border: "#999" };
    text = "メッセージング状態を確認中...";
  }

  return (
    <div
      role="status"
      style={{
        padding: "8px 12px",
        borderRadius: 4,
        marginBottom: 8,
        background: color.bg,
        color: color.fg,
        border: `1px solid ${color.border}`,
        fontSize: "0.8rem",
      }}
    >
      {text}
    </div>
  );
}
