import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Badge { id: number; name: string; description: string | null; icon: string | null; criteria: string | null; points: number; is_active: boolean; created_at: string; }
interface LeaderEntry { user_id: number; username: string | null; badge_count: number; total_points: number; }

export default function BadgesPage() {
  const { t } = useTranslation();
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
    } catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/badges", { name: form.name, description: form.description || null, icon: form.icon || null, criteria: form.criteria || null, points: Number(form.points) });
      setShowForm(false); setForm({ name: "", description: "", icon: "🏆", criteria: "", points: "10" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : t("common.saveError")); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("badges.title")}</h2>
        {hasPermission("badges.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>{t("badges.newBadge")}</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{t("badges.newBadge")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("badges.badgeName")} *</label><input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="例: 初成約" /></div>
              <div className="form-group"><label>{t("badges.icon")}</label><input value={form.icon} onChange={e => setForm({ ...form, icon: e.target.value })} placeholder="例: 🏆" /></div>
              <div className="form-group"><label>{t("common.description")}</label><textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} /></div>
              <div className="form-group"><label>{t("badges.criteria")}</label><input value={form.criteria} onChange={e => setForm({ ...form, criteria: e.target.value })} placeholder="例: 初めて案件を成約" /></div>
              <div className="form-group"><label>{t("badges.points")}</label><input type="number" min="0" value={form.points} onChange={e => setForm({ ...form, points: e.target.value })} /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{t("common.create")}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <>
          {leaderboard.length > 0 && (
            <>
              <h3 style={{ marginBottom: "var(--space-3)" }}>{t("badges.leaderboard")}</h3>
              <table className="data-table" style={{ marginBottom: "var(--space-6)" }}>
                <thead><tr><th>{t("badges.rank")}</th><th>{t("badges.user")}</th><th>{t("badges.badgeCount")}</th><th>{t("badges.points")}</th></tr></thead>
                <tbody>
                  {leaderboard.map((e, i) => (
                    <tr key={e.user_id}>
                      <td style={{ fontWeight: i < 3 ? 700 : 400 }}>{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}`}</td>
                      <td>{e.username || `User #${e.user_id}`}</td>
                      <td>{e.badge_count}</td>
                      <td style={{ fontWeight: "var(--font-weight-semi)" }}>{e.total_points} pt</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <h3 style={{ marginBottom: "var(--space-3)" }}>{t("badges.badgeList")}</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))", gap: "var(--space-4)" }}>
            {badges.map(b => (
              <div key={b.id} style={{ background: "var(--bg-surface)", borderRadius: 8, padding: "var(--space-4)", boxShadow: "var(--shadow-sm)", textAlign: "center" }}>
                <div style={{ fontSize: "var(--font-3xl)" }}>{b.icon || "🏅"}</div>
                <div style={{ fontWeight: "var(--font-weight-semi)", marginTop: "var(--space-2)" }}>{b.name}</div>
                <div style={{ color: "var(--text-muted)", fontSize: "var(--font-sm)", marginTop: "var(--space-1)" }}>{b.description || "-"}</div>
                <div style={{ marginTop: "var(--space-2)", fontWeight: "var(--font-weight-semi)", color: "var(--accent)" }}>{b.points} pt</div>
              </div>
            ))}
            {badges.length === 0 && <div style={{ color: "var(--text-muted)" }}>{t("badges.noBadges")}</div>}
          </div>
        </>
      )}
    </div>
  );
}
