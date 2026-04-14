import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";

const PHONE_RE = /^(\+?\d{10,15}|0\d{9,10})$/;
const validatePhoneClient = (raw: string): string | null => {
  if (!raw) return null;
  const cleaned = raw.replace(/[\s\-()]/g, "");
  return PHONE_RE.test(cleaned) ? null : "電話番号の形式が正しくありません（例: 03-1234-5678, 090-1234-5678）";
};

interface Customer {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

const emptyForm = { name: "", email: "", phone: "", company: "", notes: "" };

export default function CustomersPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);

  const loadCustomers = async () => {
    try {
      const params = search ? `?search=${encodeURIComponent(search)}` : "";
      const data = await api.get<Customer[]>(`/customers${params}`);
      setCustomers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadCustomers(); }, [search]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const phoneErr = validatePhoneClient(form.phone);
    if (phoneErr) {
      setPhoneError(phoneErr);
      return;
    }
    setPhoneError(null);
    const payload = {
      name: form.name,
      email: form.email || null,
      phone: form.phone || null,
      company: form.company || null,
      notes: form.notes || null,
    };
    try {
      if (editId) {
        await api.patch(`/customers/${editId}`, payload);
      } else {
        await api.post("/customers", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadCustomers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (c: Customer) => {
    setEditId(c.id);
    setForm({
      name: c.name,
      email: c.email || "",
      phone: c.phone || "",
      company: c.company || "",
      notes: c.notes || "",
    });
    setPhoneError(null);
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/customers/${id}`);
      loadCustomers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>顧客管理</h2>
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); setPhoneError(null); }}>
          新規登録
        </button>
      </div>

      <div className="search-bar">
        <input
          type="text"
          placeholder="名前・メール・会社名で検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "顧客編集" : "新規顧客登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group">
                <label>名前 *</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group">
                <label>メール</label>
                <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="form-group">
                <label>電話番号</label>
                <input
                  value={form.phone}
                  placeholder="例: 03-1234-5678 または 090-1234-5678"
                  onChange={(e) => { setForm({ ...form, phone: e.target.value }); if (phoneError) setPhoneError(null); }}
                  onBlur={(e) => setPhoneError(validatePhoneClient(e.target.value))}
                />
                {phoneError && <div className="error-message" style={{ marginTop: 4 }}>{phoneError}</div>}
              </div>
              <div className="form-group">
                <label>会社名</label>
                <input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
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
              <th>名前</th>
              <th>メール</th>
              <th>電話番号</th>
              <th>会社名</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {customers.map((c) => (
              <tr key={c.id}>
                <td>{c.name}</td>
                <td>{c.email || "-"}</td>
                <td>{c.phone || "-"}</td>
                <td>{c.company || "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => handleEdit(c)}>編集</button>
                  <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(c)}>削除</button>
                </td>
              </tr>
            ))}
            {customers.length === 0 && (
              <tr><td colSpan={5} className="empty">顧客が登録されていません</td></tr>
            )}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="顧客を削除"
        message={
          <>
            <strong>{deleteTarget?.name}</strong> を削除します。<br />
            関連する商談・注文がある場合は削除できません（先にそれらを削除してください）。<br />
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
