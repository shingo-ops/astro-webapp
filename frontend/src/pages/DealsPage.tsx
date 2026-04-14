import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";

interface Deal {
  id: number;
  customer_id: number;
  title: string;
  amount: number | null;
  status: string;
  expected_close_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface Customer { id: number; name: string; }

const STATUSES = ["open", "negotiating", "won", "lost", "on_hold"];
const STATUS_LABELS: Record<string, string> = {
  open: "進行中", negotiating: "交渉中", won: "成約", lost: "失注", on_hold: "保留",
};

const emptyForm = { customer_id: "", title: "", amount: "", status: "open", expected_close_date: "", notes: "" };

export default function DealsPage() {
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
    const payload = {
      customer_id: Number(form.customer_id),
      title: form.title,
      amount: form.amount ? Number(form.amount) : null,
      status: form.status,
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
      customer_id: String(d.customer_id),
      title: d.title,
      amount: d.amount ? String(d.amount) : "",
      status: d.status,
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

  const fmt = (n: number) => n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });
  const customerName = (id: number) => customers.find((c) => c.id === id)?.name || `ID:${id}`;

  return (
    <div className="page">
      <div className="page-header">
        <h2>案件管理</h2>
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>
          新規登録
        </button>
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
              <div className="form-group">
                <label>顧客 *</label>
                <select required value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })}>
                  <option value="">選択してください</option>
                  {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>タイトル *</label>
                <input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </div>
              <div className="form-group">
                <label>金額</label>
                <input type="number" min="0" step="1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
              </div>
              <div className="form-group">
                <label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>成約予定日</label>
                <input type="date" value={form.expected_close_date} onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })} />
              </div>
              <div className="form-group">
                <label>備考</label>
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
              <th>タイトル</th>
              <th>顧客</th>
              <th>金額</th>
              <th>ステータス</th>
              <th>成約予定日</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {deals.map((d) => (
              <tr key={d.id}>
                <td>{d.title}</td>
                <td>{customerName(d.customer_id)}</td>
                <td>{d.amount ? fmt(d.amount) : "-"}</td>
                <td><span className={`badge badge-${d.status}`}>{STATUS_LABELS[d.status] || d.status}</span></td>
                <td>{d.expected_close_date || "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => handleEdit(d)}>編集</button>
                  <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(d)}>削除</button>
                </td>
              </tr>
            ))}
            {deals.length === 0 && (
              <tr><td colSpan={6} className="empty">商談が登録されていません</td></tr>
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
