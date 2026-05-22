/**
 * /super-admin/inbound — Discord 受信メッセージ一覧（中央 admin、is_super_admin 限定）。
 *
 * spec.md v1.1 F5 (Sprint 5) / AC5.5:
 *   - 中央 admin が tenant_006 等に受信した Discord メッセージを時系列降順で表示
 *   - parse_status / supplier_id / q (raw_content 部分一致) で絞り込み
 *   - 行クリック → /super-admin/inbound/:id (Sprint 6 で実装予定の F6 review 画面)
 *
 * 注意:
 *   - 5 タブ MastersPage には乗せず、独立ページ /super-admin/inbound として配置
 *     （受信ボリュームが多く専用画面が必要、Sprint 6 review UI も同 URL 配下）
 *   - is_super_admin=false なら 403 メッセージ。バックエンド側でも
 *     require_super_admin で二重ガード（AC2.1 / AC6.8 と同一パターン）
 */
import { useCallback, useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";

interface InboundListItem {
  id: number;
  discord_message_id: string;
  discord_channel_id: string;
  supplier_id: number | null;
  supplier_name: string | null;
  raw_content_preview: string;
  parse_status: string;
  parse_engine: string | null;
  received_at: string;
  llm_cost_usd: string | null;
}

// parse_status enum (migration 059 と整合)
const PARSE_STATUS_VALUES = [
  "pending",
  "parsing",
  "parsed",
  "parsed_rule_only",
  "parsed_llm",
  "unparsed",
  "budget_exhausted",
  "ignored_routing",
  "approved",
  "rejected",
] as const;

type ParseStatus = (typeof PARSE_STATUS_VALUES)[number];

function statusBadgeClass(status: string): string {
  switch (status) {
    case "approved":
    case "parsed":
    case "parsed_rule_only":
    case "parsed_llm":
      return "badge badge-success";
    case "rejected":
    case "unparsed":
      return "badge badge-danger";
    case "budget_exhausted":
    case "ignored_routing":
      return "badge badge-warning";
    case "pending":
    case "parsing":
    default:
      return "badge badge-secondary";
  }
}

export default function DiscordInboundPage() {
  const { t } = useTranslation();
  const { isSuperAdmin, loading: superAdminLoading } = useSuperAdmin();
  const [items, setItems] = useState<InboundListItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [filterStatus, setFilterStatus] = useState<"" | ParseStatus>("");
  const [filterQ, setFilterQ] = useState("");

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (filterStatus) params.set("parse_status", filterStatus);
    if (filterQ.trim()) params.set("q", filterQ.trim());
    params.set("per_page", "100");
    return params.toString();
  }, [filterStatus, filterQ]);

  const load = useCallback(async () => {
    setError("");
    setLoading(true);
    try {
      const data = await api.get<InboundListItem[]>(
        `/super-admin/inbound/discord?${queryString}`,
      );
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [queryString, t]);

  useEffect(() => {
    if (!isSuperAdmin) return;
    void load();
  }, [isSuperAdmin, load]);

  if (superAdminLoading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!isSuperAdmin) {
    return (
      <div className="page">
        <div className="page-header">
          <h2>{t("superAdmin.inbound.title")}</h2>
        </div>
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </div>
    );
  }

  return (
    <div className="page super-admin-inbound-page">
      <div className="page-header">
        <h2>{t("superAdmin.inbound.title")}</h2>
        <p className="page-subtitle">{t("superAdmin.inbound.subtitle")}</p>
      </div>

      {error && (
        <div className="error-message" role="alert">
          {error}
        </div>
      )}

      <div
        className="filter-bar"
        style={{
          display: "flex",
          gap: "0.5rem",
          margin: "1rem 0",
          alignItems: "center",
        }}
      >
        <label>
          {t("superAdmin.inbound.filters.status")}
          <select
            data-testid="filter-parse-status"
            value={filterStatus}
            onChange={(e) =>
              setFilterStatus(e.target.value as ParseStatus | "")
            }
            style={{ marginLeft: "var(--space-1)" }}
          >
            <option value="">
              {t("superAdmin.inbound.filters.statusAny")}
            </option>
            {PARSE_STATUS_VALUES.map((s) => (
              <option key={s} value={s}>
                {t(`superAdmin.inbound.parseStatus.${s}`, s)}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("superAdmin.inbound.filters.search")}
          <input
            data-testid="filter-q"
            value={filterQ}
            onChange={(e) => setFilterQ(e.target.value)}
            placeholder={t("superAdmin.inbound.filters.searchPlaceholder")}
            style={{ marginLeft: "var(--space-1)" }}
          />
        </label>
        <button onClick={() => void load()} className="btn-secondary">
          {t("common.reload")}
        </button>
      </div>

      {loading ? (
        <div className="loading-indicator">{t("common.loading")}</div>
      ) : items.length === 0 ? (
        <div className="empty-state" data-testid="inbound-empty">
          {t("superAdmin.inbound.noRows")}
        </div>
      ) : (
        <table className="data-table" data-testid="inbound-table">
          <thead>
            <tr>
              <th>{t("superAdmin.inbound.columns.receivedAt")}</th>
              <th>{t("superAdmin.inbound.columns.supplier")}</th>
              <th>{t("superAdmin.inbound.columns.parseStatus")}</th>
              <th>{t("superAdmin.inbound.columns.preview")}</th>
              <th>{t("superAdmin.inbound.columns.engine")}</th>
              <th>{t("superAdmin.inbound.columns.llmCost")}</th>
              <th>{t("superAdmin.inbound.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} data-testid={`inbound-row-${m.id}`}>
                <td>
                  <code style={{ fontSize: "0.85em" }}>
                    {new Date(m.received_at).toLocaleString()}
                  </code>
                </td>
                <td>{m.supplier_name ?? "—"}</td>
                <td>
                  <span
                    className={statusBadgeClass(m.parse_status)}
                    data-testid={`status-${m.id}`}
                  >
                    {t(
                      `superAdmin.inbound.parseStatus.${m.parse_status}`,
                      m.parse_status,
                    )}
                  </span>
                </td>
                <td
                  style={{
                    maxWidth: "400px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {m.raw_content_preview}
                </td>
                <td>
                  <code style={{ fontSize: "0.85em" }}>
                    {m.parse_engine ?? "—"}
                  </code>
                </td>
                <td>
                  {m.llm_cost_usd
                    ? `$${Number.parseFloat(m.llm_cost_usd).toFixed(4)}`
                    : "—"}
                </td>
                <td>
                  <Link
                    to={`/super-admin/inbound/${m.id}/review`}
                    data-testid={`review-link-${m.id}`}
                  >
                    {t("superAdmin.inbound.columns.openReview")}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
