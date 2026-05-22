/**
 * 会社の重複マージモーダル（A-4 / PR #145+#152 follow-up）。
 *
 * 役割:
 *   pending_dedup_review として暫定登録された「重複候補」会社（merge 元）を
 *   既存の master 会社へ吸収させる UI。
 *
 *   merge 元の company_id を持つ contacts / deals / orders / quotes / invoices /
 *   company_addresses / company_sales_channels が全て master に付け替えられ、
 *   merge 元の会社は削除される。
 *
 * 安全策:
 *   1. master 候補は同テナント内かつ自分自身を除く active / pending_dedup_review に限定
 *   2. 確定前に「取り消せません」の警告ダイアログ
 *   3. オペレータの判断根拠を audit_logs に残す任意の reason 入力欄
 */

import { useEffect, useMemo, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

interface CompanyOption {
  id: number;
  name: string;
  company_code: string;
  status: string;
}

interface Props {
  open: boolean;
  /** マージ元（吸収されて削除される側）の会社 */
  source: { id: number; name: string; company_code: string };
  /** 成功後コールバック。master の id を渡す（呼び元で詳細リロード or 遷移） */
  onMerged: (masterId: number) => void;
  onCancel: () => void;
}

// バックエンド `/companies` の per_page 上限。テナント保有会社が PER_PAGE_CAP を
// 超えても master 候補が確実に見つかるよう、検索文字が入っている間はサーバー側
// search を使う（PR #164 round1 Major 2 対応）。
const PER_PAGE_CAP = 100;
const SEARCH_DEBOUNCE_MS = 250;

export default function MergeCompanyModal({ open, source, onMerged, onCancel }: Props) {
  const { t } = useTranslation();
  const [candidates, setCandidates] = useState<CompanyOption[]>([]);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedSnapshot, setSelectedSnapshot] = useState<CompanyOption | null>(null);
  const [reason, setReason] = useState("");
  const [stage, setStage] = useState<"select" | "confirm">("select");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // PR #164 round1 Major 2: 全件 100 ヒット時の silent failure 警告
  const [resultsCapped, setResultsCapped] = useState(false);

  // PR #164 round1 Major 2: 旧実装は per_page=100 で初回1回だけロードして
  // クライアント側で includes フィルタ。テナント保有会社が 101 件以上になると
  // 101 件目以降が候補リストに永遠に出てこない silent failure が起きる。
  // 修正: 初回ロード（空 query）と、search 入力時のサーバー側 search 再 fetch を
  // 両方サポートする二段構成。検索時は debounce 250ms で round-trip を抑制する。
  useEffect(() => {
    if (!open) return;
    // モーダル open 時のみ全状態を初期化
    setSelectedId(null);
    setSelectedSnapshot(null);
    setReason("");
    setStage("select");
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const q = search.trim();
    let cancelled = false;
    const handle = window.setTimeout(() => {
      setLoading(true);
      const path = q
        ? `/companies?per_page=${PER_PAGE_CAP}&search=${encodeURIComponent(q)}`
        : `/companies?per_page=${PER_PAGE_CAP}`;
      api
        .get<CompanyOption[]>(path)
        .then((rows) => {
          if (cancelled) return;
          // 自分自身 + archived を除外。pending_dedup_review 同士のマージは許容
          // （重複の両方が候補登録されているケース）。ただし backend 側で master が
          // archived だと 409 を返すので archived はリスト時点で外しておく。
          const filtered = rows.filter(
            (r) => r.id !== source.id && r.status !== "archived",
          );
          setCandidates(filtered);
          setResultsCapped(rows.length >= PER_PAGE_CAP);
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          setError(e instanceof Error ? e.message : t("common.fetchError"));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, q ? SEARCH_DEBOUNCE_MS : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
  }, [open, source.id, search]);

  // 検索文字列が変わって候補リストから消えても、選択済 master を維持できるように
  // クリック時にスナップショットを保持しておく（再 fetch で消えても confirm 画面で参照可能）。
  const selected = useMemo(() => {
    const fromList = candidates.find((c) => c.id === selectedId) || null;
    if (fromList) return fromList;
    if (selectedSnapshot && selectedSnapshot.id === selectedId) return selectedSnapshot;
    return null;
  }, [candidates, selectedId, selectedSnapshot]);

  // server-side search を使うため、表示はそのまま candidates を出すだけ。
  // 旧 useMemo フィルタは不要。
  const filteredCandidates = candidates;

  const handleConfirmSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.post(
        `/companies/${selected.id}/merge?merge_id=${source.id}`,
        { reason: reason.trim() || null },
      );
      onMerged(selected.id);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-content-wide"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 640 }}
      >
        <h2>{t("mergeCompany.title")}</h2>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9em", marginTop: 4 }}>
          {t("mergeCompany.sourceDesc", { name: source.name, code: source.company_code })}
        </p>

        {error && <div className="error-banner">{error}</div>}

        {stage === "select" && (
          <>
            <div className="form-row">
              <label>{t("mergeCompany.selectMaster")}</label>
              <input
                type="text"
                placeholder={t("mergeCompany.searchPlaceholder")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            {resultsCapped && (
              <div
                style={{
                  background: "var(--warning-bg)",
                  border: "1px solid var(--warning-text)",
                  padding: 8,
                  borderRadius: 4,
                  marginTop: 8,
                  fontSize: "0.85em",
                  color: "var(--warning-text)",
                }}
              >
                {t("mergeCompany.resultsCapped", { count: PER_PAGE_CAP })}
              </div>
            )}

            <div
              style={{
                maxHeight: 280,
                overflowY: "auto",
                border: "1px solid var(--border-light)",
                borderRadius: 4,
                marginTop: 8,
              }}
            >
              {loading ? (
                <p style={{ padding: 16, textAlign: "center" }}>{t("common.loading")}</p>
              ) : filteredCandidates.length === 0 ? (
                <p style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
                  {t("mergeCompany.noResults")}
                </p>
              ) : (
                <table className="data-table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}></th>
                      <th>会社コード</th>
                      <th>会社名</th>
                      <th>ステータス</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredCandidates.map((c) => (
                      <tr
                        key={c.id}
                        onClick={() => {
                          setSelectedId(c.id);
                          setSelectedSnapshot(c);
                        }}
                        style={{
                          cursor: "pointer",
                          background: c.id === selectedId ? "var(--warning-bg)" : undefined,
                        }}
                      >
                        <td>
                          <input
                            type="radio"
                            name="master-candidate"
                            checked={c.id === selectedId}
                            onChange={() => {
                              setSelectedId(c.id);
                              setSelectedSnapshot(c);
                            }}
                          />
                        </td>
                        <td>{c.company_code}</td>
                        <td>{c.name}</td>
                        <td>
                          <span className={`status-badge status-${c.status}`}>
                            {c.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="form-row" style={{ marginTop: 16 }}>
              <label>{t("mergeCompany.reasonLabel")}</label>
              <textarea
                rows={2}
                placeholder={t("mergeCompany.reasonPlaceholder")}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
              />
            </div>

            <div className="form-actions">
              <button type="button" onClick={onCancel}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={!selected}
                onClick={() => setStage("confirm")}
              >
                {t("mergeCompany.nextStep")}
              </button>
            </div>
          </>
        )}

        {stage === "confirm" && selected && (
          <form onSubmit={handleConfirmSubmit}>
            <div
              style={{
                background: "var(--warning-bg)",
                border: "1px solid var(--warning-text)",
                padding: 12,
                borderRadius: 4,
                marginBottom: 16,
              }}
            >
              <strong>{t("mergeCompany.confirmWarning")}</strong>
              <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
                <li>
                  {t("mergeCompany.confirmDesc1", {
                    sourceName: source.name,
                    sourceCode: source.company_code,
                    masterName: selected.name,
                    masterCode: selected.company_code,
                  })}
                </li>
                <li>
                  {t("mergeCompany.confirmDesc2", { sourceName: source.name })}
                </li>
                <li>
                  {t("mergeCompany.confirmDesc3")}
                </li>
                <li>{t("mergeCompany.confirmDesc4")}</li>
              </ul>
            </div>

            {reason.trim() && (
              <div
                style={{
                  background: "var(--bg-subtle)",
                  border: "1px solid var(--border)",
                  padding: 8,
                  borderRadius: 4,
                  marginBottom: 16,
                  fontSize: "0.9em",
                }}
              >
                <strong>マージ理由:</strong> {reason.trim()}
              </div>
            )}

            <div className="form-actions">
              <button
                type="button"
                onClick={() => setStage("select")}
                disabled={submitting}
              >
                {t("common.back")}
              </button>
              <button
                type="submit"
                className="btn-danger"
                disabled={submitting}
              >
                {submitting
                  ? t("mergeCompany.merging")
                  : t("mergeCompany.executeLabel", { masterName: selected.name })}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
