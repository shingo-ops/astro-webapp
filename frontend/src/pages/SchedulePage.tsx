/**
 * スケジュールページ（Google Calendar 連携）
 *
 * 機能:
 *   - GET /google-calendar/status で接続状態を確認
 *   - 接続済み: GET /google-calendar/events + GET /shifts を並列取得 → react-big-calendar に表示
 *   - 未接続 + admin: 接続バナーを表示（クリックで OAuth フロー開始）
 *   - イベントのクリック / スロットのクリックで EventModal を表示
 *   - イベント作成 / 更新 / 削除の CRUD 対応
 *   - 既存 Shifts は緑色、Google Calendar イベントは青色で色分け
 *
 * ADR-027: 全 UI 文字列は t() 経由
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Calendar, dateFnsLocalizer, Views } from "react-big-calendar";
import { format, parse, startOfWeek, getDay } from "date-fns";
import { ja } from "date-fns/locale";
import "react-big-calendar/lib/css/react-big-calendar.css";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";
import { PageLayout } from "../components/PageLayout";

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

interface CalendarStatus {
  connected: boolean;
  calendar_id: string | null;
  connected_at: string | null;
}

interface GoogleEvent {
  id: string;
  summary?: string;
  start: { dateTime?: string; date?: string };
  end: { dateTime?: string; date?: string };
  description?: string;
  location?: string;
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
  source: "google" | "shift";
  raw?: GoogleEvent;
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

function toDate(dt?: string, d?: string): Date | null {
  if (dt) return new Date(dt);
  if (d) return new Date(`${d}T00:00:00`);
  return null;
}

function toRfc3339(date: Date): string {
  return date.toISOString();
}

function rangeOf(view: string, date: Date): { start: Date; end: Date } {
  const d = new Date(date);
  if (view === Views.MONTH) {
    const start = new Date(d.getFullYear(), d.getMonth(), 1);
    start.setDate(start.getDate() - 7); // 前後1週バッファ
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

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function toTimeInput(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
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
  const editable = canEdit && !isShift && (isNew || event?.source === "google");

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
        <h3>{isNew ? t("schedule.addEvent") : (editable ? t("schedule.editEvent") : event?.title ?? t("schedule.noTitle"))}</h3>

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
              <div style={{ display: "flex", gap: "8px" }}>
                <input type="date" value={form.startDate} onChange={(e) => setForm({ ...form, startDate: e.target.value })} />
                <input type="time" value={form.startTime} onChange={(e) => setForm({ ...form, startTime: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label>{t("schedule.eventEnd")}</label>
              <div style={{ display: "flex", gap: "8px" }}>
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
          <div style={{ padding: "8px 0" }}>
            {event?.raw?.description && <p>{event.raw.description}</p>}
            {event?.raw?.location && <p>{event.raw.location}</p>}
            {isShift && <p>({t("schedule.shiftLabel")})</p>}
          </div>
        )}

        {error && <div className="error-message">{error}</div>}

        {confirmDelete ? (
          <div className="form-actions">
            <span style={{ flex: 1, color: "var(--color-error, red)", fontSize: "14px" }}>
              {t("schedule.deleteEventConfirm")}
            </span>
            <button className="btn-danger" onClick={handleDelete} disabled={deleting}>
              {deleting ? t("common.saving") : t("common.delete")}
            </button>
            <button className="btn-secondary" onClick={() => setConfirmDelete(false)}>{t("common.cancel")}</button>
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
              <button className="btn-primary" onClick={handleSave} disabled={saving || !form.summary.trim()}>
                {saving ? t("common.saving") : t("common.save")}
              </button>
            )}
            <button className="btn-secondary" onClick={onClose}>{t("common.close")}</button>
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

  const [status, setStatus] = useState<CalendarStatus | null>(null);
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [loadingStatus, setLoadingStatus] = useState(true);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);

  const [currentView, setCurrentView] = useState<string>(Views.MONTH);
  const [currentDate, setCurrentDate] = useState(new Date());

  const [modalEvent, setModalEvent] = useState<CalEvent | null>(null);
  const [isNewEvent, setIsNewEvent] = useState(false);
  const [newSlot, setNewSlot] = useState<{ start: Date; end: Date } | null>(null);

  const loadingRef = useRef(false);

  // URL クエリからバナー表示
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
  }, []);

  // 接続状態確認
  useEffect(() => {
    api.get<CalendarStatus>("/google-calendar/status")
      .then((s) => setStatus(s))
      .catch(() => setStatus({ connected: false, calendar_id: null, connected_at: null }))
      .finally(() => setLoadingStatus(false));
  }, []);

  // イベント取得
  const loadEvents = useCallback(async (view: string, date: Date) => {
    if (!status?.connected || loadingRef.current) return;
    loadingRef.current = true;
    setLoadingEvents(true);

    const { start, end } = rangeOf(view, date);
    try {
      const [gcRes, shiftsRes] = await Promise.allSettled([
        api.get<{ events: GoogleEvent[] }>(
          `/google-calendar/events?start=${toRfc3339(start)}&end=${toRfc3339(end)}`
        ),
        api.get<Shift[]>("/shifts"),
      ]);

      const gcEvents: CalEvent[] = [];
      if (gcRes.status === "fulfilled") {
        for (const ev of gcRes.value.events) {
          const s = toDate(ev.start?.dateTime, ev.start?.date);
          const e = toDate(ev.end?.dateTime, ev.end?.date);
          if (s && e) {
            gcEvents.push({
              id: ev.id,
              title: ev.summary ?? t("schedule.noTitle"),
              start: s,
              end: e,
              source: "google",
              raw: ev,
            });
          }
        }
      }

      const shiftEvents: CalEvent[] = [];
      if (shiftsRes.status === "fulfilled") {
        for (const sh of shiftsRes.value) {
          const s = new Date(`${sh.shift_date}T${sh.start_time}`);
          const e = new Date(`${sh.shift_date}T${sh.end_time}`);
          shiftEvents.push({
            id: `shift-${sh.id}`,
            title: `[${t("schedule.shiftLabel")}] ${sh.shift_type}`,
            start: s,
            end: e,
            source: "shift",
          });
        }
      }

      setEvents([...gcEvents, ...shiftEvents]);
    } finally {
      setLoadingEvents(false);
      loadingRef.current = false;
    }
  }, [status, t]);

  useEffect(() => {
    if (status?.connected) {
      loadEvents(currentView, currentDate);
    }
  }, [status]);

  const handleNavigate = (date: Date) => {
    setCurrentDate(date);
    loadEvents(currentView, date);
  };

  const handleViewChange = (view: string) => {
    setCurrentView(view);
    loadEvents(view, currentDate);
  };

  // OAuth 接続開始
  const handleConnect = async () => {
    setConnecting(true);
    try {
      const { auth_url } = await api.get<{ auth_url: string }>("/google-calendar/connect/start");
      window.location.href = auth_url;
    } catch {
      setBanner({ type: "error", message: t("schedule.connectError") });
      setConnecting(false);
    }
  };

  // 接続解除
  const handleDisconnect = async () => {
    if (!window.confirm(t("schedule.disconnectConfirm"))) return;
    setDisconnecting(true);
    try {
      await api.delete("/google-calendar/connect");
      setStatus({ connected: false, calendar_id: null, connected_at: null });
      setEvents([]);
    } finally {
      setDisconnecting(false);
    }
  };

  // イベント保存（作成 / 更新）
  const handleSave = async (form: EventFormState, id?: string) => {
    const body = {
      summary: form.summary,
      start: { dateTime: `${form.startDate}T${form.startTime}:00`, timeZone: "Asia/Tokyo" },
      end: { dateTime: `${form.endDate}T${form.endTime}:00`, timeZone: "Asia/Tokyo" },
      description: form.description || undefined,
      location: form.location || undefined,
    };
    if (id) {
      await api.patch(`/google-calendar/events/${id}`, body);
    } else {
      await api.post("/google-calendar/events", body);
    }
    await loadEvents(currentView, currentDate);
  };

  // イベント削除
  const handleDelete = async (id: string) => {
    await api.delete(`/google-calendar/events/${id}`);
    await loadEvents(currentView, currentDate);
  };

  // カレンダーイベントの色分け
  const eventStyleGetter = (event: CalEvent) => {
    const isShift = event.source === "shift";
    return {
      style: {
        backgroundColor: isShift ? "var(--success)" : "var(--accent)",
        borderColor: isShift ? "var(--success)" : "var(--accent)",
        color: "#fff",
        borderRadius: "4px",
        border: "none",
        opacity: 0.9,
      },
    };
  };

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
      {/* バナー */}
      {banner && (
        <div
          className={banner.type === "success" ? "success-banner" : "error-banner"}
          style={{ marginBottom: "16px" }}
        >
          {banner.message}
          <button
            onClick={() => setBanner(null)}
            style={{ marginLeft: "12px", background: "none", border: "none", cursor: "pointer", color: "inherit" }}
            aria-label={t("common.close")}
          >
            ×
          </button>
        </div>
      )}

      {loadingStatus ? (
        <div className="loading-indicator">{t("schedule.loading")}</div>
      ) : (
        <>
          {/* 未接続バナー */}
          {!status?.connected && (
            <div
              style={{
                background: "var(--bg-subtle)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                padding: "24px",
                textAlign: "center",
                marginBottom: "16px",
              }}
            >
              <p style={{ fontWeight: 600, marginBottom: "8px" }}>{t("schedule.notConnected")}</p>
              <p style={{ color: "var(--text-secondary)", marginBottom: "16px" }}>
                {t("schedule.notConnectedDesc")}
              </p>
              {canManage && (
                <button className="btn-primary" onClick={handleConnect} disabled={connecting}>
                  {connecting ? t("common.saving") : t("schedule.connect")}
                </button>
              )}
            </div>
          )}

          {/* 接続済みヘッダー */}
          {status?.connected && canManage && (
            <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "12px" }}>
              <button className="btn-secondary" onClick={handleDisconnect} disabled={disconnecting}>
                {disconnecting ? t("common.saving") : t("schedule.disconnect")}
              </button>
            </div>
          )}

          {/* カレンダー */}
          {status?.connected && (
            <div style={{ height: "calc(100vh - 220px)", minHeight: "500px" }}>
              {loadingEvents && (
                <div
                  style={{
                    position: "absolute",
                    top: "50%",
                    left: "50%",
                    transform: "translate(-50%,-50%)",
                    background: "rgba(255,255,255,0.8)",
                    padding: "12px 24px",
                    borderRadius: "8px",
                    zIndex: 10,
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
                view={currentView as Parameters<typeof Calendar>[0]["view"]}
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
                  if (!status?.connected) return;
                  setModalEvent(null);
                  setIsNewEvent(true);
                  setNewSlot({ start: slot.start as Date, end: slot.end as Date });
                }}
                selectable={status?.connected}
                popup
              />
            </div>
          )}
        </>
      )}

      {/* イベントモーダル */}
      {(modalEvent || isNewEvent) && (
        <EventModal
          event={modalEvent}
          isNew={isNewEvent}
          initialSlot={newSlot}
          canEdit={canManage && status?.connected === true}
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
