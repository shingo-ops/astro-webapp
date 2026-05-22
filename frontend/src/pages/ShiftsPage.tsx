import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Shift { id: number; user_id: number; shift_date: string; start_time: string; end_time: string; shift_type: string; notes: string | null; created_at: string; }

export default function ShiftsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ user_id: "", shift_date: "", start_time: "09:00", end_time: "18:00", shift_type: "normal", notes: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setShifts(await api.get<Shift[]>("/shifts")); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/shifts", { user_id: Number(form.user_id), shift_date: form.shift_date, start_time: form.start_time, end_time: form.end_time, shift_type: form.shift_type, notes: form.notes || null });
      setShowForm(false); load();
    } catch (e) { setError(e instanceof Error ? e.message : t("common.saveError")); }
  };

  const handleDelete = async (id: number) => {
    try { await api.delete(`/shifts/${id}`); load(); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.deleteError")); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("shifts.title")}</h2>
        {hasPermission("shifts.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>{t("shifts.newShift")}</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{t("shifts.newShift")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("shifts.userId")} *</label><input type="number" min="1" required value={form.user_id} onChange={e => setForm({ ...form, user_id: e.target.value })} /></div>
              <div className="form-group"><label>{t("common.date")} *</label><input type="date" required value={form.shift_date} onChange={e => setForm({ ...form, shift_date: e.target.value })} /></div>
              <div className="form-group"><label>{t("shifts.startTime")} *</label><input type="time" required value={form.start_time} onChange={e => setForm({ ...form, start_time: e.target.value })} /></div>
              <div className="form-group"><label>{t("shifts.endTime")} *</label><input type="time" required value={form.end_time} onChange={e => setForm({ ...form, end_time: e.target.value })} /></div>
              <div className="form-group"><label>{t("shifts.shiftType")}</label>
                <select value={form.shift_type} onChange={e => setForm({ ...form, shift_type: e.target.value })}>
                  <option value="normal">{t("shifts.type_normal")}</option><option value="early">{t("shifts.type_early")}</option><option value="late">{t("shifts.type_late")}</option><option value="night">{t("shifts.type_night")}</option><option value="off">{t("shifts.type_off")}</option>
                </select>
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{t("common.register")}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table">
          <thead><tr><th>{t("common.date")}</th><th>{t("shifts.userId")}</th><th>{t("shifts.colStart")}</th><th>{t("shifts.colEnd")}</th><th>{t("shifts.shiftType")}</th><th>{t("common.actions")}</th></tr></thead>
          <tbody>
            {shifts.map(s => (
              <tr key={s.id}>
                <td>{s.shift_date}</td><td>{s.user_id}</td><td>{s.start_time}</td><td>{s.end_time}</td>
                <td><span className="badge badge-negotiating">{s.shift_type}</span></td>
                <td className="actions">{hasPermission("shifts.manage") && <button className="btn-sm btn-danger" onClick={() => handleDelete(s.id)}>{t("common.delete")}</button>}</td>
              </tr>
            ))}
            {shifts.length === 0 && <tr><td colSpan={6} className="empty">{t("shifts.noShifts")}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
