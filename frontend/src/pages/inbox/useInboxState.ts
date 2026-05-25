/**
 * useInboxState — 受信箱ページのステート管理フック
 *
 * InboxPage.tsx から抽出（STEP 3-C）。
 * useState / useCallback / useEffect / useMemo / useRef をすべて集約し、
 * InboxPage は JSX レンダリングのみに専念できるようにする。
 */

import { KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { useInboxSSE } from "../../hooks/useInboxSSE";
import { api, ApiError } from "../../lib/api";
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
import {
  DRAFT_KEY,
  FOLLOWUP_EXCLUDED,
  INBOX_SETTINGS_KEY,
  POLL_BACKOFF_FACTOR,
  POLL_INTERVAL_MS,
  POLL_MAX_INTERVAL_MS,
  STATUS_TABS,
  readInboxSettings,
} from "./inbox.types";
import type { InboxSettings, LeadDetail, StatusTabKey } from "./inbox.types";

// ---------------------------------------------------------------------------
// 返却型
// ---------------------------------------------------------------------------

export interface UseInboxStateReturn {
  t: ReturnType<typeof useTranslation>["t"];

  // 会話リスト
  conversations: Conversation[];
  convLoading: boolean;
  convError: string;
  filteredConversations: Conversation[];
  loadConversations: () => Promise<void>;

  // 受信箱設定
  inboxSettings: InboxSettings;
  showSettings: boolean;
  setShowSettings: (v: boolean) => void;
  updateInboxSetting: <K extends keyof InboxSettings>(key: K, value: InboxSettings[K]) => void;

  // フィルタ
  statusTab: StatusTabKey;
  setStatusTab: (v: StatusTabKey) => void;
  platformFilter: PlatformFilter;
  setPlatformFilter: (v: PlatformFilter) => void;
  unreadOnly: boolean;
  setUnreadOnly: (fn: boolean | ((prev: boolean) => boolean)) => void;
  followUpOnly: boolean;
  setFollowUpOnly: (fn: boolean | ((prev: boolean) => boolean)) => void;
  searchQuery: string;
  setSearchQuery: (v: string) => void;
  pageIdFilter: string;
  availablePageIds: string[];
  onPageFilterChange: (value: string) => void;

  // 選択中会話
  selectedLeadId: number | null;
  selectedConversation: Conversation | null;
  selectedPlatform: ReturnType<typeof inferPlatform>;
  messagesData: MessagesResponse | null;
  msgLoading: boolean;
  msgError: string;
  avatarErrors: Set<number>;
  handleAvatarError: (leadId: number) => void;
  selectLead: (leadId: number) => void;

  // 顧客カルテ（右パネル）
  leadDetail: LeadDetail | null;
  cardForm: Partial<LeadDetail>;
  cardSaveStatus: "idle" | "saving" | "saved" | "error";
  cardSaveError: string;
  karteTab: "contact" | "company" | "deal";
  setKarteTab: (v: "contact" | "company" | "deal") => void;
  showKartePanel: boolean;
  openKartePanel: () => void;
  closeKartePanel: () => void;
  showProfileModal: boolean;
  setShowProfileModal: (v: boolean) => void;
  profileModalTab: "contact" | "company" | "deal";
  setProfileModalTab: (v: "contact" | "company" | "deal") => void;
  profileModalRef: RefObject<HTMLDivElement>;
  handleCardFieldChange: (field: keyof LeadDetail, value: unknown) => void;
  handleCardFieldBlur: () => Promise<void>;

  // 送信エリア
  draft: string;
  setDraft: (v: string) => void;
  sending: boolean;
  sendError: string;
  sendDisabled: boolean;
  canSend: boolean;
  trimmedDraft: string;
  messagingWindow: MessagingWindow | undefined;
  submitSend: () => Promise<void>;
  handleKeyDown: (e: KeyboardEvent<HTMLTextAreaElement>) => void;

  // 管理ドロップダウン
  manageOpen: boolean;
  setManageOpen: (fn: boolean | ((prev: boolean) => boolean)) => void;
  manageRef: RefObject<HTMLDivElement>;
  handleMarkAllRead: () => Promise<void>;
  handleMarkUnread: () => void;
  handleExclude: () => Promise<void>;
  handleDeleteLead: () => Promise<void>;

  // スクロール ref
  messageListRef: RefObject<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// フック本体
// ---------------------------------------------------------------------------

export function useInboxState(): UseInboxStateReturn {
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

  // 受信箱設定（localStorage はマウント時1回だけ読む — useRef でキャッシュし再レンダリング時の再読み込みを防ぐ）
  const _settingsCache = useRef<InboxSettings | null>(null);
  if (_settingsCache.current === null) _settingsCache.current = readInboxSettings();
  const initialSettings = _settingsCache.current;
  const [inboxSettings, setInboxSettings] = useState<InboxSettings>(initialSettings);
  const [showSettings, setShowSettings] = useState(false);

  // フィルタ（設定のデフォルト値を反映）
  const [statusTab, setStatusTab] = useState<StatusTabKey>(initialSettings.defaultTab);
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>("all");
  const [unreadOnly, setUnreadOnly] = useState(initialSettings.defaultUnreadOnly);
  const [followUpOnly, setFollowUpOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Phase 1-E F14-S5: Page フィルタ
  const initialPageId = searchParams.get("page_id") || "";
  const [pageIdFilter, setPageIdFilter] = useState<string>(initialPageId);
  const [availablePageIds, setAvailablePageIds] = useState<string[]>([]);

  // 選択中会話
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(initialLeadId);
  const [messagesData, setMessagesData] = useState<MessagesResponse | null>(null);
  const [avatarErrors, setAvatarErrors] = useState<Set<number>>(new Set());
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState("");

  // 右パネル (顧客カルテ)
  const [leadDetail, setLeadDetail] = useState<LeadDetail | null>(null);
  const [cardForm, setCardForm] = useState<Partial<LeadDetail>>({});
  const [cardSaveStatus, setCardSaveStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [cardSaveError, setCardSaveError] = useState("");
  const [karteTab, setKarteTab] = useState<"contact" | "company" | "deal">("deal");
  const [showKartePanel, setShowKartePanel] = useState(false);
  const [showProfileModal, setShowProfileModal] = useState(false);
  const [profileModalTab, setProfileModalTab] = useState<"contact" | "company" | "deal">("deal");
  const profileModalRef = useRef<HTMLDivElement>(null);

  // 入力欄
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");

  // 管理ドロップダウン
  const [manageOpen, setManageOpen] = useState(false);
  const manageRef = useRef<HTMLDivElement>(null);

  // スクロール用 ref
  const messageListRef = useRef<HTMLDivElement>(null);
  const skipNextPollRef = useRef(false);
  const pollErrorCountRef = useRef(0);
  const transientErrorCountRef = useRef(0);
  const msgTransientErrorCountRef = useRef(0);

  // ---------------------------------------------------------------------------
  // カルテパネル開閉（iOSスクロール貫通対策）
  // ---------------------------------------------------------------------------
  const openKartePanel = useCallback(() => {
    setShowKartePanel(true);
    document.body.style.overflow = "hidden";
  }, []);
  const closeKartePanel = useCallback(() => {
    setShowKartePanel(false);
    document.body.style.overflow = "";
  }, []);

  // アンマウント時に body.style.overflow を必ずリセット（ページ遷移時のスクロール固着対策）
  useEffect(() => {
    return () => { document.body.style.overflow = ""; };
  }, []);

  // ---------------------------------------------------------------------------
  // アバターエラー
  // ---------------------------------------------------------------------------
  const handleAvatarError = useCallback((leadId: number) => {
    setAvatarErrors(prev => { const s = new Set(prev); s.add(leadId); return s; });
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
      setAvatarErrors(new Set());
      transientErrorCountRef.current = 0;
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") return;
      const isTransient =
        (e instanceof ApiError && (e.status === 502 || e.status === 503)) ||
        (e instanceof TypeError) ||
        (e instanceof Error && /^HTTP 50[23]/.test(e.message));
      if (isTransient) {
        transientErrorCountRef.current += 1;
        console.warn(`[InboxPage] transient error #${transientErrorCountRef.current}:`, e instanceof Error ? e.message : e);
        if (transientErrorCountRef.current < 3) return;
      } else {
        transientErrorCountRef.current = 0;
      }
      const msg = e instanceof ApiError ? e.message : t("inbox.fetchError");
      setConvError(msg);
    } finally {
      setConvLoading(false);
    }
  }, [platformFilter, unreadOnly, pageIdFilter, t]);

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
      msgTransientErrorCountRef.current = 0;
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
          if (msgTransientErrorCountRef.current < 3) return;
        } else {
          msgTransientErrorCountRef.current = 0;
        }
        const msg = e instanceof ApiError ? e.message : t("inbox.fetchError");
        setMsgError(msg);
      }
      setMessagesData(null);
    } finally {
      setMsgLoading(false);
    }
  }, [t]);

  const loadLeadDetail = useCallback(async (leadId: number) => {
    try {
      const data = await api.get<LeadDetail>(`/leads/${leadId}`);
      setLeadDetail(data);
      try {
        const raw = localStorage.getItem(DRAFT_KEY(leadId));
        if (raw) {
          const savedDraft = JSON.parse(raw) as Partial<LeadDetail>;
          setCardForm({ ...data, ...savedDraft });
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
  }, [leadDetail, cardForm, t]);

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
  // ---------------------------------------------------------------------------

  useInboxSSE({
    onUpdate: useCallback(() => {
      skipNextPollRef.current = true;
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
    return () => { cancelled = true; clearTimeout(timerId); };
  }, [loadConversations, loadMessages, selectedLeadId]);

  // ---------------------------------------------------------------------------
  // lead 選択時 → メッセージ取得 + 既読化 + URL 更新 + 右パネル
  // ---------------------------------------------------------------------------

  const selectLead = useCallback((leadId: number) => {
    setSelectedLeadId(leadId);
    msgTransientErrorCountRef.current = 0;
    closeKartePanel();
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
        const tab = STATUS_TABS.find((tb) => tb.key === statusTab);
        if (!tab || !tab.statuses) return true;
        return (tab.statuses as readonly string[]).includes(c.lead_status ?? "");
      })
      .filter((c) => {
        if (!unreadOnly) return true;
        return (c.unread_count ?? 0) > 0;
      })
      .filter((c) => {
        if (!followUpOnly) return true;
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
  // 選択中会話の派生値
  // ---------------------------------------------------------------------------

  const selectedConversation = useMemo(
    () => conversations.find((c) => c.lead_id === selectedLeadId) || null,
    [conversations, selectedLeadId],
  );

  const selectedPlatform = inferPlatform(messagesData?.lead, selectedConversation);

  // ---------------------------------------------------------------------------
  // 管理ドロップダウン: click-outside で閉じる
  // ---------------------------------------------------------------------------

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

  // ---------------------------------------------------------------------------
  // プロフィールモーダル: ESCキー + 初期フォーカス
  // ---------------------------------------------------------------------------

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

  // ---------------------------------------------------------------------------
  // アクション
  // ---------------------------------------------------------------------------

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
  // 返却
  // ---------------------------------------------------------------------------

  return {
    t,

    // 会話リスト
    conversations,
    convLoading,
    convError,
    filteredConversations,
    loadConversations,

    // 受信箱設定
    inboxSettings,
    showSettings,
    setShowSettings,
    updateInboxSetting,

    // フィルタ
    statusTab,
    setStatusTab,
    platformFilter,
    setPlatformFilter,
    unreadOnly,
    setUnreadOnly,
    followUpOnly,
    setFollowUpOnly,
    searchQuery,
    setSearchQuery,
    pageIdFilter,
    availablePageIds,
    onPageFilterChange,

    // 選択中会話
    selectedLeadId,
    selectedConversation,
    selectedPlatform,
    messagesData,
    msgLoading,
    msgError,
    avatarErrors,
    handleAvatarError,
    selectLead,

    // 顧客カルテ
    leadDetail,
    cardForm,
    cardSaveStatus,
    cardSaveError,
    karteTab,
    setKarteTab,
    showKartePanel,
    openKartePanel,
    closeKartePanel,
    showProfileModal,
    setShowProfileModal,
    profileModalTab,
    setProfileModalTab,
    profileModalRef,
    handleCardFieldChange,
    handleCardFieldBlur,

    // 送信エリア
    draft,
    setDraft,
    sending,
    sendError,
    sendDisabled,
    canSend,
    trimmedDraft,
    messagingWindow,
    submitSend,
    handleKeyDown,

    // 管理ドロップダウン
    manageOpen,
    setManageOpen,
    manageRef,
    handleMarkAllRead,
    handleMarkUnread,
    handleExclude,
    handleDeleteLead,

    // スクロール ref
    messageListRef,
  };
}
