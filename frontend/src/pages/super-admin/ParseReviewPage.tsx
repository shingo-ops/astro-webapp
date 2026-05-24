/**
 * /super-admin/inbound/:id/review — 解析結果レビュー画面 (Sprint 6 F6)。
 *
 * spec.md v1.1 F6 / AC6.1〜6.8:
 *   - 行単位 UI: 採用 / スキップ / 編集 / 差戻し
 *   - 承認 → POST /super-admin/parse-review/:id/approve → inventory_movements 反映
 *   - 差戻し → POST /super-admin/parse-review/:id/reject (exclude_reason 必須)
 *   - 楽観ロック: version mismatch (409) → エラートースト + 最新版再取得
 *   - is_super_admin=false → 403 view (バックエンドの require_super_admin と二重ガード)
 *
 * Generator 判断 (Sprint 6):
 *   - product_id NULL の items は採用不可（行を gray-out + "skip 必須" メッセージ）。
 *     ⇒ Sprint 7 (2026-05-22): InventorySearchBar を行内に埋め込み、インラインで product_id 解決可能化。
 *   - 編集は delta_qty / notes / product_id (Sprint 7 で追加) をインライン可能。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../lib/api";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
import InventorySearchBar, { InventorySearchCandidate } from "../../components/InventorySearchBar";

interface ReviewItem {
  product_id: number | null;
  delta_qty: number;
  alias_text?: string | null;
  notes?: string | null;
  original_index?: number;
}

interface ParseResultJson {
  items?: ReviewItem[];
  excludes?: unknown[];
  unparsed?: unknown[];
  skipped?: number[];
}

interface ParseReviewDetail {
  id: number;
  discord_message_id: string;
  discord_channel_id: string;
  supplier_id: number | null;
  supplier_name: string | null;
  raw_content: string;
  parse_status: string;
  parse_engine: string | null;
  parse_result_json: ParseResultJson | null;
  received_at: string;
  exclude_reason: string | null;
  operator_comment: string | null;
  operator_id: number | null;
  approved_at: string | null;
  llm_cost_usd: string | null;
  created_at: string;
  updated_at: string;
  version: number;
}

interface RowDraft {
  product_id: number | null;
  delta_qty: number;
  alias_text: string;
  notes: string;
  original_index: number;
  skipped: boolean;
}

interface ApproveResponse {
  inbound_id: number;
  parse_status: string;
  version: number;
  movements: Array<{
    movement_id: number;
    product_id: number;
    delta_qty: number;
    before_qty: number;
    after_qty: number;
  }>;
  skipped_count: number;
  // Sprint 9 / F9 v1.2: Phase A 並走時に products.stock_quantity 更新を skip したか
  skipped_stock_update?: boolean;
  phase?: "A" | "B" | "C";
}

interface RejectResponse {
  inbound_id: number;
  parse_status: string;
  version: number;
  exclude_reason: string;
}

function detailToDrafts(detail: ParseReviewDetail): RowDraft[] {
  const items = detail.parse_result_json?.items ?? [];
  const existingSkipped = new Set(detail.parse_result_json?.skipped ?? []);
  return items.map((item, idx) => ({
    product_id: item.product_id ?? null,
    delta_qty: Number(item.delta_qty ?? 0),
    alias_text: String(item.alias_text ?? ""),
    notes: String(item.notes ?? ""),
    original_index: idx,
    skipped: existingSkipped.has(idx),
  }));
}

export default function ParseReviewPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { isSuperAdmin, loading: superAdminLoading } = useSuperAdmin();

  const [detail, setDetail] = useState<ParseReviewDetail | null>(null);
  const [drafts, setDrafts] = useState<RowDraft[]>([]);
  const [operatorComment, setOperatorComment] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [showRejectDialog, setShowRejectDialog] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  // Sprint 9 / F9 v1.2: Phase A 並走時の warning toast
  const [phaseWarning, setPhaseWarning] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const inboundId = useMemo(() => (id ? Number.parseInt(id, 10) : NaN), [id]);

  const load = useCallback(async ({ preserveError = false }: { preserveError?: boolean } = {}) => {
    if (!inboundId || Number.isNaN(inboundId)) return;
    if (!preserveError) setError("");
    setLoading(true);
    try {
      const d = await api.get<ParseReviewDetail>(
        `/super-admin/parse-review/${inboundId}`,
      );
      setDetail(d);
      setDrafts(detailToDrafts(d));
      setOperatorComment(d.operator_comment ?? "");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [inboundId, t]);

  useEffect(() => {
    if (!isSuperAdmin) return;
    void load();
  }, [isSuperAdmin, load]);

  const updateDraft = (idx: number, patch: Partial<RowDraft>) => {
    setDrafts((prev) =>
      prev.map((row, i) => (i === idx ? { ...row, ...patch } : row)),
    );
  };

  const handleApprove = async () => {
    if (!detail) return;
    setError("");
    setInfo("");
    setSubmitting(true);
    try {
      // 採用行（skipped=false かつ product_id !== null かつ delta_qty !== 0）のみ送信
      const items = drafts
        .filter((r) => !r.skipped && r.product_id !== null && r.delta_qty !== 0)
        .map((r) => ({
          product_id: r.product_id,
          delta_qty: r.delta_qty,
          alias_text: r.alias_text || null,
          notes: r.notes || null,
          original_index: r.original_index,
        }));
      const skipped_indices = drafts
        .filter((r) => r.skipped)
        .map((r) => r.original_index);

      const resp = await api.post<ApproveResponse>(
        `/super-admin/parse-review/${inboundId}/approve`,
        {
          version: detail.version,
          items,
          skipped_indices,
          operator_comment: operatorComment || null,
        },
      );
      setInfo(
        t("superAdmin.inbound.review.approveSuccess", {
          count: resp.movements.length,
          skipped: resp.skipped_count,
        }),
      );
      // Sprint 9 / F9 v1.2 (AC9.6): Phase A 並走中の在庫値スキップ警告
      if (resp.skipped_stock_update) {
        setPhaseWarning(
          t("superAdmin.parseReview.phaseAWarning.afterApprove", {
            count: resp.movements.length,
          }),
        );
      } else {
        setPhaseWarning("");
      }
      // 反映後は最新を再取得 → 画面更新
      await load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("superAdmin.inbound.review.versionConflict"));
        // 自動で最新版を取得し直す（AC6.5 UI 動作）
        // preserveError: 409 conflict メッセージを load() 冒頭の setError("") でクリアさせない
        await load({ preserveError: true });
      } else {
        setError(e instanceof Error ? e.message : t("common.operationError"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!detail) return;
    if (!rejectReason.trim()) {
      setError(t("superAdmin.inbound.review.rejectReasonRequired"));
      return;
    }
    setError("");
    setInfo("");
    setSubmitting(true);
    try {
      const resp = await api.post<RejectResponse>(
        `/super-admin/parse-review/${inboundId}/reject`,
        { version: detail.version, exclude_reason: rejectReason },
      );
      setInfo(t("superAdmin.inbound.review.rejectSuccess"));
      setShowRejectDialog(false);
      setRejectReason("");
      await load();
      // 既に rejected になっているので一覧へ戻る誘導も可（ユーザー任意）
      if (resp.parse_status === "rejected") {
        // 残留しない: 何もしない、ユーザーが back ボタンで戻る
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError(t("superAdmin.inbound.review.versionConflict"));
        // preserveError: 409 conflict メッセージを load() 冒頭の setError("") でクリアさせない
        await load({ preserveError: true });
      } else {
        setError(e instanceof Error ? e.message : t("common.operationError"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (superAdminLoading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!isSuperAdmin) {
    return (
      <div className="page">
        <div className="page-header">
          {/* eslint-disable-next-line no-restricted-syntax -- 詳細ページ（route param あり）は PageLayout の navKey 制約対象外 */}
          <h2>{t("superAdmin.inbound.review.title")}</h2>
        </div>
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </div>
    );
  }

  const isFinal =
    detail?.parse_status === "approved" || detail?.parse_status === "rejected";

  return (
    <div className="page super-admin-parse-review-page">
      <div className="page-header">
        {/* eslint-disable-next-line no-restricted-syntax */}
        <h2>{t("superAdmin.inbound.review.title")}</h2>
        <p className="page-subtitle">
          {t("superAdmin.inbound.review.subtitle")}
        </p>
        <button
          onClick={() => navigate("/super-admin/inbound")}
          className="btn-secondary"
          data-testid="review-back-link"
        >
          {t("superAdmin.inbound.review.backToList")}
        </button>
      </div>

      {/* Sprint 9 / F9 v1.2 AC9.6: Phase A 並走中の常時表示 warning banner。
          スプレッドシートが在庫数の真値であることをレビュアーに常時知らせる */}
      <div
        className="warning-banner"
        role="status"
        data-testid="phase-a-warning-banner"
        style={{
          backgroundColor: "var(--warning-bg)",
          color: "var(--warning-text)",
          border: "1px solid var(--border-strong)",
          padding: "0.75rem 1rem",
          borderRadius: "var(--radius-sm)",
          marginBottom: "var(--space-4)",
        }}
      >
        {t("superAdmin.parseReview.phaseAWarning.always")}
      </div>

      {error && (
        <div className="error-message" role="alert" data-testid="review-error">
          {error}
        </div>
      )}
      {info && (
        <div className="info-message" role="status" data-testid="review-info">
          {info}
        </div>
      )}
      {phaseWarning && (
        <div
          className="warning-message"
          role="status"
          data-testid="phase-a-warning-toast"
          style={{
            backgroundColor: "var(--warning-bg)",
            border: "1px solid var(--border-strong)",
            padding: "var(--space-2) var(--space-4)",
            borderRadius: "var(--radius-sm)",
            marginBottom: "var(--space-4)",
            color: "var(--warning-text)",
          }}
        >
          {phaseWarning}
        </div>
      )}

      {loading && (
        <div className="loading-indicator">{t("common.loading")}</div>
      )}

      {detail && (
        <>
          <section
            className="review-meta"
            data-testid="review-meta"
            style={{ marginBottom: "var(--space-4)" }}
          >
            <dl>
              <dt>{t("superAdmin.inbound.columns.supplier")}</dt>
              <dd>{detail.supplier_name ?? "—"}</dd>
              <dt>{t("superAdmin.inbound.columns.parseStatus")}</dt>
              <dd>
                <span data-testid="review-status">
                  {t(
                    `superAdmin.inbound.parseStatus.${detail.parse_status}`,
                    detail.parse_status,
                  )}
                </span>
              </dd>
              <dt>{t("superAdmin.inbound.columns.receivedAt")}</dt>
              <dd>{new Date(detail.received_at).toLocaleString()}</dd>
              <dt>{t("superAdmin.inbound.review.versionLabel")}</dt>
              <dd>
                <code data-testid="review-version">{detail.version}</code>
              </dd>
            </dl>
            <details>
              <summary>{t("superAdmin.inbound.review.rawContent")}</summary>
              <pre style={{ whiteSpace: "pre-wrap" }}>{detail.raw_content}</pre>
            </details>
          </section>

          <table className="data-table" data-testid="review-table">
            <thead>
              <tr>
                <th>#</th>
                <th>{t("superAdmin.inbound.review.col.productId")}</th>
                <th>{t("superAdmin.inbound.review.col.deltaQty")}</th>
                <th>{t("superAdmin.inbound.review.col.alias")}</th>
                <th>{t("superAdmin.inbound.review.col.notes")}</th>
                <th>{t("superAdmin.inbound.review.col.skip")}</th>
              </tr>
            </thead>
            <tbody>
              {drafts.length === 0 ? (
                <tr>
                  <td colSpan={6} data-testid="review-empty">
                    {t("superAdmin.inbound.review.noItems")}
                  </td>
                </tr>
              ) : (
                drafts.map((row, idx) => (
                  <tr
                    key={idx}
                    data-testid={`review-row-${idx}`}
                    style={
                      row.skipped
                        ? {
                            opacity: "var(--opacity-skipped)",
                            background: "var(--bg-disabled)",
                          }
                        : undefined
                    }
                  >
                    <td>{idx}</td>
                    <td style={{ minWidth: 240 }}>
                      {row.product_id === null ? (
                        <div data-testid={`review-row-${idx}-missing-product`}>
                          <em
                            style={{ color: "var(--color-warning)", fontSize: "0.85em" }}
                          >
                            {t("superAdmin.inbound.review.missingProduct")}
                          </em>
                          {!isFinal && (
                            <div style={{ marginTop: "var(--space-1)" }}>
                              <InventorySearchBar
                                disabled={row.skipped}
                                testIdPrefix={`review-row-${idx}-inv-search`}
                                onSelect={(c: InventorySearchCandidate) =>
                                  updateDraft(idx, { product_id: c.product_id })
                                }
                              />
                            </div>
                          )}
                        </div>
                      ) : (
                        <code data-testid={`review-row-${idx}-product-id`}>{row.product_id}</code>
                      )}
                    </td>
                    <td>
                      <input
                        type="number"
                        data-testid={`review-row-${idx}-delta`}
                        value={row.delta_qty}
                        disabled={row.skipped || isFinal}
                        onChange={(e) =>
                          updateDraft(idx, {
                            delta_qty: Number.parseInt(e.target.value, 10) || 0,
                          })
                        }
                        style={{ width: "5rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        data-testid={`review-row-${idx}-alias`}
                        value={row.alias_text}
                        disabled={row.skipped || isFinal}
                        onChange={(e) =>
                          updateDraft(idx, { alias_text: e.target.value })
                        }
                        style={{ width: "8rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        data-testid={`review-row-${idx}-notes`}
                        value={row.notes}
                        disabled={row.skipped || isFinal}
                        onChange={(e) =>
                          updateDraft(idx, { notes: e.target.value })
                        }
                        style={{ width: "10rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        data-testid={`review-row-${idx}-skip`}
                        checked={row.skipped}
                        disabled={isFinal}
                        onChange={(e) =>
                          updateDraft(idx, { skipped: e.target.checked })
                        }
                      />
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <section
            className="review-comment"
            style={{ marginTop: "var(--space-4)", maxWidth: "40rem" }}
          >
            <label htmlFor="operator-comment">
              {t("superAdmin.inbound.review.operatorComment")}
            </label>
            <textarea
              id="operator-comment"
              data-testid="review-operator-comment"
              rows={3}
              value={operatorComment}
              disabled={isFinal}
              onChange={(e) => setOperatorComment(e.target.value)}
              style={{ width: "100%" }}
            />
          </section>

          <div className="action-bar" style={{ marginTop: "var(--space-4)" }}>
            <button
              onClick={() => void handleApprove()}
              disabled={isFinal || submitting}
              data-testid="review-approve-btn"
              className="btn-primary"
            >
              {t("superAdmin.inbound.review.approveBtn")}
            </button>
            <button
              onClick={() => setShowRejectDialog(true)}
              disabled={isFinal || submitting}
              data-testid="review-reject-btn"
              className="btn-danger"
              style={{ marginLeft: "var(--space-2)" }}
            >
              {t("superAdmin.inbound.review.rejectBtn")}
            </button>
          </div>

          {showRejectDialog && (
            <div
              className="modal"
              role="dialog"
              aria-modal="true"
              data-testid="review-reject-dialog"
              style={{
                marginTop: "var(--space-4)",
                padding: "var(--space-4)",
                border: "1px solid var(--border-color)",
              }}
            >
              <h3>{t("superAdmin.inbound.review.rejectDialogTitle")}</h3>
              <label htmlFor="reject-reason">
                {t("superAdmin.inbound.review.rejectReasonLabel")}
              </label>
              <textarea
                id="reject-reason"
                data-testid="review-reject-reason"
                rows={3}
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                style={{ width: "100%" }}
              />
              <div style={{ marginTop: "var(--space-2)" }}>
                <button
                  onClick={() => void handleReject()}
                  disabled={submitting}
                  data-testid="review-reject-confirm-btn"
                  className="btn-danger"
                >
                  {t("superAdmin.inbound.review.rejectConfirmBtn")}
                </button>
                <button
                  onClick={() => {
                    setShowRejectDialog(false);
                    setRejectReason("");
                  }}
                  className="btn-secondary"
                  style={{ marginLeft: "var(--space-2)" }}
                >
                  {t("common.cancel")}
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
