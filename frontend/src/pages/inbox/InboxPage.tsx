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
import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInboxSSE } from "../../hooks/useInboxSSE";
import { INBOX_ACTION_ICONS, NAV_ICONS, PAGE_ICONS, PlatformIcon, STATUS_ICONS } from "../../constants/icons";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { PageLayout } from "../../components/PageLayout";
import { api, ApiError } from "../../lib/api";
import { ICON } from "../../constants/iconSizes";
import {
  Conversation,
  MessagesResponse,
  MessagingWindow,
  PlatformFilter,
  getMessages,
  inferPlatform,
  listConversations,
  markRead as apiMarkRead,

  sendMessage,
} from "../../lib/messages";

// ---------------------------------------------------------------------------
// 設定
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 30_000;
const POLL_MAX_INTERVAL_MS = 300_000;
const POLL_BACKOFF_FACTOR = 2;

// ---------------------------------------------------------------------------
// ステータスタブ定数（商談進捗ベース）
// ---------------------------------------------------------------------------

const STATUS_TABS = [
  { key: "all",      labelKey: "inbox.tabAll",      statuses: null as null | string[] },
  { key: "lead",     labelKey: "inbox.tabLead",     statuses: ["新規"] },
  { key: "deal",     labelKey: "inbox.tabDeal",     statuses: ["商談中"] },
  { key: "existing", labelKey: "inbox.tabExisting", statuses: ["既存顧客"] },
  { key: "followup", labelKey: "inbox.tabFollowUp", statuses: ["追客（短期）", "追客（長期）"] },
  { key: "archive",  labelKey: "inbox.tabArchive",  statuses: ["失注", "対象外"] },
] as const;

type StatusTabKey = "all" | "lead" | "deal" | "existing" | "followup" | "archive";

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
  nickname: string | null;
  country: string | null;
  target_titles: string | null;
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



// ---------------------------------------------------------------------------
// 受信箱設定 (localStorage)
// ---------------------------------------------------------------------------

const INBOX_SETTINGS_KEY = "inbox_settings";
const DRAFT_KEY = (leadId: number) => `cartedit_draft_${leadId}`;

interface InboxSettings {
  showRightPanel: boolean;
  defaultTab: StatusTabKey;
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
  const [statusTab, setStatusTab] = useState<StatusTabKey>(() => readInboxSettings().defaultTab);
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
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
  // アバター画像ロード失敗済みのlead_idセット（onError時にイニシャルフォールバック）
  const [avatarErrors, setAvatarErrors] = useState<Set<number>>(new Set());
  const handleAvatarError = useCallback((leadId: number) => {
    setAvatarErrors(prev => { const s = new Set(prev); s.add(leadId); return s; });
  }, []);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");

