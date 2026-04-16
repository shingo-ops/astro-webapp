/**
 * ロール・権限管理ページ（Discord式カスタムロール）。
 * ロールのCRUD + 権限のチェックボックス割り当て + ユーザーへのロール付与。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 */

import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";

interface Role {
  id: number;
  name: string;
  color: string | null;
  priority: number;
  is_system: boolean;
  description: string | null;
  created_at: string;
  updated_at: string;
}

interface Permission {
  id: number;
  key: string;
  resource: string;
  action: string;
  description: string;
  category: string;
}

const emptyForm = { name: "", color: "#6c757d", priority: 10, description: "" };

export default function RolesPage() {
  const { hasPermission } = usePermissions();
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);
  const [permissionsPanel, setPermissionsPanel] = useState<Role | null>(null);
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<Set<number>>(new Set());
  const [userAssignPanel, setUserAssignPanel] = useState(false);
  const [targetUserId, setTargetUserId] = useState("");
  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());

  const loadRoles = async () => {
    try {
      const data = await api.get<Role[]>("/roles");
      setRoles(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadPermissions = async () => {
    try {
      const data = await api.get<Permission[]>("/permissions");
      setPermissions(data);
    } catch {
      // 権限マスタ取得失敗は致命的ではない
    }
  };

  useEffect(() => { loadRoles(); loadPermissions(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    const payload = {
      name: form.name,
      color: form.color,
      priority: Number(form.priority),
      description: form.description || null,
    };
    try {
      if (editId) {
        await api.patch(`/roles/${editId}`, payload);
      } else {
        await api.post("/roles", payload);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadRoles();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const handleEdit = (r: Role) => {
    setEditId(r.id);
    setForm({
      name: r.name,
      color: r.color || "#6c757d",
      priority: r.priority,
      description: r.description || "",
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/roles/${id}`);
      loadRoles();
    } catch (e) {
      setError(e instanceof Error ? e.message : "削除に失敗しました");
    }
  };

  const openPermissionsPanel = async (r: Role) => {
    setPermissionsPanel(r);
    try {
      const current = await api.get<Permission[]>(`/roles/${r.id}/permissions`);
      setSelectedPermissionIds(new Set(current.map((p) => p.id)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "権限取得に失敗しました");
    }
  };

  const savePermissions = async () => {
    if (!permissionsPanel) return;
    try {
      await api.put(`/roles/${permissionsPanel.id}/permissions`, {
        permission_ids: Array.from(selectedPermissionIds),
      });
      setPermissionsPanel(null);
      setSelectedPermissionIds(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const togglePermission = (id: number) => {
    const next = new Set(selectedPermissionIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedPermissionIds(next);
  };

  const categories = Array.from(new Set(permissions.map((p) => p.category)));

  const saveUserRoles = async () => {
    try {
      await api.put(`/users/${targetUserId}/roles`, {
        role_ids: Array.from(selectedRoleIds),
      });
      setUserAssignPanel(false);
      setTargetUserId("");
      setSelectedRoleIds(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存に失敗しました");
    }
  };

  const toggleRole = (id: number) => {
    const next = new Set(selectedRoleIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedRoleIds(next);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>ロール・権限管理</h2>
        <div className="actions">
          {hasPermission("roles.assign") && (
            <button className="btn-secondary" onClick={() => setUserAssignPanel(true)}>ユーザー割当</button>
          )}
          {hasPermission("roles.create") && (
            <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>新規ロール</button>
          )}
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? "ロール編集" : "新規ロール作成"}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>ロール名 *</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group"><label>表示色</label>
                <input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} />
              </div>
              <div className="form-group"><label>優先順位 (0-999)</label>
                <input type="number" min="0" max="999" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} />
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

      {permissionsPanel && (
        <div className="modal-overlay" onClick={() => setPermissionsPanel(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 600 }}>
            <h3>権限設定 - {permissionsPanel.name}</h3>
            {categories.map((cat) => (
              <div key={cat} style={{ marginBottom: 16 }}>
                <h4 style={{ borderBottom: "1px solid #e2e8f0", paddingBottom: 4 }}>{cat}</h4>
                {permissions.filter((p) => p.category === cat).map((p) => (
                  <label key={p.id} style={{ display: "block", padding: 4 }}>
                    <input
                      type="checkbox"
                      checked={selectedPermissionIds.has(p.id)}
                      onChange={() => togglePermission(p.id)}
                    />{" "}
                    <code style={{ marginRight: 8 }}>{p.key}</code> {p.description}
                  </label>
                ))}
              </div>
            ))}
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => setPermissionsPanel(null)}>キャンセル</button>
              <button type="button" className="btn-primary" onClick={savePermissions}>保存</button>
            </div>
          </div>
        </div>
      )}

      {userAssignPanel && (
        <div className="modal-overlay" onClick={() => { setUserAssignPanel(false); setTargetUserId(""); setSelectedRoleIds(new Set()); }}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>ユーザーへのロール割当</h3>
            <div className="form-group"><label>対象ユーザーID *</label>
              <input type="number" min="1" required value={targetUserId} onChange={(e) => setTargetUserId(e.target.value)} />
            </div>
            <div className="form-group"><label>付与するロール</label>
              {roles.map((r) => (
                <label key={r.id} style={{ display: "block", padding: 4 }}>
                  <input type="checkbox" checked={selectedRoleIds.has(r.id)} onChange={() => toggleRole(r.id)} />{" "}
                  <span className="badge" style={{ background: r.color || "#e2e8f0" }}>{r.name}</span>
                  <small style={{ marginLeft: 8, color: "#718096" }}>priority: {r.priority}</small>
                </label>
              ))}
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={() => { setUserAssignPanel(false); setTargetUserId(""); setSelectedRoleIds(new Set()); }}>キャンセル</button>
              <button type="button" className="btn-primary" onClick={saveUserRoles} disabled={!targetUserId}>保存</button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>ロール名</th><th>優先順位</th><th>タイプ</th><th>説明</th><th>操作</th></tr>
          </thead>
          <tbody>
            {roles.map((r) => (
              <tr key={r.id}>
                <td>
                  <span className="badge" style={{ background: r.color || "#e2e8f0", color: "#fff" }}>{r.name}</span>
                </td>
                <td>{r.priority}</td>
                <td>{r.is_system ? "システム" : "カスタム"}</td>
                <td>{r.description || "-"}</td>
                <td className="actions">
                  {hasPermission("roles.update") && !r.is_system && (
                    <button className="btn-sm" onClick={() => openPermissionsPanel(r)}>権限設定</button>
                  )}
                  {hasPermission("roles.update") && !r.is_system && (
                    <button className="btn-sm" onClick={() => handleEdit(r)}>編集</button>
                  )}
                  {hasPermission("roles.delete") && !r.is_system && (
                    <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(r)}>削除</button>
                  )}
                </td>
              </tr>
            ))}
            {roles.length === 0 && <tr><td colSpan={5} className="empty">ロールがありません</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title="ロールを削除"
        message={<><strong>{deleteTarget?.name}</strong> を削除します。<br />このロールを持つユーザーは自動的に剥奪されます。</>}
        confirmLabel="削除する"
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
