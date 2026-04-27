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

export default function MergeCompanyModal({ open, source, onMerged, onCancel }: Props) {
  const [candidates, setCandidates] = useState<CompanyOption[]>([]);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [stage, setStage] = useState<"select" | "confirm">("select");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // モーダルを開いた直後に master 候補一覧をロード
  useEffect(() => {
    if (!open) return;
    setSearch("");
    setSelectedId(null);
    setReason("");
    setStage("select");
    setError(null);
    setLoading(true);
    api
      .get<CompanyOption[]>(`/companies?per_page=100`)
      .then((rows) => {
        // 自分自身 + archived を除外。pending_dedup_review 同士のマージは許容
        // （重複の両方が候補登録されているケース）。ただし backend 側で master が
        // archived だと 409 を返すので archived はリスト時点で外しておく。
        const filtered = rows.filter(
          (r) => r.id !== source.id && r.status !== "archived",
        );
        setCandidates(filtered);
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "会社一覧の取得に失敗しました");
      })
      .finally(() => setLoading(false));
  }, [open, source.id]);

  const filteredCandidates = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return candidates;
    return candidates.filter(
      (c) =>
        c.name.toLowerCase().includes(q) || c.company_code.toLowerCase().includes(q),
    );
  }, [candidates, search]);

  const selected = candidates.find((c) => c.id === selectedId) || null;

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
      setError(e instanceof Error ? e.message : "マージに失敗しました");
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
        <h2>重複としてマージ</h2>
        <p style={{ color: "#666", fontSize: "0.9em", marginTop: 4 }}>
          「{source.name}」（{source.company_code}）を既存の会社に吸収させます。
        </p>

        {error && <div className="error-banner">{error}</div>}

        {stage === "select" && (
          <>
            <div className="form-row">
              <label>マージ先（master）の会社を選択</label>
              <input
                type="text"
                placeholder="会社名 / 会社コードで絞り込み"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                disabled={loading}
              />
            </div>

            <div
              style={{
                maxHeight: 280,
                overflowY: "auto",
                border: "1px solid #ddd",
                borderRadius: 4,
                marginTop: 8,
              }}
            >
              {loading ? (
                <p style={{ padding: 16, textAlign: "center" }}>読み込み中...</p>
              ) : filteredCandidates.length === 0 ? (
                <p style={{ padding: 16, textAlign: "center", color: "#888" }}>
                  該当する会社がありません
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
                        onClick={() => setSelectedId(c.id)}
                        style={{
                          cursor: "pointer",
                          background: c.id === selectedId ? "#fff3cd" : undefined,
                        }}
                      >
                        <td>
                          <input
                            type="radio"
                            name="master-candidate"
                            checked={c.id === selectedId}
                            onChange={() => setSelectedId(c.id)}
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
              <label>マージ理由（任意 / audit_logs に記録）</label>
              <textarea
                rows={2}
                placeholder="例: 同一法人の支店登録ミス、CSV 取り込み重複など"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={500}
              />
            </div>

            <div className="form-actions">
              <button type="button" onClick={onCancel}>
                キャンセル
              </button>
              <button
                type="button"
                className="btn-primary"
                disabled={!selected}
                onClick={() => setStage("confirm")}
              >
                次へ（マージ内容を確認）
              </button>
            </div>
          </>
        )}

        {stage === "confirm" && selected && (
          <form onSubmit={handleConfirmSubmit}>
            <div
              style={{
                background: "#fff3cd",
                border: "1px solid #ffeeba",
                padding: 12,
                borderRadius: 4,
                marginBottom: 16,
              }}
            >
              <strong>確認: この操作は取り消せません</strong>
              <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
                <li>
                  「{source.name}」（{source.company_code}）に紐づく
                  <strong>担当者・商談・注文・見積・請求書・住所・販売チャネル</strong>が
                  全て「{selected.name}」（{selected.company_code}）に付け替えられます。
                </li>
                <li>
                  「{source.name}」の会社レコードは削除されます。
                </li>
                <li>
                  master 側が pending_dedup_review だった場合、自動的に active に
                  昇格します。
                </li>
                <li>監査ログ (audit_logs) に操作内容が記録されます。</li>
              </ul>
            </div>

            {reason.trim() && (
              <div
                style={{
                  background: "#f8f9fa",
                  border: "1px solid #e9ecef",
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
                戻る
              </button>
              <button
                type="submit"
                className="btn-danger"
                disabled={submitting}
              >
                {submitting
                  ? "マージ中..."
                  : `「${selected.name}」へマージを実行`}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
