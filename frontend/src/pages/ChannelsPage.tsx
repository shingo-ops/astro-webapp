/**
 * Channels 設定ページ（Phase 1-D Sprint 3）。
 *
 * 接続済 Facebook Page / Instagram の一覧表示と、OAuth 接続開始 / 切断を行う。
 * 仕様: spec §5-2, §7-1
 *
 * 主な機能:
 *  - GET /meta/channels で接続済リストを取得（loading / error / empty を考慮）
 *  - POST /meta/connect/start → auth_url 取得 → window.location.href でリダイレクト
 *  - 各カードの「切断」ボタン → ConfirmModal → DELETE /meta/connect/{page_id}
 *  - URL クエリ ?status=connected|error|partial を解析してバナー表示
 *    - connected: 「Page 接続が完了しました」（success トースト）
 *    - error: reason の英文を日本語マップで日本語化
 *    - partial: 「N 件接続成功、M 件失敗（M Page）」（Sprint 2 evaluator I4 対応）
 *  - URL クリーンアップ（history.replaceState）
 *
 * 変更履歴:
 *   2026-04-30: Phase 1-D Sprint 3 初版
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";
import { STATUS_ICONS } from "../constants/icons";
import { ICON } from "../constants/iconSizes";

interface Channel {
  page_id: string;
  page_name: string;
  instagram_business_account_id: string | null;
  instagram_username: string | null;
  is_active: boolean;
  connected_at: string | null;
  page_token_expires_at: string | null;
  connected_by_staff_id: number | null;
  connected_by_staff_name: string | null;
  granted_scopes: string[] | null;
  requires_reauth: boolean;
}

interface ChannelsResponse {
  channels: Channel[];
}

interface ConnectStartResponse {
  auth_url: string;
  state: string;
  expires_at: string;
}

type Banner =
  | { type: "success"; text: string }
  | { type: "error"; text: string }
  | { type: "warning"; text: string }
  | null;

// OAuth callback の reason → 日本語の汎用マップ。
// 具体的なエラー文言は backend の audit_log に残る前提で UI は短く統一する。
const ERROR_REASON_MAP: Record<string, string> = {
  user_denied: "The connection was denied on Facebook. Please try again.",
  state_mismatch: "Security token mismatch. Please try connecting again.",
  state_expired: "Your connection session has expired. Please try again.",
  meta_api_error: "Couldn't connect due to a Meta API error. Please try again in a moment.",
  meta_timeout: "The Meta API request timed out. Please check your network connection.",
  no_pages: "No manageable Facebook Pages were found. Please create a Page and try again.",
  permission_denied: "You don't have permission to connect channels. Please contact your administrator.",
  internal_error: "An internal error occurred. Please contact support.",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  // ISO 文字列でも SQLite 由来の "2026-04-30 12:00:00+00:00" 文字列でも parse 可能
  const d = new Date(iso.replace(" ", "T"));
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso.replace(" ", "T"));
  if (isNaN(d.getTime())) return null;
  const diffMs = d.getTime() - Date.now();
  return Math.floor(diffMs / (1000 * 60 * 60 * 24));
}

export default function ChannelsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [disconnectTarget, setDisconnectTarget] = useState<Channel | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);

  const canManage = hasPermission("channels.manage");

  // ADR-041: 旧スコープ（business_management 未付与）の接続が 1 つでもあれば再認証を促す
  const reauthRequired = channels.some((c) => c.is_active && c.requires_reauth);

  // ----- OAuth callback の URL クエリを解析 -----
  // この effect は初回マウントのみ走る。?status=... があれば banner を立てて
  // history.replaceState で URL を綺麗にする。
  useEffect(() => {
    const url = new URL(window.location.href);
    const statusParam = url.searchParams.get("status");
    if (!statusParam) return;

    if (statusParam === "connected") {
      const pageName = url.searchParams.get("page_name") || "";
      const text = pageName
        ? `"${pageName}" connected successfully.`
        : "Page connected successfully.";
      setBanner({ type: "success", text });
    } else if (statusParam === "partial") {
      const succeeded = url.searchParams.get("succeeded") || "0";
      const failedPagesRaw = url.searchParams.get("failed_pages") || "";
      const failedCount = url.searchParams.get("failed") || (failedPagesRaw ? String(failedPagesRaw.split(",").length) : "0");
      const text = `Connected ${succeeded} Page(s) but ${failedCount} failed${failedPagesRaw ? ` (${failedPagesRaw})` : ""}. Please retry the failed Pages.`;
      setBanner({ type: "warning", text });
    } else if (statusParam === "error") {
      const reason = url.searchParams.get("reason") || "internal_error";
      const text = ERROR_REASON_MAP[reason] || `Connection failed (reason: ${reason}).`;
      setBanner({ type: "error", text });
    }

    // URL を綺麗にする（query string を消す）
    url.search = "";
    window.history.replaceState({}, "", url.pathname);
  }, []);

  // ----- 一覧取得 -----
  const loadChannels = async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.get<ChannelsResponse>("/meta/channels");
      setChannels(data.channels || []);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "Failed to load channels");
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadChannels(); }, []);

  // ----- 接続開始 -----
  const handleConnect = async () => {
    setConnectError("");
    setConnecting(true);
    try {
      const data = await api.post<ConnectStartResponse>("/meta/connect/start", {});
      if (!data.auth_url) {
        throw new Error("Failed to obtain auth_url");
      }
      // Facebook OAuth ダイアログへ遷移。state は backend が Redis に保存済み。
      window.location.href = data.auth_url;
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "Couldn't start the connection");
      setConnectError(msg);
      setConnecting(false);
    }
  };

  // ----- 切断 -----
  const performDisconnect = async () => {
    if (!disconnectTarget) return;
    setDisconnecting(true);
    try {
      await api.delete(`/meta/connect/${encodeURIComponent(disconnectTarget.page_id)}`);
      setDisconnectTarget(null);
      setBanner({
        type: "success",
        text: `Disconnected "${disconnectTarget.page_name}".`,
      });
      await loadChannels();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e instanceof Error ? e.message : "Disconnect failed");
      setBanner({ type: "error", text: `Disconnect failed: ${msg}` });
    } finally {
      setDisconnecting(false);
    }
  };

  // ----- バナー UI -----
  const bannerStyle: React.CSSProperties = banner
    ? {
        padding: "var(--space-3) var(--space-4)",
        borderRadius: "var(--radius-sm)",
        marginBottom: "var(--space-4)",
        background:
          banner.type === "success"
            ? "#e6f4ea"
            : banner.type === "warning"
              ? "#fff4e5"
              : "#fdecea",
        color:
          banner.type === "success"
            ? "#137333"
            : banner.type === "warning"
              ? "#a45a00"
              : "#a50e0e",
        border: `1px solid ${
          banner.type === "success"
            ? "#137333"
            : banner.type === "warning"
              ? "#a45a00"
              : "#a50e0e"
        }`,
      }
    : {};

  // ----- 描画 -----
  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("channels.title")}</h2>
        {canManage && (
          <button
            className="btn-primary"
            onClick={handleConnect}
            disabled={connecting}
          >
            {connecting ? t("channels.connecting") : t("channels.connect")}
          </button>
        )}
      </div>

      {banner && (
        <div style={bannerStyle} role={banner.type === "error" ? "alert" : "status"}>
          <span style={{ marginRight: "var(--space-2)" }} aria-hidden="true">
            {banner.type === "success"
              ? <STATUS_ICONS.check size={ICON.sm} />
              : banner.type === "warning"
              ? <STATUS_ICONS.warning size={ICON.sm} />
              : <STATUS_ICONS.error size={ICON.sm} />}
          </span>
          {banner.text}
          <button
            type="button"
            onClick={() => setBanner(null)}
            style={{
              float: "right",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              fontSize: "var(--font-md)",
              lineHeight: 1,
            }}
            aria-label={t("channels.close")}
          >
            ×
          </button>
        </div>
      )}

      {reauthRequired && (
        <div
          role="status"
          data-testid="channels-reauth-banner"
          style={{
            padding: "12px 16px",
            borderRadius: "var(--radius-sm)",
            marginBottom: "var(--space-4)",
            background: "var(--warning-bg)",
            color: "var(--warning-text)",
            border: "1px solid var(--warning-text)",
            display: "flex",
            alignItems: "center",
            gap: "var(--space-3)",
          }}
        >
          <span style={{ flex: 1 }}>
            <strong><STATUS_ICONS.warning size={ICON.sm} aria-hidden="true" />{" "}</strong>
            {t("channels.reauthRequired")}
          </span>
          {canManage && (
            <button
              className="btn-sm"
              onClick={handleConnect}
              disabled={connecting}
            >
              {connecting ? t("channels.connecting") : t("channels.reauthAction")}
            </button>
          )}
        </div>
      )}

      {connectError && (
        <div className="error" style={{ marginBottom: "var(--space-4)" }}>{connectError}</div>
      )}

      {loadError && (
        <div className="error" style={{ marginBottom: "var(--space-4)" }}>
          {t("channels.loadError")} {loadError}
          <button
            type="button"
            className="btn-sm"
            style={{ marginLeft: "var(--space-2)" }}
            onClick={loadChannels}
          >
            {t("channels.reload")}
          </button>
        </div>
      )}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : channels.length === 0 ? (
        // ----- 空 state（onboarding CTA） -----
        <div
          className="card"
          style={{
            textAlign: "center",
            padding: "var(--space-12) var(--space-6)",
          }}
        >
          <h3 style={{ marginTop: 0 }}>{t("channels.noChannels")}</h3>
          <p style={{ color: "var(--text-muted)", marginBottom: "var(--space-6)" }}>
            {t("channels.noChannelsDesc")}
          </p>
          {canManage ? (
            <button
              className="btn-primary"
              onClick={handleConnect}
              disabled={connecting}
              style={{ fontSize: "var(--font-md)", padding: "var(--space-3) var(--space-6)" }}
            >
              {connecting ? t("channels.connecting") : t("channels.connect")}
            </button>
          ) : (
            <p style={{ color: "var(--text-muted)" }}>
              {t("channels.noChannelsDesc")}
            </p>
          )}
        </div>
      ) : (
        // ----- 接続済リスト -----
        <div className="channel-list" style={{ display: "grid", gap: "var(--space-3)" }}>
          {channels.map((ch) => {
            const expiresIn = daysUntil(ch.page_token_expires_at);
            const tokenWarn = expiresIn !== null && expiresIn <= 30;
            return (
              <div
                key={ch.page_id}
                className="card"
                style={{
                  padding: "var(--space-4)",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  gap: "var(--space-4)",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-1)" }}>
                    <h3 style={{ margin: 0, fontSize: "var(--font-sidebar-brand)" }}>{ch.page_name}</h3>
                    {ch.is_active ? (
                      <span className="badge" style={{ background: "var(--success-bg)", color: "var(--success-text)" }}>
                        {t("channels.status_active")}
                      </span>
                    ) : (
                      <span className="badge" style={{ background: "var(--bg-hover)", color: "var(--text-muted)" }}>
                        {t("channels.status_inactive")}
                      </span>
                    )}
                    {ch.is_active && ch.requires_reauth && (
                      <span
                        className="badge"
                        data-testid="channel-reauth-badge"
                        style={{ background: "var(--warning-bg)", color: "var(--warning-text)" }}
                      >
                        {t("channels.reauthBadge")}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)", lineHeight: 1.7 }}>
                    <div>
                      <strong>Page ID:</strong> <span className="mono">{ch.page_id}</span>
                    </div>
                    {ch.instagram_username && (
                      <div>
                        <strong>{t("channels.instagramLinked")}:</strong> @{ch.instagram_username}
                        {ch.instagram_business_account_id && (
                          <span className="mono" style={{ marginLeft: "var(--space-6px)", opacity: 0.7 }}>
                            ({ch.instagram_business_account_id})
                          </span>
                        )}
                      </div>
                    )}
                    <div>
                      <strong>{t("channels.connectedAt")}:</strong> {formatDate(ch.connected_at)}
                      {ch.connected_by_staff_name && ` / ${t("channels.connectedBy")}: ${ch.connected_by_staff_name}`}
                    </div>
                    {ch.page_token_expires_at && (
                      <div style={tokenWarn ? { color: "var(--warning-text)", fontWeight: "var(--font-weight-semi)" } : undefined}>
                        <strong>{t("channels.tokenExpires")}:</strong> {formatDate(ch.page_token_expires_at)}
                        {expiresIn !== null && (
                          <span style={{ marginLeft: "var(--space-6px)" }}>
                            ({expiresIn >= 0 ? t("channels.daysLeft", { count: expiresIn }) : t("channels.expired")})
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
                <div style={{ flexShrink: 0 }}>
                  {canManage && ch.is_active && (
                    <button
                      className="btn-sm btn-danger"
                      onClick={() => setDisconnectTarget(ch)}
                      disabled={disconnecting}
                    >
                      {t("channels.disconnect")}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <ConfirmModal
        open={!!disconnectTarget}
        title={t("channels.disconnectTitle")}
        danger
        confirmLabel={disconnecting ? t("channels.disconnecting") : t("channels.disconnect")}
        message={
          <>
            <strong>{disconnectTarget?.page_name}</strong> {t("channels.disconnectConfirm")}
            <br />
            {t("common.irreversible")}
          </>
        }
        onConfirm={performDisconnect}
        onCancel={() => setDisconnectTarget(null)}
      />
    </div>
  );
}
