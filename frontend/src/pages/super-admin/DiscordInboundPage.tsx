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
import { PageLayout } from "../../components/PageLayout";

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

// 受信通知 → 商品マスタ取込（プレビュー付き）の候補
interface InboundProductCandidate {
  name: string;
  occurrences: number;
  sample: string | null;
  // PR5c: 取込時に商品マスタへ転記する付随情報。
  unit: string | null;       // 代表的な取引単位（carton→case 正規化済・小文字）
  condition: string | null;  // 代表的な状態（小文字）
  language: string;          // 商品名から自動判定した言語（ja/en・取込時に修正可）
}

// 取引単位は backend で carton→case 正規化済。表示は「先頭の文字だけ大文字」（例: case→Case）。
const capUnit = (u: string | null) =>
  u ? u.charAt(0).toUpperCase() + u.slice(1).toLowerCase() : "-";

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
  // 受信通知 → 商品マスタ取込（プレビュー付き）。元は在庫表にあったが受信通知の文脈なので本ページへ移設。
  const [showImport, setShowImport] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [importApplying, setImportApplying] = useState(false);
  const [importError, setImportError] = useState("");
  const [candidates, setCandidates] = useState<InboundProductCandidate[]>([]);
  const [importSelected, setImportSelected] = useState<Set<string>>(new Set());
  const [importCategory, setImportCategory] = useState("");
  const [importDone, setImportDone] = useState("");
  // PR5c: 商品名→言語コード(ja/en)。自動判定値を初期値にし、オペレータが取込時に修正できる。
  const [importLanguages, setImportLanguages] = useState<Record<string, string>>({});

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

  // 受信通知から未登録の商品名候補を取得してプレビューを開く
  const openImport = async () => {
    setShowImport(true);
    setImportError("");
    setImportDone("");
    setImportLoading(true);
    setCandidates([]);
    setImportSelected(new Set());
    setImportCategory("");
    setImportLanguages({});
    try {
      const data = await api.get<{ candidates: InboundProductCandidate[]; total: number }>(
        "/super-admin/inbound/product-candidates",
      );
      const list = Array.isArray(data.candidates) ? data.candidates : [];
      setCandidates(list);
      // デフォルトは全選択（オペレータがノイズを外す運用）
      setImportSelected(new Set(list.map((c) => c.name)));
      // 言語は全件デフォルト「日本語」（ユーザー方針 2026-06-02）。英語は取込時に個別修正できる。
      setImportLanguages(Object.fromEntries(list.map((c) => [c.name, "ja"])));
    } catch (e) {
      setImportError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setImportLoading(false);
    }
  };

  const toggleImport = (name: string) => {
    setImportSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const setImportLanguage = (name: string, lang: string) => {
    setImportLanguages((prev) => ({ ...prev, [name]: lang }));
  };

  const allImportSelected = candidates.length > 0 && importSelected.size === candidates.length;
  const toggleImportAll = () => {
    setImportSelected(allImportSelected ? new Set() : new Set(candidates.map((c) => c.name)));
  };

  // 選択した候補を商品マスタへ一括登録
  const applyImport = async () => {
    const names = candidates.map((c) => c.name).filter((n) => importSelected.has(n));
    if (names.length === 0) return;
    // 選択された名前ぶんの言語上書き（取込時にオペレータが修正した値）
    const languages: Record<string, string> = {};
    names.forEach((n) => {
      if (importLanguages[n]) languages[n] = importLanguages[n];
    });
    setImportApplying(true);
    setImportError("");
    try {
      const res = await api.post<{ inserted: number; skipped: number }>(
        "/super-admin/inbound/product-candidates/apply",
        { names, category: importCategory.trim() || null, languages },
      );
      setShowImport(false);
      setImportDone(t("products.importDone", { count: res.inserted }));
    } catch (e) {
      setImportError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setImportApplying(false);
    }
  };

  if (superAdminLoading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!isSuperAdmin) {
    return (
      <PageLayout navKey="nav.superAdminInbound">
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      navKey="nav.superAdminInbound"
      subtitleKey="superAdmin.inbound.subtitle"
      headerAction={
        <button className="btn-secondary" onClick={openImport} data-testid="open-import-from-inbound">
          {t("products.importFromInbound")}
        </button>
      }
    >

      {error && (
        <div className="error-message" role="alert">
          {error}
        </div>
      )}

      {importDone && <div className="success-message" data-testid="import-done">{importDone}</div>}

      {showImport && (
        <div className="modal-overlay" onClick={() => !importApplying && setShowImport(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("products.importFromInbound")}</h3>
            <p style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)", marginTop: 0 }}>
              {t("products.importFromInboundHint")}
            </p>
            {importError && <div className="error-message">{importError}</div>}
            {importLoading ? (
              <div className="loading">{t("common.loading")}</div>
            ) : candidates.length === 0 ? (
              <p className="empty">{t("products.importNoCandidates")}</p>
            ) : (
              <>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap", marginBottom: "var(--space-2)" }}>
                  <label style={{ display: "flex", alignItems: "center", gap: "var(--space-1)", cursor: "pointer" }}>
                    <input type="checkbox" checked={allImportSelected} onChange={toggleImportAll} data-testid="import-select-all" />
                    {t("common.selectAll")}
                  </label>
                  <span style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)" }}>
                    {t("products.importCandidateCount", { count: candidates.length })}
                  </span>
                  <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "var(--space-1)" }}>
                    <label style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)" }}>{t("products.importCategory")}</label>
                    <input
                      style={{ width: "var(--input-width-product-name)" }}
                      placeholder={t("common.optional")}
                      value={importCategory}
                      onChange={(e) => setImportCategory(e.target.value)}
                      data-testid="import-category"
                    />
                  </span>
                </div>
                {/* table-layout: fixed + width 100% でモーダル幅に収める（横スクロール抑止）。
                    名前/サンプルは可変幅で折返し、単位/言語は固定幅。overflowX も明示 hidden。 */}
                <div style={{ maxHeight: "50vh", overflowY: "auto", overflowX: "hidden", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                  <table className="data-table" style={{ tableLayout: "fixed" }}>
                    <thead>
                      <tr>
                        <th style={{ width: "var(--col-width-checkbox)", textAlign: "center" }} aria-label={t("common.select")}></th>
                        <th>{t("common.name")}</th>
                        <th style={{ width: "var(--col-width-checkbox)", textAlign: "right" }}>{t("products.importOccurrences")}</th>
                        <th style={{ width: "72px" }}>{t("products.unitCol")}</th>
                        <th style={{ width: "104px" }}>{t("language.label")}</th>
                        <th>{t("products.importSample")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {candidates.map((c) => (
                        <tr key={c.name}>
                          <td style={{ textAlign: "center" }}>
                            <input
                              type="checkbox"
                              checked={importSelected.has(c.name)}
                              onChange={() => toggleImport(c.name)}
                              aria-label={c.name}
                            />
                          </td>
                          <td style={{ wordBreak: "break-word" }}>{c.name}</td>
                          <td style={{ textAlign: "right" }}>{c.occurrences}</td>
                          <td>{capUnit(c.unit)}</td>
                          <td>
                            <select
                              style={{ maxWidth: "100%" }}
                              value={importLanguages[c.name] ?? "ja"}
                              onChange={(e) => setImportLanguage(c.name, e.target.value)}
                              aria-label={t("language.label")}
                            >
                              <option value="ja">{t("language.ja")}</option>
                              <option value="en">{t("language.en")}</option>
                            </select>
                          </td>
                          <td style={{ color: "var(--text-secondary)", fontSize: "var(--font-xs)", wordBreak: "break-word" }}>{c.sample || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setShowImport(false)} disabled={importApplying}>{t("common.cancel")}</button>
              <button
                type="button"
                className="btn-primary"
                onClick={applyImport}
                disabled={importApplying || importLoading || importSelected.size === 0}
                data-testid="import-apply"
              >
                {importApplying ? t("common.loading") : t("products.importApply", { count: importSelected.size })}
              </button>
            </div>
          </div>
        </div>
      )}

      <div
        className="filter-bar"
        style={{
          display: "flex",
          gap: "var(--space-2)",
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
              <th>{t("superAdmin.inbound.columns.llmCost")}</th>
              <th>{t("superAdmin.inbound.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id} data-testid={`inbound-row-${m.id}`}>
                <td>
                  <code>{new Date(m.received_at).toLocaleString()}</code>
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
    </PageLayout>
  );
}
