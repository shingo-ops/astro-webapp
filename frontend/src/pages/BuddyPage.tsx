import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Pair { id: number; coach_user_id: number; mentee_user_id: number; is_active: boolean; started_at: string; ended_at: string | null; notes: string | null; }
interface Feedback { id: number; pair_id: number; feedback_type: string; reason: string | null; created_by: number; created_at: string; }

export default function BuddyPage() {
  const { hasPermission } = usePermissions();
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ coach_user_id: "", mentee_user_id: "", notes: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setPairs(await api.get<Pair[]>("/buddy/pairs"));
      setFeedbacks(await api.get<Feedback[]>("/buddy/feedbacks"));
    } catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/buddy/pairs", { coach_user_id: Number(form.coach_user_id), mentee_user_id: Number(form.mentee_user_id), notes: form.notes || null });
      setShowForm(false); setForm({ coach_user_id: "", mentee_user_id: "", notes: "" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  const endPair = async (id: number) => {
    try { await api.post(`/buddy/pairs/${id}/end`, {}); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "終了失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Buddy / コーチング</h2>
        {hasPermission("buddy.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>ペアリング作成</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Buddyペアリング作成</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>コーチ ユーザーID *</label><input type="number" min="1" required value={form.coach_user_id} onChange={e => setForm({ ...form, coach_user_id: e.target.value })} /></div>
              <div className="form-group"><label>メンティー ユーザーID *</label><input type="number" min="1" required value={form.mentee_user_id} onChange={e => setForm({ ...form, mentee_user_id: e.target.value })} /></div>
              <div className="form-group"><label>備考</label><textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">作成</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">読み込み中...</div> : (
        <>
          <h3 style={{ marginBottom: 12 }}>ペアリング</h3>
          <table className="data-table" style={{ marginBottom: 24 }}>
            <thead><tr><th>コーチID</th><th>メンティーID</th><th>状態</th><th>開始日</th><th>操作</th></tr></thead>
            <tbody>
              {pairs.map(p => (
                <tr key={p.id}>
                  <td>{p.coach_user_id}</td><td>{p.mentee_user_id}</td>
                  <td><span className={`badge badge-${p.is_active ? "won" : "lost"}`}>{p.is_active ? "アクティブ" : "終了"}</span></td>
                  <td>{new Date(p.started_at).toLocaleDateString()}</td>
                  <td className="actions">{p.is_active && hasPermission("buddy.manage") && <button className="btn-sm btn-danger" onClick={() => endPair(p.id)}>終了</button>}</td>
                </tr>
              ))}
              {pairs.length === 0 && <tr><td colSpan={5} className="empty">ペアリングがありません</td></tr>}
            </tbody>
          </table>
          <h3 style={{ marginBottom: 12 }}>フィードバック履歴</h3>
          <table className="data-table">
            <thead><tr><th>ペアID</th><th>種別</th><th>理由</th><th>投稿日</th></tr></thead>
            <tbody>
              {feedbacks.map(f => (
                <tr key={f.id}>
                  <td>{f.pair_id}</td>
                  <td><span className={`badge badge-${f.feedback_type === "Good" ? "won" : "lost"}`}>{f.feedback_type}</span></td>
                  <td>{f.reason || "-"}</td><td>{new Date(f.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
              {feedbacks.length === 0 && <tr><td colSpan={4} className="empty">フィードバックがありません</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
