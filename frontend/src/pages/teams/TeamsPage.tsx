/**
 * チーム管理ページ。
 * チームのCRUD＋メンバー管理。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

interface Team {
  id: number;
  name: string;
  leader_id: number | null;
  description: string | null;
  is_active: boolean;
  member_count: number | null;
  created_at: string;
  updated_at: string;
}

interface TeamMember {
  user_id: number;
  username: string | null;
  email: string | null;
  joined_at: string;
}

const emptyForm = { name: "", leader_id: "", description: "" };

export default function TeamsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [teams, setTeams] = useState<Team[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Team | null>(null);
  const [membersPanel, setMembersPanel] = useState<Team | null>(null);
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [newMemberId, setNewMemberId] = useState("");

  const loadTeams = async () => {
    try {
      const data = await api.get<Team[]>("/teams");
      setTeams(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  const loadMembers = async (teamId: number) => {
    try {
      const data = await api.get<TeamMember[]>(`/teams/${teamId}/members`);
      setMembers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  useEffect(() => { loadTeams(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const payload = {
      name: form.name,
      leader_id: form.leader_id ? Number(form.leader_id) : null,
      description: form.description || null,
    };
    try {
      if (editId) {
        await api.patch(`/teams/${editId}`, payload);
      } else {
        await api.post("/teams", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadTeams();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    }
  };

  const handleEdit = (t: Team) => {
    setEditId(t.id);
    setForm({
      name: t.name,
      leader_id: t.leader_id != null ? String(t.leader_id) : "",
      description: t.description || "",
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/teams/${id}`);
      loadTeams();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  const openMembers = async (team: Team) => {
    setMembersPanel(team);
    await loadMembers(team.id);
  };

  const addMember = async (e: FormEvent) => {
    e.preventDefault();
    if (!membersPanel) return;
    try {
      await api.post(`/teams/${membersPanel.id}/members`, { user_id: Number(newMemberId) });
      setNewMemberId("");
      loadMembers(membersPanel.id);
      loadTeams();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  const removeMember = async (userId: number) => {
    if (!membersPanel) return;
    try {
      await api.delete(`/teams/${membersPanel.id}/members/${userId}`);
      loadMembers(membersPanel.id);
      loadTeams();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  return (
    <PageLayout
      navKey="nav.teams"
      headerAction={hasPermission("teams.create") ? (
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>{t("teams.newTeam")}</button>
      ) : undefined}
    >
      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("teams.editTeam") : t("teams.newTeam")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("teams.teamName")} *</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("teams.leaderUserIdLabel")}</label>
                <input type="number" min="1" value={form.leader_id} onChange={(e) => setForm({ ...form, leader_id: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("common.description")}</label>
                <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{editId ? t("common.update") : t("common.create")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {membersPanel && (
        <div className="modal-overlay" onClick={() => setMembersPanel(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("teams.manageMembersTitle", { name: membersPanel.name })}</h3>
            {hasPermission("teams.manage_members") && (
              <form onSubmit={addMember} style={{ marginBottom: "var(--space-4)" }}>
                <div className="form-group"><label>{t("teams.addUserIdLabel")}</label>
                  <input type="number" min="1" required value={newMemberId} onChange={(e) => setNewMemberId(e.target.value)} />
                </div>
                <button type="submit" className="btn-primary">{t("common.add")}</button>
              </form>
            )}
            <table className="data-table">
              <thead><tr><th>{t("teams.colUsername")}</th><th>{t("common.email")}</th><th>{t("teams.colJoinedAt")}</th><th>{t("common.actions")}</th></tr></thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.user_id}>
                    <td>{m.username || "-"}</td>
                    <td>{m.email || "-"}</td>
                    <td>{new Date(m.joined_at).toLocaleDateString()}</td>
                    <td>
                      {hasPermission("teams.manage_members") && (
                        <button className="btn-sm btn-danger" onClick={() => removeMember(m.user_id)}>{t("common.remove")}</button>
                      )}
                    </td>
                  </tr>
                ))}
                {members.length === 0 && <tr><td colSpan={4} className="empty">{t("teams.noMembers")}</td></tr>}
              </tbody>
            </table>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setMembersPanel(null)}>{t("common.close")}</button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>{t("teams.teamName")}</th><th>{t("common.description")}</th><th>{t("teams.colMemberCount")}</th><th>{t("teams.colLeaderId")}</th><th>{t("common.actions")}</th></tr>
          </thead>
          <tbody>
            {teams.map((team) => (
              <tr key={team.id}>
                <td>{team.name}</td>
                <td>{team.description || "-"}</td>
                <td>{team.member_count ?? 0}</td>
                <td>{team.leader_id ?? "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => openMembers(team)}>{t("teams.membersBtn")}</button>
                  {hasPermission("teams.update") && <button className="btn-sm" onClick={() => handleEdit(team)}>{t("common.edit")}</button>}
                  {hasPermission("teams.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(team)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {teams.length === 0 && <tr><td colSpan={5} className="empty">{t("teams.noTeams")}</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("teams.deleteTeam")}
        message={<><strong>{deleteTarget?.name}</strong>{t("common.deleteConfirmSuffix")}<br />{t("teams.memberDeleteNote")}</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </PageLayout>
  );
}
