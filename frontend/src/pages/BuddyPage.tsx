import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";
import { PageLayout } from "../components/PageLayout";

interface Pair { id: number; coach_user_id: number; mentee_user_id: number; is_active: boolean; started_at: string; ended_at: string | null; notes: string | null; }
interface Feedback { id: number; pair_id: number; feedback_type: string; reason: string | null; created_by: number; created_at: string; }

export default function BuddyPage() {
  const { t } = useTranslation();
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
    } catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/buddy/pairs", { coach_user_id: Number(form.coach_user_id), mentee_user_id: Number(form.mentee_user_id), notes: form.notes || null });
      setShowForm(false); setForm({ coach_user_id: "", mentee_user_id: "", notes: "" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : t("common.saveError")); }
  };

  const endPair = async (id: number) => {
    try { await api.post(`/buddy/pairs/${id}/end`, {}); load(); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.operationError")); }
  };

  return (
    <PageLayout
      navKey="nav.buddy"
      headerAction={hasPermission("buddy.manage") ? (
        <button className="btn-primary" onClick={() => setShowForm(true)}>{t("buddy.newPair")}</button>
      ) : undefined}
    >
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{t("buddy.newPair")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("buddy.coachUserId")} *</label><input type="number" min="1" required value={form.coach_user_id} onChange={e => setForm({ ...form, coach_user_id: e.target.value })} /></div>
              <div className="form-group"><label>{t("buddy.menteeUserId")} *</label><input type="number" min="1" required value={form.mentee_user_id} onChange={e => setForm({ ...form, mentee_user_id: e.target.value })} /></div>
              <div className="form-group"><label>{t("common.notes")}</label><textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /></div>
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
          <h3 style={{ marginBottom: "var(--space-3)" }}>{t("buddy.pairsTitle")}</h3>
          <table className="data-table" style={{ marginBottom: "var(--space-6)" }}>
            <thead><tr><th>{t("buddy.coachId")}</th><th>{t("buddy.menteeId")}</th><th>{t("common.status")}</th><th>{t("buddy.startedAt")}</th><th>{t("common.actions")}</th></tr></thead>
            <tbody>
              {pairs.map(p => (
                <tr key={p.id}>
                  <td>{p.coach_user_id}</td><td>{p.mentee_user_id}</td>
                  <td><span className={`badge badge-${p.is_active ? "won" : "lost"}`}>{p.is_active ? t("common.active") : t("buddy.ended")}</span></td>
                  <td>{new Date(p.started_at).toLocaleDateString()}</td>
                  <td className="actions">{p.is_active && hasPermission("buddy.manage") && <button className="btn-sm btn-danger" onClick={() => endPair(p.id)}>{t("buddy.end")}</button>}</td>
                </tr>
              ))}
              {pairs.length === 0 && <tr><td colSpan={5} className="empty">{t("buddy.noPairs")}</td></tr>}
            </tbody>
          </table>
          <h3 style={{ marginBottom: "var(--space-3)" }}>{t("buddy.feedbackTitle")}</h3>
          <table className="data-table">
            <thead><tr><th>{t("buddy.pairId")}</th><th>{t("common.type")}</th><th>{t("buddy.reason")}</th><th>{t("buddy.postedAt")}</th></tr></thead>
            <tbody>
              {feedbacks.map(f => (
                <tr key={f.id}>
                  <td>{f.pair_id}</td>
                  <td><span className={`badge badge-${f.feedback_type === "Good" ? "won" : "lost"}`}>{f.feedback_type}</span></td>
                  <td>{f.reason || "-"}</td><td>{new Date(f.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
              {feedbacks.length === 0 && <tr><td colSpan={4} className="empty">{t("buddy.noFeedbacks")}</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </PageLayout>
  );
}
