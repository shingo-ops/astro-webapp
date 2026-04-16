/**
 * チーム管理ページ。
 * チームのCRUD＋メンバー管理。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

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
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadMembers = async (teamId: number) => {
    try {
      const data = await api.get<TeamMember[]>(`/teams/${teamId}/members`);
      setMembers(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "メンバー取得に失敗しました");
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
      setError(e instanceof Error ? e.message : "保存に失敗しました");
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
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const openMembers = async (t: Team) => {
    setMembersPanel(t);
    await loadMembers(t.id);
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
      setError(e instanceof Error ? e.message : "メンバー追加に失敗しました");
    }
  };

  const removeMember = async (userId: number) => {
    if (!membersPanel) return;
    try {
      await api.delete(`/teams/${membersPanel.id}/members/${userId}`);
      loadMembers(membersPanel.id);
      loadTeams();
    } catch (e) {
      setError(e instanceof Error ? e.message : "メンバー削除に失敗しました");
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>チーム管理</h2>
        {hasPermission("teams.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>新規作成</button>
        )}
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "チーム編集" : "新規チーム作成"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>チーム名 *</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group"><label>リーダーユーザーID（任意）</label>
                <input type="number" min="1" value={form.leader_id} onChange={(e) => setForm({ ...form, leader_id: e.target.value })} />
              </div>
              <div className="form-group"><label>説明</label>
                <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">{editId ? "更新" : "作成"}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {membersPanel && (
        <div className="modal-overlay" onClick={() => setMembersPanel(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>メンバー管理 - {membersPanel.name}</h3>
            {hasPermission("teams.manage_members") && (
              <form onSubmit={addMember} style={{ marginBottom: 16 }}>
                <div className="form-group"><label>追加するユーザーID</label>
                  <input type="number" min="1" required value={newMemberId} onChange={(e) => setNewMemberId(e.target.value)} />
                </div>
                <button type="submit" className="btn-primary">追加</button>
              </form>
            )}
            <table className="data-table">
              <thead><tr><th>ユーザー名</th><th>メール</th><th>加入日</th><th>操作</th></tr></thead>
              <tbody>
                {members.map((m) => (
                  <tr key={m.user_id}>
                    <td>{m.username || "-"}</td>
                    <td>{m.email || "-"}</td>
                    <td>{new Date(m.joined_at).toLocaleDateString()}</td>
                    <td>
                      {hasPermission("teams.manage_members") && (
                        <button className="btn-sm btn-danger" onClick={() => removeMember(m.user_id)}>削除</button>
                      )}
                    </td>
                  </tr>
                ))}
                {members.length === 0 && <tr><td colSpan={4} className="empty">メンバーがいません</td></tr>}
              </tbody>
            </table>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setMembersPanel(null)}>閉じる</button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>チーム名</th><th>説明</th><th>メンバー数</th><th>リーダーID</th><th>操作</th></tr>
          </thead>
          <tbody>
            {teams.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{t.description || "-"}</td>
                <td>{t.member_count ?? 0}</td>
                <td>{t.leader_id ?? "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => openMembers(t)}>メンバー</button>
                  {hasPermission("teams.update") && <button className="btn-sm" onClick={() => handleEdit(t)}>編集</button>}
                  {hasPermission("teams.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(t)}>削除</button>}
                </td>
              </tr>
            ))}
            {teams.length === 0 && <tr><td colSpan={5} className="empty">チームが作成されていません</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="チームを削除"
        message={<><strong>{deleteTarget?.name}</strong> を削除します。<br />メンバー情報も同時に削除されます。</>}
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
