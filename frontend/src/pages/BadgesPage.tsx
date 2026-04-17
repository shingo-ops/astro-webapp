import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Badge { id: number; name: string; description: string | null; icon: string | null; criteria: string | null; points: number; is_active: boolean; created_at: string; }
interface LeaderEntry { user_id: number; username: string | null; badge_count: number; total_points: number; }

export default function BadgesPage() {
  const { hasPermission } = usePermissions();
  const [badges, setBadges] = useState<Badge[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderEntry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", icon: "🏆", criteria: "", points: "10" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setBadges(await api.get<Badge[]>("/badges"));
      setLeaderboard(await api.get<LeaderEntry[]>("/badges/leaderboard"));
    } catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/badges", { name: form.name, description: form.description || null, icon: form.icon || null, criteria: form.criteria || null, points: Number(form.points) });
      setShowForm(false); setForm({ name: "", description: "", icon: "🏆", criteria: "", points: "10" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>バッジ・ゲーミフィケーション</h2>
        {hasPermission("badges.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>バッジ作成</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>バッジ作成</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>バッジ名 *</label><input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="例: 初成約" /></div>
              <div className="form-group"><label>アイコン</label><input value={form.icon} onChange={e => setForm({ ...form, icon: e.target.value })} placeholder="例: 🏆" /></div>
              <div className="form-group"><label>説明</label><textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></div>
              <div className="form-group"><label>獲得条件</label><input value={form.criteria} onChange={e => setForm({ ...form, criteria: e.target.value })} placeholder="例: 初めて案件を成約" /></div>
              <div className="form-group"><label>ポイント</label><input type="number" min="0" value={form.points} onChange={e => setForm({ ...form, points: e.target.value })} /></div>
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
          {leaderboard.length > 0 && (
            <>
              <h3 style={{ marginBottom: 12 }}>リーダーボード</h3>
              <table className="data-table" style={{ marginBottom: 24 }}>
                <thead><tr><th>順位</th><th>ユーザー</th><th>バッジ数</th><th>ポイント</th></tr></thead>
                <tbody>
                  {leaderboard.map((e, i) => (
                    <tr key={e.user_id}>
                      <td style={{ fontWeight: i < 3 ? 700 : 400 }}>{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}`}</td>
                      <td>{e.username || `User #${e.user_id}`}</td>
                      <td>{e.badge_count}</td>
                      <td style={{ fontWeight: 600 }}>{e.total_points} pt</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3 style={{ marginBottom: 12 }}>バッジ一覧</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: 16 }}>
            {badges.map(b => (
              <div key={b.id} style={{ background: "var(--bg-surface)", borderRadius: 8, padding: 16, boxShadow: "var(--shadow-sm)", textAlign: "center" }}>
                <div style={{ fontSize: "2rem" }}>{b.icon || "🏅"}</div>
                <div style={{ fontWeight: 600, marginTop: 8 }}>{b.name}</div>
                <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", marginTop: 4 }}>{b.description || "-"}</div>
                <div style={{ marginTop: 8, fontWeight: 600, color: "var(--accent)" }}>{b.points} pt</div>
              </div>
            ))}
            {badges.length === 0 && <div style={{ color: "var(--text-muted)" }}>バッジがありません</div>}
          </div>
        </>
      )}
    </div>
  );
}
