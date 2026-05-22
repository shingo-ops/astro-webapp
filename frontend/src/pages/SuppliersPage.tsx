import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
    catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
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
    } catch (e) { setError(e instanceof Error ? e.message : t("common.saveError")); }
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
    catch (e) { setError(e instanceof Error ? e.message : t("common.deleteError")); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("suppliers.title")}</h2>
        {hasPermission("suppliers.create") && <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>{t("suppliers.newSupplier")}</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{editId ? t("suppliers.editSupplier") : t("suppliers.newSupplier")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("suppliers.supplierName")} *</label><input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></div>
              <div className="form-group"><label>{t("suppliers.contactName")}</label><input value={form.contact_name} onChange={e => setForm({ ...form, contact_name: e.target.value })} /></div>
              <div className="form-group"><label>{t("common.email")}</label><input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></div>
              <div className="form-group"><label>{t("common.phone")}</label><input value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} /></div>
              <div className="form-group"><label>{t("suppliers.address")}</label><textarea value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} /></div>
              <div className="form-group"><label>{t("common.notes")}</label><textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{editId ? t("common.update") : t("common.register")}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table">
          <thead><tr><th>{t("common.code")}</th><th>{t("suppliers.supplierName")}</th><th>{t("suppliers.colContact")}</th><th>{t("common.email")}</th><th>{t("common.phone")}</th><th>{t("common.actions")}</th></tr></thead>
          <tbody>
            {suppliers.map(s => (
              <tr key={s.id}>
                <td className="mono">{s.supplier_code || "-"}</td><td>{s.name}</td><td>{s.contact_name || "-"}</td>
                <td>{s.email || "-"}</td><td>{s.phone || "-"}</td>
                <td className="actions">
                  {hasPermission("suppliers.update") && <button className="btn-sm" onClick={() => handleEdit(s)}>{t("common.edit")}</button>}
                  {hasPermission("suppliers.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(s)}>{t("suppliers.deleteSupplier")}</button>}
                </td>
              </tr>
            ))}
            {suppliers.length === 0 && <tr><td colSpan={6} className="empty">{t("suppliers.noSuppliers")}</td></tr>}
          </tbody>
        </table>
      )}
      <ConfirmModal open={!!deleteTarget} title={t("suppliers.deleteSupplier")} message={<><strong>{deleteTarget?.name}</strong>{t("suppliers.disableConfirmSuffix")}</>} confirmLabel={t("suppliers.disableLabel")} danger onConfirm={performDelete} onCancel={() => setDeleteTarget(null)} />
    </div>
  );
}
