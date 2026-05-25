/**
 * スケジュールページ（アプリ内カレンダー + Google Calendar 双方向同期）
 *
 * 機能:
 *   - GET /calendar/events でアプリ DB のイベントを表示（Google 未接続でも動作）
 *   - GET /shifts を並列取得し、シフト（緑）と予定（青）を色分け表示
 *   - Google Calendar 接続ステータスバーを常時表示
 *   - イベントの作成 / 更新 / 削除（DB 経由 → Google に自動同期）
 *   - FullCalendar による Google Calendar クローン UI（週/月/日ビュー）
 *
 * ADR-027: 全 UI 文字列は t() 経由
 * ADR-067: デザイントークン参照のみ（ハードコード禁止）
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import timeGridPlugin from "@fullcalendar/timegrid";
import interactionPlugin from "@fullcalendar/interaction";
import type { EventClickArg, DateSelectArg, DatesSetArg } from "@fullcalendar/core";
import "../schedule.css";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";
import { GoogleCalendarStatusBar, type SyncStatus } from "../../components/GoogleCalendarStatusBar";

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

// FullCalendar に渡すイベント形式
interface FCEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  allDay?: boolean;
  classNames: string[];
  extendedProps: {
    source: "app" | "google" | "shift";
    raw?: AppEvent;
  };
}

// EventModal に渡すイベント形式（Date 型が必要）
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

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

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

  const [events, setEvents] = useState<FCEvent[]>([]);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [banner, setBanner] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const [calMonthLabel, setCalMonthLabel] = useState("");
  const [calView, setCalView] = useState("timeGridWeek");
  const [gcalStatus, setGcalStatus] = useState<SyncStatus>("loading");
  const calendarRef = useRef<FullCalendar>(null);

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
  const loadEvents = useCallback(async (startStr: string, endStr: string) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadingEvents(true);

    try {
      const [evRes, shiftsRes] = await Promise.allSettled([
        api.get<{ events: AppEvent[] }>(`/calendar/events?start=${startStr}&end=${endStr}`),
        api.get<Shift[]>("/shifts"),
      ]);

      const calEvents: FCEvent[] = [];

      if (evRes.status === "fulfilled") {
        for (const ev of evRes.value.events) {
          calEvents.push({
            id: String(ev.id),
            title: ev.title,
            start: ev.start_datetime,
            end: ev.end_datetime,
            allDay: ev.is_all_day,
            classNames: ["fc-event--app"],
            extendedProps: { source: ev.source, raw: ev },
          });
        }
      }

      if (shiftsRes.status === "fulfilled") {
        for (const sh of shiftsRes.value) {
          calEvents.push({
            id: `shift-${sh.id}`,
            title: `[${t("schedule.shiftLabel")}] ${sh.shift_type}`,
            start: `${sh.shift_date}T${sh.start_time}`,
            end: `${sh.shift_date}T${sh.end_time}`,
            classNames: ["fc-event--shift"],
            extendedProps: { source: "shift" },
          });
        }
      }

      setEvents(calEvents);
    } finally {
      setLoadingEvents(false);
      loadingRef.current = false;
    }
  }, [t]);

  // FullCalendar のビュー変更 / ナビゲーション時に呼ばれる（初回マウント含む）
  const handleDatesSet = useCallback((arg: DatesSetArg) => {
    setCalView(arg.view.type);
    setCalMonthLabel(
      new Intl.DateTimeFormat("ja-JP", { year: "numeric", month: "long" }).format(arg.view.activeStart)
    );
    loadEvents(arg.startStr, arg.endStr);
  }, [loadEvents]);

  // 現在表示中の範囲でリロード（イベント保存・削除後）
  const reloadCurrentView = useCallback(() => {
    const calApi = calendarRef.current?.getApi();
    if (!calApi) return;
    loadEvents(
      calApi.view.activeStart.toISOString(),
      calApi.view.activeEnd.toISOString(),
    );
  }, [loadEvents]);

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
    reloadCurrentView();
  };

  // イベント削除
  const handleDelete = async (id: string) => {
    await api.delete(`/calendar/events/${id}`);
    reloadCurrentView();
  };

  // ツールバー ナビゲーション
  const handleToolbarNavigate = (action: "PREV" | "NEXT" | "TODAY") => {
    const calApi = calendarRef.current?.getApi();
    if (!calApi) return;
    if (action === "PREV") calApi.prev();
    else if (action === "NEXT") calApi.next();
    else calApi.today();
  };

  // ツールバー ビュー切り替え
  const handleToolbarView = (viewName: string) => {
    calendarRef.current?.getApi().changeView(viewName);
  };

  // イベントクリック → モーダル表示
  const handleEventClick = (arg: EventClickArg) => {
    setModalEvent({
      id: arg.event.id,
      title: arg.event.title,
      start: arg.event.start ?? new Date(),
      end: arg.event.end ?? arg.event.start ?? new Date(),
      source: arg.event.extendedProps.source as "app" | "google" | "shift",
      raw: arg.event.extendedProps.raw as AppEvent | undefined,
    });
    setIsNewEvent(false);
    setNewSlot(null);
  };

  // スロット選択 → 新規イベントモーダル
  const handleSelect = (arg: DateSelectArg) => {
    setModalEvent(null);
    setIsNewEvent(true);
    setNewSlot({ start: arg.start, end: arg.end });
  };

  const gcalConnectBtnClass =
    gcalStatus === "connected"
      ? "gcal-connect-btn gcal-connect-btn--connected"
      : gcalStatus === "disconnected"
      ? "gcal-connect-btn gcal-connect-btn--error"
      : "gcal-connect-btn";

  const gcalConnectBtnLabel =
    gcalStatus === "connected"
      ? t("schedule.connectBtnConnected")
      : gcalStatus === "disconnected"
      ? t("schedule.connectBtnError")
      : t("schedule.connectBtn");

  return (
    <PageLayout
      navKey="nav.schedule"
      headerLeft={
        <div className="schedule-header-nav">
          <button className="gcal-nav__today" onClick={() => handleToolbarNavigate("TODAY")}>
            {t("schedule.today")}
          </button>
          <button
            className="gcal-nav__arrow"
            onClick={() => handleToolbarNavigate("PREV")}
            aria-label={t("schedule.prevPeriod")}
          >
            ‹
          </button>
          <button
            className="gcal-nav__arrow"
            onClick={() => handleToolbarNavigate("NEXT")}
            aria-label={t("schedule.nextPeriod")}
          >
            ›
          </button>
          <span className="schedule-header-month">{calMonthLabel}</span>
        </div>
      }
      headerAction={
        <div className="schedule-header-actions">
          <select
            className="schedule-view-select"
            value={calView}
            onChange={(e) => handleToolbarView(e.target.value)}
            aria-label={t("schedule.viewSelect")}
          >
            <option value="dayGridMonth">{t("schedule.monthView")}</option>
            <option value="timeGridWeek">{t("schedule.weekView")}</option>
            <option value="timeGridDay">{t("schedule.dayView")}</option>
          </select>
          {canManage && (
            <button
              className={gcalConnectBtnClass}
              onClick={gcalStatus !== "connected" ? handleGoogleConnect : undefined}
            >
              {gcalConnectBtnLabel}
            </button>
          )}
        </div>
      }
    >
      {/* Google Calendar 接続ステータスバー（接続中/切断中のみ表示） */}
      <GoogleCalendarStatusBar
        onReconnect={handleGoogleConnect}
        onConnect={handleGoogleConnect}
        canManage={canManage}
        onSyncStatusChange={setGcalStatus}
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

      {/* カレンダー本体 */}
      <div className="gcal-container">
        {loadingEvents && (
          <div className="gcal-loading">
            {t("schedule.loading")}
          </div>
        )}

        <FullCalendar
          ref={calendarRef}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          locale="ja"
          firstDay={0}
          headerToolbar={false}
          events={events}
          selectable={canManage}
          selectMirror
          select={handleSelect}
          eventClick={handleEventClick}
          datesSet={handleDatesSet}
          height="100%"
          nowIndicator
          allDaySlot
          slotMinTime="00:00:00"
          slotMaxTime="24:00:00"
          slotDuration="00:30:00"
          slotLabelInterval="01:00:00"
          slotLabelFormat={{ hour: "numeric", minute: "2-digit", omitZeroMinute: true, meridiem: false }}
          moreLinkContent={(args) => `+${args.num}`}
          dayHeaderContent={({ date, isToday, view }) => {
            const dayName = new Intl.DateTimeFormat("ja-JP", { weekday: "narrow" }).format(date);
            if (view.type === "dayGridMonth") {
              return <span className="gcal-month-col-name">{dayName}</span>;
            }
            return (
              <div className="gcal-day-header">
                <span className="gcal-day-header__name">{dayName}</span>
                <span className={`gcal-day-header__num${isToday ? " today" : ""}`}>
                  {date.getDate()}
                </span>
              </div>
            );
          }}
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
