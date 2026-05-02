import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import CompanyContactSelector from "../components/CompanyContactSelector";

interface Order {
  id: number;
  // Step 5d: 旧 customer_id を撤去、company_id を必須化
  company_id: number;
  contact_id: number | null;
  deal_id: number | null;
  order_number: string;
  total_amount: number | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

interface CompanyMini {
  id: number;
  company_code: string;
  name: string;
}

const STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"];
const STATUS_LABELS: Record<string, string> = {
  pending: "保留", confirmed: "確定", shipped: "出荷済", delivered: "納品済", cancelled: "キャンセル",
};

// 注文の (company_id, contact_id) は作成後変更不可（backend OrderUpdate にも含まれない）
// ため、編集モードではセレクタを disabled にする。Step 5d で旧 customer_id 経路は撤去済。
const emptyForm = { deal_id: "", order_number: "", total_amount: "", status: "pending", notes: "" };

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [companies, setCompanies] = useState<CompanyMini[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [contactId, setContactId] = useState<number | null>(null);
  const [selectorError, setSelectorError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Order | null>(null);

  const loadOrders = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Order[]>(`/orders${params}`);
      setOrders(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadCompanies = async () => {
    try {
      // backend `/companies` は per_page le=100 制約のため 100 を上限に揃える
      const data = await api.get<CompanyMini[]>("/companies?per_page=100");
      setCompanies(data.map((c) => ({ id: c.id, company_code: c.company_code, name: c.name })));
    } catch { /* ignore */ }
  };

  useEffect(() => { loadOrders(); }, [statusFilter]);
  useEffect(() => { loadCompanies(); }, []);

  const resetSelector = () => {
    setCompanyId(null);
    setContactId(null);
    setSelectorError("");
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSelectorError("");
    if (!editId && contactId === null) {
      setSelectorError("会社と担当者を選択してください");
      return;
    }
    // 新規作成時のみ company_id/contact_id を送信。編集時は変更不可なので含めない。
    const basePayload = {
      deal_id: form.deal_id ? Number(form.deal_id) : null,
      order_number: form.order_number,
      total_amount: form.total_amount ? Number(form.total_amount) : null,
      status: form.status,
      notes: form.notes || null,
    };
    const payload = editId
      ? basePayload
      : { ...basePayload, company_id: companyId, contact_id: contactId };
    try {
      if (editId) {
        await api.patch(`/orders/${editId}`, payload);
      } else {
        await api.post("/orders", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      resetSelector();
      loadOrders();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (o: Order) => {
    setEditId(o.id);
    setForm({
      deal_id: o.deal_id ? String(o.deal_id) : "",
      order_number: o.order_number,
      total_amount: o.total_amount ? String(o.total_amount) : "",
      status: o.status,
      notes: o.notes || "",
    });
    setCompanyId(o.company_id);
    setContactId(o.contact_id);
    setSelectorError("");
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/orders/${id}`);
      loadOrders();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const fmt = (n: number) => n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });
  const companyName = (id: number | null) => {
    if (!id) return "-";
    const c = companies.find((c) => c.id === id);
    return c ? `${c.name}（${c.company_code}）` : `#${id}`;
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>注文管理</h2>
        <button
          className="btn-primary"
          onClick={() => {
            setShowForm(true);
            setEditId(null);
            setForm(emptyForm);
            resetSelector();
          }}
        >
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
            <h3>{editId ? "注文編集" : "新規注文登録"}</h3>
            <form onSubmit={handleSubmit}>
              <CompanyContactSelector
                value={{ companyId, contactId }}
                onChange={({ companyId: c, contactId: ct }) => {
                  setCompanyId(c);
                  setContactId(ct);
                }}
                required={!editId}
                disabled={editId !== null}
                error={selectorError}
                companies={companies}
              />
              {editId && (
                <p style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginTop: -8 }}>
                  ※ 注文の会社・担当者は作成後変更できません
                </p>
              )}
              <div className="form-group">
                <label>注文番号 *</label>
                <input required value={form.order_number} onChange={(e) => setForm({ ...form, order_number: e.target.value })} />
              </div>
              <div className="form-group">
                <label>合計金額</label>
                <input type="number" min="0" step="1" value={form.total_amount} onChange={(e) => setForm({ ...form, total_amount: e.target.value })} />
              </div>
              <div className="form-group">
                <label>ステータス</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
                </select>
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
              <th>注文番号</th>
              <th>会社</th>
              <th>合計金額</th>
              <th>ステータス</th>
              <th>登録日</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>{o.order_number}</td>
                <td>{companyName(o.company_id)}</td>
                <td>{o.total_amount ? fmt(o.total_amount) : "-"}</td>
                <td><span className={`badge badge-${o.status}`}>{STATUS_LABELS[o.status] || o.status}</span></td>
                <td>{new Date(o.created_at).toLocaleDateString("ja-JP")}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => handleEdit(o)}>編集</button>
                  <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(o)}>削除</button>
                </td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr><td colSpan={6} className="empty">注文が登録されていません</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="注文を削除"
        message={
          <>
            注文番号 <strong>{deleteTarget?.order_number}</strong> を削除します。<br />
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