  // 右パネル (顧客カルテ)
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);
  const [cardForm, setCardForm] = useState<Partial<LeadDetail>>({});
  const [cardSaveStatus, setCardSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [cardSaveError, setCardSaveError] = useState("");
  // カルテ右パネルのタブ（連絡先 / 会社情報 / 商談情報）
  const [karteTab, setKarteTab] = useState<"contact" | "company" | "deal">("contact");
  // モバイル/タブレット時のカルテドロワー開閉（デスクトップ≥1280pxでは常時表示のため無視）
  const [showKartePanel, setShowKartePanel] = useState(false);
  // プロフィールモーダル
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [profileModalTab, setProfileModalTab] = useState<"contact" | "company" | "deal">("contact");
  const profileModalRef = useRef<HTMLDivElement>(null);

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
  // 502/503/ネットワークエラーの連続発生カウント（loadConversations用）
  const transientErrorCountRef = useRef(0);
  // loadMessages専用の一時エラーカウンター（loadConversationsと独立管理）
  const msgTransientErrorCountRef = useRef(0);

  // ---------------------------------------------------------------------------
  // カルテパネル開閉（iOSスクロール貫通対策: 開閉時に body.overflow を制御）
  // ---------------------------------------------------------------------------
  const openKartePanel = useCallback(() => {
    setShowKartePanel(true);
    document.body.style.overflow = "hidden";
  }, []);
  const closeKartePanel = useCallback(() => {
    setShowKartePanel(false);
    document.body.style.overflow = "";
  }, []);

  // ---------------------------------------------------------------------------
  // データ取得
  // ---------------------------------------------------------------------------

  const loadConversations = useCallback(async () => {
    setConvError("");
    try {
      const data = await listConversations({
        platform: platformFilter === "all" ? undefined : platformFilter,
        unread_only: unreadOnly,
        page_id: pageIdFilter || undefined,
      });
      setConversations(data.conversations || []);
      setAvatarErrors(new Set()); // 新しい会話一覧取得時にアバターエラー状態をリセット
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
        if (transientErrorCountRef.current < 3) return; // 2回まで抑制（デプロイ60秒窓をカバー）
        // 3回目以降は本物の障害としてバナー表示
      } else {
        transientErrorCountRef.current = 0;
      }

      const msg = e instanceof ApiError
        ? e.message
        : t("inbox.fetchError");
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
      msgTransientErrorCountRef.current = 0; // 成功時リセット
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setMsgError("Lead not found.");
        msgTransientErrorCountRef.current = 0;
      } else {
        const isTransient =
          (e instanceof TypeError) ||
          (e instanceof ApiError && (e.status === 502 || e.status === 503));
        if (isTransient) {
          msgTransientErrorCountRef.current += 1;
          console.warn(`[InboxPage] loadMessages transient error #${msgTransientErrorCountRef.current}:`, e instanceof Error ? e.message : e);
          if (msgTransientErrorCountRef.current < 3) return; // 2回まで抑制（デプロイ60秒窓をカバー）
        } else {
          msgTransientErrorCountRef.current = 0;
        }
        const msg = e instanceof ApiError
          ? e.message
          : t("inbox.fetchError");
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
      setCardSaveError(e instanceof Error ? e.message : t("common.saveError"));
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
    msgTransientErrorCountRef.current = 0; // lead切替時にリセット（前リードのエラーカウントを引き継がない）
    closeKartePanel(); // モバイルドロワーはリード切替時に閉じる（body.overflow も解除）
    setDraft("");
    setSendError("");
    const params = new URLSearchParams(searchParams);
    params.set("lead_id", String(leadId));
    setSearchParams(params, { replace: true });
  }, [closeKartePanel, searchParams, setSearchParams]);

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
        // ステータスタブによるフィルタ
        const tab = STATUS_TABS.find((t) => t.key === statusTab);
        if (!tab || !tab.statuses) return true; // "all" タブは全件表示
        return (tab.statuses as readonly string[]).includes(c.lead_status ?? "");
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
  }, [conversations, statusTab, unreadOnly, followUpOnly, searchQuery]);

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

  // プロフィールモーダル: ESCキー + 初期フォーカス
  useEffect(() => {
    if (!showProfileModal) return;
    const first = profileModalRef.current?.querySelector<HTMLElement>(
      "button, input, select, textarea"
    );
    first?.focus();
    const onEsc = (e: Event) => {
      if ((e as { key?: string }).key === "Escape") setShowProfileModal(false);
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [showProfileModal]);

  // 全て既読にする（現在フィルタ済みの未読会話を一括既読化）
  const handleMarkAllRead = useCallback(async () => {
    setManageOpen(false);
    const unreadConvs = filteredConversations.filter((c) => c.unread_count > 0);
    await Promise.all(unreadConvs.map((c) => markRead(c.lead_id)));
  }, [filteredConversations, markRead]);

  const handleMarkUnread = useCallback(() => {
    if (!selectedLeadId) return;
    setConversations((prev) =>
      prev.map((c) => c.lead_id === selectedLeadId ? { ...c, unread_count: 1 } : c)
    );
  }, [selectedLeadId]);

  const handleExclude = useCallback(async () => {
    if (!selectedLeadId) return;
    try {
      await api.patch<void>(`/leads/${selectedLeadId}`, { status: "対象外" });
      setConversations((prev) => prev.filter((c) => c.lead_id !== selectedLeadId));
      setSelectedLeadId(null);
    } catch { /* noop */ }
  }, [selectedLeadId]);

  const handleDeleteLead = useCallback(async () => {
    if (!selectedLeadId) return;
    if (!window.confirm(t("inbox.confirmDelete"))) return;
    try {
      await api.delete(`/leads/${selectedLeadId}`);
      setConversations((prev) => prev.filter((c) => c.lead_id !== selectedLeadId));
      setSelectedLeadId(null);
    } catch { /* noop */ }
  }, [selectedLeadId, t]);

  // ---------------------------------------------------------------------------
  // 描画
  // ---------------------------------------------------------------------------

  const settingsBtn = (
    <button
      type="button"
      className="inbox-settings-btn"
      onClick={() => setShowSettings(true)}
      aria-label={t("inbox.settings.title")}
      data-tooltip={t("inbox.settings.tooltip")}
    >
      <NAV_ICONS.settings size={ICON.base} weight="fill" aria-hidden="true" />
    </button>
  );

  return (
    <>
      <PageLayout navKey="nav.leadChat" subtitleKey="inbox.subtitle" noScroll headerAction={settingsBtn}>
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
                    <INBOX_ACTION_ICONS.markUnread size={ICON.sm} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="inbox-header-action-btn"
                    onClick={handleExclude}
                    aria-label={t("inbox.exclude")}
                    data-tooltip={t("inbox.exclude")}
                  >
                    <INBOX_ACTION_ICONS.exclude size={ICON.sm} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="inbox-header-action-btn danger"
                    onClick={handleDeleteLead}
                    aria-label={t("inbox.deleteLead")}
                    data-tooltip={t("inbox.deleteLead")}
                  >
                    <INBOX_ACTION_ICONS.delete size={ICON.sm} aria-hidden="true" />
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
                  className={`right-panel-tab${karteTab === "contact" ? " active" : ""}`}
                  onClick={() => setKarteTab("contact")}
                >{t("inbox.karteContact")}</button>
                <button
                  type="button"
                  className={`right-panel-tab${karteTab === "company" ? " active" : ""}`}
                  onClick={() => setKarteTab("company")}
                >{t("inbox.karteCompany")}</button>
                <button
                  type="button"
                  className={`right-panel-tab${karteTab === "deal" ? " active" : ""}`}
                  onClick={() => setKarteTab("deal")}
                >{t("inbox.karteDeal")}</button>
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
        <div className="inbox-settings-overlay" onClick={() => setShowSettings(false)}>
          <div className="inbox-settings-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="inbox-settings-modal-title">{t("inbox.settings.title")}</h3>

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

      {/* ============================== プロフィールモーダル ============================== */}
      {showProfileModal && leadDetail && (
        <div
          className="inbox-profile-overlay"
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
                className={`right-panel-tab${profileModalTab === "contact" ? " active" : ""}`}
                onClick={() => setProfileModalTab("contact")}
              >{t("inbox.karteContact")}</button>
              <button type="button"
                className={`right-panel-tab${profileModalTab === "company" ? " active" : ""}`}
                onClick={() => setProfileModalTab("company")}
              >{t("inbox.karteCompany")}</button>
              <button type="button"
                className={`right-panel-tab${profileModalTab === "deal" ? " active" : ""}`}
                onClick={() => setProfileModalTab("deal")}
              >{t("inbox.karteDeal")}</button>
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

