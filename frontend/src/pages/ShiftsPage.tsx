import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Shift { id: number; user_id: number; shift_date: string; start_time: string; end_time: string; shift_type: string; notes: string | null; created_at: string; }

export default function ShiftsPage() {
  const { hasPermission } = usePermissions();
  const [shifts, setShifts] = useState<Shift[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ user_id: "", shift_date: "", start_time: "09:00", end_time: "18:00", shift_type: "normal", notes: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setShifts(await api.get<Shift[]>("/shifts")); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/shifts", { user_id: Number(form.user_id), shift_date: form.shift_date, start_time: form.start_time, end_time: form.end_time, shift_type: form.shift_type, notes: form.notes || null });
      setShowForm(false); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  const handleDelete = async (id: number) => {
    try { await api.delete(`/shifts/${id}`); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "削除失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>シフト管理</h2>
        {hasPermission("shifts.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>シフト登録</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>シフト登録</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>ユーザーID *</label><input type="number" min="1" required value={form.user_id} onChange={e => setForm({ ...form, user_id: e.target.value })} /></div>
              <div className="form-group"><label>日付 *</label><input type="date" required value={form.shift_date} onChange={e => setForm({ ...form, shift_date: e.target.value })} /></div>
              <div className="form-group"><label>開始時刻 *</label><input type="time" required value={form.start_time} onChange={e => setForm({ ...form, start_time: e.target.value })} /></div>
              <div className="form-group"><label>終了時刻 *</label><input type="time" required value={form.end_time} onChange={e => setForm({ ...form, end_time: e.target.value })} /></div>
              <div className="form-group"><label>種別</label>
                <select value={form.shift_type} onChange={e => setForm({ ...form, shift_type: e.target.value })}>
                  <option value="normal">通常</option><option value="early">早番</option><option value="late">遅番</option><option value="night">夜勤</option><option value="off">休日</option>
                </select>
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">登録</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>日付</th><th>ユーザーID</th><th>開始</th><th>終了</th><th>種別</th><th>操作</th></tr></thead>
          <tbody>
            {shifts.map(s => (
              <tr key={s.id}>
                <td>{s.shift_date}</td><td>{s.user_id}</td><td>{s.start_time}</td><td>{s.end_time}</td>
                <td><span className="badge badge-negotiating">{s.shift_type}</span></td>
                <td className="actions">{hasPermission("shifts.manage") && <button className="btn-sm btn-danger" onClick={() => handleDelete(s.id)}>削除</button>}</td>
              </tr>
            ))}
            {shifts.length === 0 && <tr><td colSpan={6} className="empty">シフトがありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
