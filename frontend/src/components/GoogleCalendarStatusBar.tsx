/**
 * Google Calendar 接続ステータスバー
 *
 * 接続状態を常時表示し、切断時は再接続ボタンを表示する。
 * 30秒ごとに自動ポーリングして状態を更新する。
 *
 * ADR-027: 全 UI 文字列は t() 経由
 * ADR-067: デザイントークン参照のみ（ハードコード禁止）
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Warning, X } from "../constants/icons";
import { api } from "../lib/api";

type SyncStatus = "connected" | "disconnected" | "loading" | "not_linked";

interface StatusBarProps {
  onReconnect: () => void;
  onConnect: () => void;
  canManage: boolean;
  /** 接続状態が変化したときに親に通知 */
  onStatusChange?: (connected: boolean) => void;
}

export function GoogleCalendarStatusBar({
  onReconnect,
  onConnect,
  canManage,
  onStatusChange,
}: StatusBarProps) {
  const { t } = useTranslation();
  const [syncStatus, setSyncStatus] = useState<SyncStatus>("loading");
  const [lastSyncTime, setLastSyncTime] = useState<Date | null>(null);
  const [reconnecting, setReconnecting] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const res = await api.get<{
        connected: boolean;
        connected_at: string | null;
      }>("/google-calendar/status");

      if (res.connected) {
        setSyncStatus("connected");
        setLastSyncTime(new Date());
        onStatusChange?.(true);
      } else {
        setSyncStatus("not_linked");
        onStatusChange?.(false);
      }
    } catch {
      setSyncStatus("disconnected");
      onStatusChange?.(false);
    }
  }, [onStatusChange]);

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 30_000);
    return () => clearInterval(interval);
  }, [checkStatus]);

  const handleReconnect = async () => {
    setReconnecting(true);
    try {
      await onReconnect();
    } finally {
      setReconnecting(false);
      await checkStatus();
    }
  };

  const formatLastSync = (date: Date): string => {
    const diffMs = Date.now() - date.getTime();
    const diffMin = Math.floor(diffMs / 60_000);
    if (diffMin < 1) return t("schedule.statusJustNow");
    if (diffMin < 60) return t("schedule.statusMinutesAgo", { count: diffMin });
    return t("schedule.statusConnected");
  };

  if (syncStatus === "loading") return null;

  const configs = {
    connected: {
      bg: "var(--calendar-status-ok-bg)",
      color: "var(--calendar-status-ok-text)",
      Icon: Check,
      message: lastSyncTime
        ? t("schedule.statusLastSync", { time: formatLastSync(lastSyncTime) })
        : t("schedule.statusConnected"),
      action: null,
    },
    disconnected: {
      bg: "var(--calendar-status-error-bg)",
      color: "var(--calendar-status-error-text)",
      Icon: X,
      message: t("schedule.statusDisconnected"),
      action: canManage ? (
        <button
          onClick={handleReconnect}
          disabled={reconnecting}
          style={{
            marginLeft: "var(--space-3)",
            padding: "var(--space-1) var(--space-3)",
            background: "var(--calendar-status-error-text)",
            color: "var(--on-accent)",
            border: "none",
            borderRadius: "var(--radius-sm)",
            cursor: "pointer",
            fontSize: "var(--font-sm)",
            fontWeight: "var(--font-weight-medium)",
          }}
        >
          {reconnecting ? t("common.saving") : t("schedule.statusReconnect")}
        </button>
      ) : null,
    },
    not_linked: {
      bg: "var(--bg-subtle)",
      color: "var(--text-secondary)",
      Icon: Warning,
      message: t("schedule.statusNotLinked"),
      action: canManage ? (
        <button
          onClick={onConnect}
          style={{
            marginLeft: "var(--space-3)",
            padding: "var(--space-1) var(--space-3)",
            background: "var(--calendar-google-blue)",
            color: "var(--on-accent)",
            border: "none",
            borderRadius: "var(--radius-sm)",
            cursor: "pointer",
            fontSize: "var(--font-sm)",
            fontWeight: "var(--font-weight-medium)",
          }}
        >
          {t("schedule.statusConnectPrompt")}
        </button>
      ) : null,
    },
  } as const;

  const cfg = configs[syncStatus];
  const { Icon } = cfg;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        padding: "var(--space-2) var(--space-4)",
        background: cfg.bg,
        color: cfg.color,
        borderRadius: "var(--radius-sm)",
        fontSize: "var(--font-sm)",
        marginBottom: "var(--space-3)",
        minHeight: "36px",
      }}
    >
      <Icon
        size={14}
        weight="bold"
        aria-hidden="true"
        style={{ marginRight: "var(--space-2)", flexShrink: 0 }}
      />
      <span style={{ flex: 1 }}>{cfg.message}</span>
      {cfg.action}
    </div>
  );
}
