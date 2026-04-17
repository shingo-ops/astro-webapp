import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

interface Supplier {
  id: number; supplier_code: string | null; name: string; contact_name: string | null;
  email: string | null; phone: string | null; address: string | null;
  notes: string | null; is_active: boolean; created_at: string;
}

const emptyForm = { name: "", contact_name: "", email: "", phone: "", address: "", notes: "" };

export default function SuppliersPage() {
  const { hasPermission } = usePermissions();
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Supplier | null>(null);

  const load = async () => {
    try { setSuppliers(await api.get<Supplier[]>("/suppliers")); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    const toNull = (v: string) => v || null;
    const payload = { name: form.name, contact_name: toNull(form.contact_name), email: toNull(form.email), phone: toNull(form.phone), address: toNull(form.address), notes: toNull(form.notes) };
    try {
      if (editId) await api.patch(`/suppliers/${editId}`, payload);
      else await api.post("/suppliers", payload);
      setShowForm(false); setEditId(null); setForm(emptyForm); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  const handleEdit = (s: Supplier) => {
    setEditId(s.id);
    setForm({ name: s.name, contact_name: s.contact_name || "", email: s.email || "", phone: s.phone || "", address: s.address || "", notes: s.notes || "" });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    setDeleteTarget(null);
    try { await api.delete(`/suppliers/${deleteTarget.id}`); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "削除失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>仕入先管理</h2>
        {hasPermission("suppliers.create") && <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>仕入先登録</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{editId ? "仕入先編集" : "仕入先登録"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>仕入先名 *</label><input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
              <div className="form-group"><label>担当者名</label><input value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} /></div>
              <div className="form-group"><label>メール</label><input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
              <div className="form-group"><label>電話番号</label><input value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} /></div>
              <div className="form-group"><label>住所</label><textarea value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></div>
              <div className="form-group"><label>備考</label><textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">{editId ? "更新" : "登録"}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>コード</th><th>仕入先名</th><th>担当者</th><th>メール</th><th>電話</th><th>操作</th></tr></thead>
          <tbody>
            {suppliers.map(s => (
              <tr key={s.id}>
                <td className="mono">{s.supplier_code || "-"}</td><td>{s.name}</td><td>{s.contact_name || "-"}</td>
                <td>{s.email || "-"}</td><td>{s.phone || "-"}</td>
                <td className="actions">
                  {hasPermission("suppliers.update") && <button className="btn-sm" onClick={() => handleEdit(s)}>編集</button>}
                  {hasPermission("suppliers.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(s)}>無効化</button>}
                </td>
              </tr>
            ))}
            {suppliers.length === 0 && <tr><td colSpan={6} className="empty">仕入先がありません</td></tr>}
          </tbody>
        </table>
      )}
      <ConfirmModal open={!!deleteTarget} title="仕入先を無効化" message={<><strong>{deleteTarget?.name}</strong> を無効化します。</>} confirmLabel="無効化" danger onConfirm={performDelete} onCancel={() => setDeleteTarget(null)} />
    </div>
  );
}
