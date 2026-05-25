/**
 * スケジュールページ（アプリ内カレンダー + Google Calendar 双方向同期）
 *
 * 機能:
 *   - GET /calendar/events でアプリ DB のイベントを表示（Google 未接続でも動作）
 *   - GET /shifts を並列取得し、シフト（緑）と予定（青）を色分け表示
 *   - Google Calendar 接続ステータスバーを常時表示
 *   - イベントの作成 / 更新 / 削除（DB 経由 → Google に自動同期）
 *   - Google Calendar デザイン準拠 UI（schedule.css オーバーライド）
 *
 * ADR-027: 全 UI 文字列は t() 経由
 * ADR-067: デザイントークン参照のみ（ハードコード禁止）
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Calendar, dateFnsLocalizer, Views, type View, type ToolbarProps } from "react-big-calendar";
import { format, parse, startOfWeek, getDay } from "date-fns";
import { ja } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
import "../schedule.css";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";
import { GoogleCalendarStatusBar } from "../../components/GoogleCalendarStatusBar";

// ---------------------------------------------------------------------------
// date-fns ローカライザー設定
// ---------------------------------------------------------------------------

const locales = { ja };
const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek: () => startOfWeek(new Date(), { weekStartsOn: 1 }),
  getDay,
  locales,
});

// ---------------------------------------------------------------------------
// 型定義
// ---------------------------------------------------------------------------

interface AppEvent {
  id: number;
  calendar_type: "shared" | "personal";
  title: string;
  description: string | null;
  location: string | null;
  start_datetime: string;
  end_datetime: string;
  is_all_day: boolean;
  source: "app" | "google";
  sync_status: "synced" | "pending" | "failed";
  created_by_user_id: number;
}

interface Shift {
  id: number;
  shift_date: string;
  start_time: string;
  end_time: string;
  shift_type: string;
  notes: string | null;
}

interface CalEvent {
  id: string;
  title: string;
  start: Date;
  end: Date;
  source: "app" | "google" | "shift";
  raw?: AppEvent;
}

interface EventFormState {
  summary: string;
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
  description: string;
  location: string;
}

// ---------------------------------------------------------------------------
// ユーティリティ
// ---------------------------------------------------------------------------

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function toTimeInput(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toRfc3339(date: Date): string {
  return date.toISOString();
}

function rangeOf(view: string, date: Date): { start: Date; end: Date } {
  const d = new Date(date);
  if (view === Views.MONTH) {
    const start = new Date(d.getFullYear(), d.getMonth(), 1);
    start.setDate(start.getDate() - 7);
    const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    end.setDate(end.getDate() + 7);
    return { start, end };
  }
  if (view === Views.WEEK) {
    const start = startOfWeek(d, { weekStartsOn: 1 });
    const end = new Date(start);
    end.setDate(end.getDate() + 7);
    return { start, end };
  }
  // day
  const start = new Date(d);
  start.setHours(0, 0, 0, 0);
  const end = new Date(d);
  end.setHours(23, 59, 59, 999);
  return { start, end };
}

// ---------------------------------------------------------------------------
// GCalToolbar（Google Calendar デザイン準拠ツールバー）
// ---------------------------------------------------------------------------

interface GCalToolbarProps {
  label: string;
  view: View;
  views: View[];
  onNavigate: (action: "PREV" | "NEXT" | "TODAY") => void;
  onView: (view: View) => void;
  onCreateEvent: () => void;
}

function GCalToolbar({ label, view, views, onNavigate, onView, onCreateEvent }: GCalToolbarProps) {
  const { t } = useTranslation();
  const viewLabels: Record<string, string> = {
    month: t("schedule.monthView"),
    week: t("schedule.weekView"),
    day: t("schedule.dayView"),
  };

  return (
    <div className="gcal-toolbar">
      <button className="gcal-toolbar__create" onClick={onCreateEvent}>
        <span className="gcal-toolbar__create-icon" aria-hidden="true">+</span>
        {t("schedule.addEvent")}
      </button>

      <div className="gcal-toolbar__nav">
        <button className="gcal-toolbar__today-btn" onClick={() => onNavigate("TODAY")}>
          {t("schedule.today")}
        </button>
        <button
          className="gcal-toolbar__arrow"
          onClick={() => onNavigate("PREV")}
          aria-label={t("schedule.prevPeriod")}
        >
          ‹
        </button>
        <button
          className="gcal-toolbar__arrow"
          onClick={() => onNavigate("NEXT")}
          aria-label={t("schedule.nextPeriod")}
        >
          ›
        </button>
      </div>

      <span className="gcal-toolbar__label">{label}</span>

      <div className="gcal-toolbar__views">
        {views.map((v) => (
          <button
            key={v}
            className={`gcal-toolbar__view-btn${v === view ? " active" : ""}`}
            onClick={() => onView(v)}
          >
            {viewLabels[v as string] ?? v}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EventModal
// ---------------------------------------------------------------------------

interface EventModalProps {
  event: CalEvent | null;
  isNew: boolean;
  initialSlot: { start: Date; end: Date } | null;
  canEdit: boolean;
  onClose: () => void;
  onSave: (form: EventFormState, id?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

function EventModal({ event, isNew, initialSlot, canEdit, onClose, onSave, onDelete }: EventModalProps) {
  const { t } = useTranslation();
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState("");

  const defaultStart = initialSlot?.start ?? event?.start ?? new Date();
  const defaultEnd = initialSlot?.end ?? event?.end ?? new Date();

  const [form, setForm] = useState<EventFormState>({
    summary: isNew ? "" : (event?.title ?? ""),
    startDate: toDateInput(defaultStart),
    startTime: toTimeInput(defaultStart),
    endDate: toDateInput(defaultEnd),
    endTime: toTimeInput(defaultEnd),
    description: isNew ? "" : (event?.raw?.description ?? ""),
    location: isNew ? "" : (event?.raw?.location ?? ""),
  });

  const isShift = event?.source === "shift";
  const editable = canEdit && !isShift && (isNew || event != null);

  const handleSave = async () => {
    setError("");
    setSaving(true);
    try {
      await onSave(form, isNew ? undefined : event?.id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!event?.id) return;
    setError("");
    setDeleting(true);
    try {
      await onDelete(event.id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          {isNew
            ? t("schedule.addEvent")
            : editable
            ? t("schedule.editEvent")
            : (event?.title ?? t("schedule.noTitle"))}
        </h3>

        {editable ? (
          <>
            <div className="form-group">
              <label>{t("schedule.eventTitle")}</label>
              <input
                type="text"
                value={form.summary}
                onChange={(e) => setForm({ ...form, summary: e.target.value })}
                required
              />
            </div>
            <div className="form-group">
              <label>{t("schedule.eventStart")}</label>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <input type="date" value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} />
                <input type="time" value={form.startTime} onChange={(e) => setForm({ ...form, startTime: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label>{t("schedule.eventEnd")}</label>
              <div style={{ display: "flex", gap: "var(--space-2)" }}>
                <input type="date" value={form.endDate} onChange={(e) => setForm({ ...form, endDate: e.target.value })} />
                <input type="time" value={form.endTime} onChange={(e) => setForm({ ...form, endTime: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label>{t("schedule.eventDescription")}</label>
              <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={3} />
            </div>
            <div className="form-group">
              <label>{t("schedule.eventLocation")}</label>
              <input type="text" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
            </div>
          </>
        ) : (
          <div style={{ padding: "var(--space-2) 0" }}>
            {event?.raw?.description && <p>{event.raw.description}</p>}
            {event?.raw?.location && <p>{event.raw.location}</p>}
            {isShift && <p>({t("schedule.shiftLabel")})</p>}
          </div>
        )}

        {error && <div className="error-message">{error}</div>}

        {confirmDelete ? (
          <div className="form-actions">
            <span style={{ flex: 1, color: "var(--danger)", fontSize: "var(--font-sm)" }}>
              {t("schedule.deleteEventConfirm")}
            </span>
            <button className="btn-danger" onClick={handleDelete} disabled={deleting}>
              {deleting ? t("common.saving") : t("common.delete")}
            </button>
            <button className="btn-secondary" onClick={() => setConfirmDelete(false)}>
              {t("common.cancel")}
            </button>
          </div>
        ) : (
          <div className="form-actions">
            {editable && !isNew && (
              <button
                className="btn-danger"
                style={{ marginRight: "auto" }}
                onClick={() => setConfirmDelete(true)}
              >
                {t("schedule.deleteEvent")}
              </button>
            )}
            {editable && (
              <button
                className="btn-primary"
                onClick={handleSave}
                disabled={saving || !form.summary.trim()}
              >
                {saving ? t("common.saving") : t("common.save")}
              </button>
            )}
            <button className="btn-secondary" onClick={onClose}>
              {t("common.close")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SchedulePage
// ---------------------------------------------------------------------------

export default function SchedulePage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [searchParams, setSearchParams] = useSearchParams();

  const canManage = hasPermission("channels.manage");

  const [events, setEvents] = useState<CalEvent[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const [currentView, setCurrentView] = useState<View>(Views.MONTH);
  const [currentDate, setCurrentDate] = useState(new Date());

  const [modalEvent, setModalEvent] = useState<CalEvent | null>(null);
  const [isNewEvent, setIsNewEvent] = useState(false);
  const [newSlot, setNewSlot] = useState<{ start: Date; end: Date } | null>(null);

  const loadingRef = useRef(false);

  // URL クエリからバナー表示（Google OAuth コールバック後）
  useEffect(() => {
    const connected = searchParams.get("connected");
    if (connected === "true") {
      setBanner({ type: "success", message: t("schedule.connectSuccess") });
    } else if (connected === "false") {
      setBanner({ type: "error", message: t("schedule.connectError") });
    }
    if (connected) {
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // イベント取得（DB 経由 — Google 未接続でも動作）
  const loadEvents = useCallback(async (view: View, date: Date) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadingEvents(true);

    const { start, end } = rangeOf(view, date);
    try {
      const [evRes, shiftsRes] = await Promise.allSettled([
        api.get<{ events: AppEvent[] }>(
          `/calendar/events?start=${toRfc3339(start)}&end=${toRfc3339(end)}`
        ),
        api.get<Shift[]>("/shifts"),
      ]);

      const calEvents: CalEvent[] = [];

      if (evRes.status === "fulfilled") {
        for (const ev of evRes.value.events) {
          calEvents.push({
            id: String(ev.id),
            title: ev.title,
            start: new Date(ev.start_datetime),
            end: new Date(ev.end_datetime),
            source: ev.source,
            raw: ev,
          });
        }
      }

      if (shiftsRes.status === "fulfilled") {
        for (const sh of shiftsRes.value) {
          calEvents.push({
            id: `shift-${sh.id}`,
            title: `[${t("schedule.shiftLabel")}] ${sh.shift_type}`,
            start: new Date(`${sh.shift_date}T${sh.start_time}`),
            end: new Date(`${sh.shift_date}T${sh.end_time}`),
            source: "shift",
          });
        }
      }

      setEvents(calEvents);
    } finally {
      setLoadingEvents(false);
      loadingRef.current = false;
    }
  }, [t]);

  useEffect(() => {
    loadEvents(currentView, currentDate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNavigate = (date: Date) => {
    setCurrentDate(date);
    loadEvents(currentView, date);
  };

  const handleViewChange = (view: View) => {
    setCurrentView(view);
    loadEvents(view, currentDate);
  };

  // Google OAuth 接続開始（未連携 / 再接続共通）
  const handleGoogleConnect = async () => {
    const { auth_url } = await api.get<{ auth_url: string }>("/google-calendar/connect/start");
    window.location.href = auth_url;
  };

  // イベント保存（作成 / 更新）
  const handleSave = async (form: EventFormState, id?: string) => {
    const body = {
      title: form.summary,
      start_datetime: `${form.startDate}T${form.startTime}:00`,
      end_datetime: `${form.endDate}T${form.endTime}:00`,
      calendar_type: "shared" as const,
      description: form.description || undefined,
      location: form.location || undefined,
    };
    if (id) {
      await api.patch(`/calendar/events/${id}`, body);
    } else {
      await api.post("/calendar/events", body);
    }
    await loadEvents(currentView, currentDate);
  };

  // イベント削除
  const handleDelete = async (id: string) => {
    await api.delete(`/calendar/events/${id}`);
    await loadEvents(currentView, currentDate);
  };

  // イベント色分け（ADR-067 準拠: CSS 変数のみ使用）
  const eventStyleGetter = (event: CalEvent) => {
    const isShift = event.source === "shift";
    return {
      style: {
        backgroundColor: isShift ? "var(--success)" : "var(--calendar-google-blue)",
        color: "var(--on-accent)",
        opacity: "var(--opacity-soft)",
      },
    };
  };

  // カスタムツールバー用 create ハンドラ（ref で安定参照）
  const createHandlerRef = useRef<() => void>(() => {});
  createHandlerRef.current = () => {
    setModalEvent(null);
    setIsNewEvent(true);
    setNewSlot(null);
  };

  // react-big-calendar に渡す安定なツールバーコンポーネント
  // props 型は react-big-calendar 内部型のため any を使用
  const CustomToolbar = useMemo(() => {
    return function Toolbar({ label, view, views, onNavigate, onView }: ToolbarProps<CalEvent, object>) {
      return (
        <GCalToolbar
          label={label}
          view={view}
          views={views as View[]}
          onNavigate={onNavigate}
          onView={onView}
          onCreateEvent={() => createHandlerRef.current()}
        />
      );
    };
  }, []);

  const messages = {
    month: t("schedule.monthView"),
    week: t("schedule.weekView"),
    day: t("schedule.dayView"),
    today: t("schedule.today"),
    next: "›",
    previous: "‹",
    showMore: (total: number) => `+${total}`,
  };

  return (
    <PageLayout navKey="nav.schedule" subtitleKey="schedule.subtitle">
      {/* Google Calendar 接続ステータスバー（常時表示） */}
      <GoogleCalendarStatusBar
        onReconnect={handleGoogleConnect}
        onConnect={handleGoogleConnect}
        canManage={canManage}
      />

      {/* OAuth コールバック後バナー */}
      {banner && (
        <div
          className={banner.type === "success" ? "success-banner" : "error-banner"}
          style={{ marginBottom: "var(--space-4)" }}
        >
          {banner.message}
          <button
            onClick={() => setBanner(null)}
            style={{
              marginLeft: "var(--space-3)",
              background: "none",
              border: "none",
              cursor: "pointer",
              color: "inherit",
            }}
            aria-label={t("common.close")}
          >
            ×
          </button>
        </div>
      )}

      {/* カレンダー本体（常時表示 — Google 未接続でも DB からイベントを表示） */}
      <div
        style={{
          height: "calc(100vh - 260px)",
          minHeight: "500px",
          position: "relative",
        }}
      >
        {loadingEvents && (
          <div
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              transform: "translate(-50%, -50%)",
              background: "var(--bg-surface)",
              padding: "var(--space-3) var(--space-6)",
              borderRadius: "var(--radius-md)",
              boxShadow: "var(--shadow-md)",
              zIndex: 10,
              fontSize: "var(--font-sm)",
              color: "var(--text-secondary)",
            }}
          >
            {t("schedule.loading")}
          </div>
        )}

        <Calendar
          localizer={localizer}
          events={events}
          startAccessor="start"
          endAccessor="end"
          culture="ja"
          messages={messages}
          view={currentView}
          onView={handleViewChange}
          date={currentDate}
          onNavigate={handleNavigate}
          style={{ height: "100%" }}
          eventPropGetter={eventStyleGetter}
          onSelectEvent={(event) => {
            setModalEvent(event as CalEvent);
            setIsNewEvent(false);
            setNewSlot(null);
          }}
          onSelectSlot={(slot) => {
            setModalEvent(null);
            setIsNewEvent(true);
            setNewSlot({ start: slot.start as Date, end: slot.end as Date });
          }}
          selectable
          popup
          components={{ toolbar: CustomToolbar }}
        />
      </div>

      {/* イベントモーダル */}
      {(modalEvent || isNewEvent) && (
        <EventModal
          event={modalEvent}
          isNew={isNewEvent}
          initialSlot={newSlot}
          canEdit={canManage}
          onClose={() => {
            setModalEvent(null);
            setIsNewEvent(false);
            setNewSlot(null);
          }}
          onSave={handleSave}
          onDelete={handleDelete}
        />
      )}
    </PageLayout>
  );
}
