/**
 * 案件管理ページ。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1拡張（deal_code/stage/probability/currency/assigned_to 追加、
 *     権限チェック連動）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

interface Deal {
  id: number;
  deal_code: string | null;
  customer_id: number | null;
  lead_id: number | null;
  title: string;
  amount: number | null;
  currency: string | null;
  status: string;
  stage: string | null;
  probability: number | null;
  lost_reason: string | null;
  assigned_to: number | null;
  expected_close_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface Customer {
  id: number;
  customer_code: string;
  company_name: string | null;
  billing_display_name: string | null;
}
/** 顧客の表示名: billing_display_name > company_name > customer_code */
const customerLabel = (c: Customer): string =>
  c.billing_display_name || c.company_name || c.customer_code;

const STATUSES = ["open", "negotiating", "won", "lost", "on_hold"];
const STATUS_LABELS: Record<string, string> = {
  open: "オープン", negotiating: "交渉中", won: "成約", lost: "失注", on_hold: "保留",
};
const STAGES = ["open", "negotiating", "proposal", "won", "lost", "on_hold"];
const STAGE_LABELS: Record<string, string> = {
  open: "初回接触", negotiating: "ヒアリング中", proposal: "提案済", won: "成約", lost: "失注", on_hold: "保留",
};

const emptyForm = {
  customer_id: "", title: "", amount: "", currency: "JPY",
  status: "open", stage: "open", probability: "10", lost_reason: "",
  assigned_to: "", expected_close_date: "", notes: "",
};

export default function DealsPage() {
  const { hasPermission } = usePermissions();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);

  const loadDeals = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Deal[]>(`/deals${params}`);
      setDeals(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadCustomers = async () => {
    try {
      const data = await api.get<Customer[]>("/customers?per_page=100");
      setCustomers(data);
    } catch { /* ignore */ }
  };

  useEffect(() => { loadDeals(); loadCustomers(); }, [statusFilter]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const payload: Record<string, unknown> = {
      customer_id: Number(form.customer_id),
      title: form.title,
      amount: form.amount ? Number(form.amount) : null,
      currency: form.currency,
      status: form.status,
      stage: form.stage,
      probability: form.probability ? Number(form.probability) : null,
      lost_reason: form.lost_reason || null,
      assigned_to: form.assigned_to ? Number(form.assigned_to) : null,
      expected_close_date: form.expected_close_date || null,
      notes: form.notes || null,
    };
    try {
      if (editId) {
        await api.patch(`/deals/${editId}`, payload);
      } else {
        await api.post("/deals", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (d: Deal) => {
    setEditId(d.id);
    setForm({
      customer_id: d.customer_id != null ? String(d.customer_id) : "",
      title: d.title,
      amount: d.amount != null ? String(d.amount) : "",
      currency: d.currency || "JPY",
      status: d.status,
      stage: d.stage || "open",
      probability: d.probability != null ? String(d.probability) : "10",
      lost_reason: d.lost_reason || "",
      assigned_to: d.assigned_to != null ? String(d.assigned_to) : "",
      expected_close_date: d.expected_close_date || "",
      notes: d.notes || "",
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/deals/${id}`);
      loadDeals();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const fmt = (n: number, ccy: string | null) => {
    const cur = ccy || "JPY";
    try {
      return n.toLocaleString("ja-JP", { style: "currency", currency: cur });
    } catch {
      return `${cur} ${n.toLocaleString()}`;
    }
  };
  const customerName = (id: number | null) => {
    if (!id) return "-";
    const c = customers.find((c) => c.id === id);
    return c ? customerLabel(c) : `ID:${id}`;
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>案件管理</h2>
        {hasPermission("deals.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>
            新規登録
          </button>
        )}
      </div>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">全ステータス</option>
          {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "商談編集" : "新規商談登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>顧客 *</label>
                <select required value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })}>
                  <option value="">選択してください</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{customerLabel(c)}</option>)}
                </select>
              </div>
              <div className="form-group"><label>タイトル *</label>
                <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </div>
              <div className="form-group"><label>金額</label>
                <input type="number" min="0" step="1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div className="form-group"><label>通貨</label>
                <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
                  <option value="JPY">JPY</option>
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                </select>
              </div>
              <div className="form-group"><label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                </select>
              </div>
              <div className="form-group"><label>ステージ</label>
                <select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                  {STAGES.map((s) => <option key={s} value={s}>{STAGE_LABELS[s]}</option>)}
                </select>
              </div>
              <div className="form-group"><label>成約確率 (%)</label>
                <input type="number" min="0" max="100" value={form.probability} onChange={(e) => setForm({ ...form, probability: e.target.value })} />
              </div>
              <div className="form-group"><label>担当者ユーザーID</label>
                <input type="number" min="1" value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })} />
              </div>
              <div className="form-group"><label>成約予定日</label>
                <input type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
              </div>
              {form.status === "lost" && (
                <div className="form-group"><label>失注理由</label>
                  <input value={form.lost_reason} onChange={(e) => setForm({ ...form, lost_reason: e.target.value })} />
                </div>
              )}
              <div className="form-group"><label>備考</label>
                <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">{editId ? "更新" : "登録"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>コード</th>
              <th>タイトル</th>
              <th>顧客</th>
              <th>金額</th>
              <th>ステージ</th>
              <th>確率</th>
              <th>ステータス</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={d.id}>
                <td className="mono">{d.deal_code || "-"}</td>
                <td>{d.title}</td>
                <td>{customerName(d.customer_id)}</td>
                <td>{d.amount ? fmt(d.amount, d.currency) : "-"}</td>
                <td>{d.stage ? (STAGE_LABELS[d.stage] || d.stage) : "-"}</td>
                <td>{d.probability != null ? `${d.probability}%` : "-"}</td>
                <td><span className={`badge badge-${d.status}`}>{STATUS_LABELS[d.status] || d.status}</span></td>
                <td className="actions">
                  {hasPermission("deals.update") && <button className="btn-sm" onClick={() => handleEdit(d)}>編集</button>}
                  {hasPermission("deals.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(d)}>削除</button>}
                </td>
              </tr>
            ))}
            {deals.length === 0 && (
              <tr><td colSpan={8} className="empty">商談が登録されていません</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="商談を削除"
        message={
          <>
            <strong>{deleteTarget?.title}</strong> を削除します。<br />
            関連する注文がある場合は削除できません（先に注文を削除してください）。<br />
            この操作は取り消せません。
          </>
        }
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
