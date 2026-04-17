import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface StaffReport {
  id: number; report_code: string | null; report_type: string; user_id: number; period: string;
  review: string | null; goals: string | null; challenges: string | null;
  reviewer_comment: string | null; reviewed_at: string | null; submitted_at: string | null; created_at: string;
}
const TYPE_LABELS: Record<string, string> = { daily: "日報", weekly: "週報", monthly: "月報" };

export default function StaffReportsPage() {
  const { hasPermission } = usePermissions();
  const [reports, setReports] = useState<StaffReport[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ report_type: "daily", period: "", review: "", goals: "", challenges: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState("");

  const load = async () => {
    try { setReports(await api.get<StaffReport[]>(`/staff-reports${typeFilter ? `?report_type=${typeFilter}` : ""}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [typeFilter]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/staff-reports", {
        report_type: form.report_type, period: form.period, review: form.review,
        goals: form.goals || null, challenges: form.challenges || null,
      });
      setShowForm(false); setForm({ report_type: "daily", period: "", review: "", goals: "", challenges: "" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>日報・週報・月報</h2>
        {hasPermission("staff_reports.create") && <button className="btn-primary" onClick={() => setShowForm(true)}>レポート提出</button>}
      </div>
      <div className="filter-bar">
        <select value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
          <option value="">全タイプ</option>
          {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>レポート提出</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>タイプ *</label>
                <select value={form.report_type} onChange={e => setForm({ ...form, report_type: e.target.value })}>
                  {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
              <div className="form-group"><label>対象期間 *</label><input required placeholder="例: 2026-04-17 / 2026-W16 / 2026-04" value={form.period} onChange={e => setForm({ ...form, period: e.target.value })} /></div>
              <div className="form-group"><label>振り返り *</label><textarea required value={form.review} onChange={e => setForm({ ...form, review: e.target.value })} style={{ minHeight: 120 }} /></div>
              <div className="form-group"><label>目標</label><textarea value={form.goals} onChange={e => setForm({ ...form, goals: e.target.value })} /></div>
              <div className="form-group"><label>課題</label><textarea value={form.challenges} onChange={e => setForm({ ...form, challenges: e.target.value })} /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">提出</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>コード</th><th>タイプ</th><th>期間</th><th>提出日</th><th>レビュー</th></tr></thead>
          <tbody>
            {reports.map(r => (
              <tr key={r.id}>
                <td className="mono">{r.report_code || "-"}</td>
                <td><span className="badge badge-negotiating">{TYPE_LABELS[r.report_type] || r.report_type}</span></td>
                <td>{r.period}</td>
                <td>{r.submitted_at ? new Date(r.submitted_at).toLocaleDateString() : "-"}</td>
                <td>{r.reviewed_at ? <span className="badge badge-won">レビュー済</span> : <span className="badge badge-pending">未レビュー</span>}</td>
              </tr>
            ))}
            {reports.length === 0 && <tr><td colSpan={5} className="empty">レポートがありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
