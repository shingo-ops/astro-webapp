/**
 * ロール・権限管理ページ（Discord式カスタムロール / GAS UI互換 split-view版）。
 *
 * レイアウト:
 *   - 左サイドバー: 役割一覧（クリックで選択）+ 「新規ロール」「ユーザー割当」ボタン
 *   - 右メインペイン: 選択中ロールの権限編集
 *     - カテゴリ単位でグループ化（アイコン + カテゴリ名 + メニュー表示トグル）
 *     - 各カテゴリ内に個別権限のチェックボックス
 *     - 未保存時は下部に警告バナー + 上部のキャンセル/保存ボタン有効化
 *
 * 変更履歴:
 *   2026-04-16: 初版（GAS UI互換に刷新、モーダル式→split-view式）
 */

import { useEffect, useMemo, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
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

// カテゴリ表示順とアイコン（絵文字使用、追加依存なし）
const CATEGORY_META: Record<string, { icon: string; order: number }> = {
  "レポート": { icon: "📊", order: 1 },
  "顧客": { icon: "👤", order: 2 },
  "リード": { icon: "🎯", order: 3 },
  "案件": { icon: "💼", order: 4 },
  "注文": { icon: "📦", order: 5 },
  "チーム": { icon: "👥", order: 6 },
  "ロール": { icon: "🔑", order: 7 },
  "システム": { icon: "⚙️", order: 99 },
};

// 各カテゴリの「メニュー表示」に対応する view系権限キー
// トグルONで .view を付与、OFFで .view を外す
const MENU_VIEW_KEY: Record<string, string[]> = {
  "顧客": ["customers.view"],
  "リード": ["leads.view"],
  "案件": ["deals.view"],
  "注文": ["orders.view"],
  "チーム": ["teams.view"],
  "ロール": ["roles.view"],
  "レポート": ["dashboard.view", "reports.view"],
  "システム": ["system.audit_view"],
};

// ロール表示色の選択肢（12色、視覚的に明確に区別できるよう Tailwind 500系で統一）
// 正方形スウォッチで表示、ラジオボタン選択
const COLOR_PALETTE = [
  "#ef4444", // 赤
  "#f97316", // オレンジ
  "#eab308", // 黄
  "#84cc16", // ライム
  "#22c55e", // 緑
  "#14b8a6", // ティール
  "#06b6d4", // シアン
  "#3b82f6", // 青
  "#6366f1", // インディゴ
  "#a855f7", // 紫
  "#ec4899", // ピンク
  "#64748b", // スレート
];

// 優先順位は旧GAS版に合わせて第1-第4順位の4段階。priority数値とのマッピング。
const PRIORITY_OPTIONS = [
  { value: 1000, label: "第1順位（最上位）" },
  { value: 900, label: "第2順位" },
  { value: 500, label: "第3順位" },
  { value: 300, label: "第4順位" },
];

const emptyRoleForm = { name: "", color: COLOR_PALETTE[0], priority: 500, description: "" };

export default function RolesPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();

  // データ
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 選択中ロール
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  // 元の権限状態（保存の差分検出用）
  const [originalPermIds, setOriginalPermIds] = useState<Set<number>>(new Set());
  // 編集中の権限状態
  const [editedPermIds, setEditedPermIds] = useState<Set<number>>(new Set());
  const [savingPerms, setSavingPerms] = useState(false);

  // ロールCRUD用モーダル
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [editingRoleId, setEditingRoleId] = useState<number | null>(null);
  const [roleForm, setRoleForm] = useState(emptyRoleForm);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);

  // ユーザー割当モーダル
  const [userAssignOpen, setUserAssignOpen] = useState(false);
  const [targetUserId, setTargetUserId] = useState("");
  const [selectedRoleIds, setSelectedRoleIds] = useState<Set<number>>(new Set());

  // 初回ロード
  useEffect(() => {
    Promise.all([
      api.get<Role[]>("/roles"),
      api.get<Permission[]>("/permissions"),
    ])
      .then(([r, p]) => {
        setRoles(r);
        setPermissions(p);
        if (r.length > 0) setSelectedRoleId(r[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : t("common.fetchError")))
      .finally(() => setLoading(false));
  }, []);

  // 選択ロール変更時、権限を読み込む
  useEffect(() => {
    if (selectedRoleId == null) return;
    api.get<Permission[]>(`/roles/${selectedRoleId}/permissions`)
      .then((perms) => {
        const ids = new Set(perms.map((p) => p.id));
        setOriginalPermIds(ids);
        setEditedPermIds(new Set(ids));
      })
      .catch((e) => setError(e instanceof Error ? e.message : t("common.fetchError")));
  }, [selectedRoleId]);

  // カテゴリ別に権限をグループ化
  const grouped = useMemo(() => {
    const map = new Map<string, Permission[]>();
    for (const p of permissions) {
      if (!map.has(p.category)) map.set(p.category, []);
      map.get(p.category)!.push(p);
    }
    return Array.from(map.entries()).sort(
      ([a], [b]) => (CATEGORY_META[a]?.order ?? 100) - (CATEGORY_META[b]?.order ?? 100),
    );
  }, [permissions]);

  const selectedRole = roles.find((r) => r.id === selectedRoleId) ?? null;
  const isSystemRole = selectedRole?.is_system ?? false;
  const dirty = useMemo(() => {
    if (originalPermIds.size !== editedPermIds.size) return true;
    for (const id of editedPermIds) if (!originalPermIds.has(id)) return true;
    return false;
  }, [originalPermIds, editedPermIds]);

  const canEditPerms = hasPermission("roles.update") && !isSystemRole;

  // 個別権限のトグル
  const togglePerm = (id: number) => {
    if (!canEditPerms) return;
    const next = new Set(editedPermIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setEditedPermIds(next);
  };

  // カテゴリ一括トグル（そのカテゴリの全権限を一斉ON/OFF）
  const toggleCategory = (category: string, on: boolean) => {
    if (!canEditPerms) return;
    const catPerms = permissions.filter((p) => p.category === category);
    const next = new Set(editedPermIds);
    for (const p of catPerms) {
      if (on) next.add(p.id);
      else next.delete(p.id);
    }
    setEditedPermIds(next);
  };

  // 「メニュー表示」専用トグル（.view 系のみON/OFF）
  const toggleMenuVisibility = (category: string, on: boolean) => {
    if (!canEditPerms) return;
    const keys = MENU_VIEW_KEY[category];
    if (!keys) return;
    const targetPerms = permissions.filter((p) => keys.includes(p.key));
    const next = new Set(editedPermIds);
    for (const p of targetPerms) {
      if (on) next.add(p.id);
      else next.delete(p.id);
    }
    setEditedPermIds(next);
  };

  const isCategoryMenuVisible = (category: string): boolean => {
    const keys = MENU_VIEW_KEY[category];
    if (!keys) return true;
    const targetPerms = permissions.filter((p) => keys.includes(p.key));
    if (targetPerms.length === 0) return true;
    return targetPerms.every((p) => editedPermIds.has(p.id));
  };

  // 保存
  const savePermissions = async () => {
    if (selectedRoleId == null) return;
    setSavingPerms(true);
    try {
      await api.put(`/roles/${selectedRoleId}/permissions`, {
        permission_ids: Array.from(editedPermIds),
      });
      setOriginalPermIds(new Set(editedPermIds));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSavingPerms(false);
    }
  };

  // 編集キャンセル（元に戻す）
  const cancelEdits = () => setEditedPermIds(new Set(originalPermIds));

  // ロール選択切替（未保存なら確認）
  const selectRole = (id: number) => {
    if (dirty && !window.confirm(t("roles.unsavedChanges") + "破棄して切り替えますか？")) return;
    setSelectedRoleId(id);
  };

  // ロール作成/編集
  const openCreateRole = () => {
    setEditingRoleId(null);
    setRoleForm(emptyRoleForm);
    setShowRoleForm(true);
  };
  const openEditRole = (r: Role) => {
    setEditingRoleId(r.id);
    setRoleForm({
      name: r.name,
      color: r.color || "#6c757d",
      priority: r.priority,
      description: r.description || "",
    });
    setShowRoleForm(true);
  };
  const submitRoleForm = async (e: FormEvent) => {
    e.preventDefault();
    const payload = {
      name: roleForm.name,
      color: roleForm.color,
      priority: Number(roleForm.priority),
      description: roleForm.description || null,
    };
    try {
      if (editingRoleId) {
        await api.patch(`/roles/${editingRoleId}`, payload);
      } else {
        await api.post("/roles", payload);
      }
      const latest = await api.get<Role[]>("/roles");
      setRoles(latest);
      setShowRoleForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    }
  };
  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/roles/${id}`);
      const latest = await api.get<Role[]>("/roles");
      setRoles(latest);
      if (selectedRoleId === id && latest.length > 0) setSelectedRoleId(latest[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.deleteError"));
    }
  };

  // ユーザー割当
  const toggleUserRole = (id: number) => {
    const next = new Set(selectedRoleIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedRoleIds(next);
  };
  const saveUserRoles = async () => {
    try {
      await api.put(`/users/${targetUserId}/roles`, {
        role_ids: Array.from(selectedRoleIds),
      });
      setUserAssignOpen(false);
      setTargetUserId("");
      setSelectedRoleIds(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    }
  };
  const closeUserAssign = () => {
    setUserAssignOpen(false);
    setTargetUserId("");
    setSelectedRoleIds(new Set());
  };

  if (loading) return <div className="page"><div className="loading">{t("common.loading")}</div></div>;

  return (
    <div className="page roles-page">
      {error && <div className="error-message">{error}</div>}

      <div className="roles-layout">
        {/* === 左サイドバー: 役割一覧 === */}
        <aside className="roles-sidebar">
          <div className="roles-sidebar-header">
            <h3>{t("roles.title")}</h3>
            {hasPermission("roles.create") && (
              <button className="btn-primary btn-sm" onClick={openCreateRole}>+ {t("common.new")}</button>
            )}
          </div>
          <ul className="roles-list">
            {roles.map((r) => {
              // priorityに応じた階層インデント。カード全体（カラーバー含む）を右にずらす
              // 1000→0, 700→1, 400→2, 100→3, 0→4
              const level =
                r.priority >= 1000 ? 0 :
                r.priority >= 700 ? 1 :
                r.priority >= 400 ? 2 :
                r.priority >= 100 ? 3 : 4;
              return (
                <li key={r.id} style={{ marginLeft: `${level * 16}px` }}>
                  <button
                    className={`role-item ${r.id === selectedRoleId ? "active" : ""}`}
                    style={{ borderLeft: `4px solid ${r.color || "#cbd5e0"}` }}
                    onClick={() => selectRole(r.id)}
                  >
                    <span className="role-item-name">{r.name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {hasPermission("roles.assign") && (
            <button className="btn-secondary btn-block" onClick={() => setUserAssignOpen(true)}>
              {t("roles.assignUsers")}
            </button>
          )}
        </aside>

        {/* === 右メインペイン: 権限編集 === */}
        <main className="roles-main">
          {selectedRole ? (
            <>
              <div className="roles-main-header">
                <div>
                  <h2>
                    <span
                      className="badge"
                      style={{ background: selectedRole.color || "var(--bg-hover)", color: "var(--on-accent)", marginRight: 8 }}
                    >
                      {selectedRole.name}
                    </span>
                    <span style={{ fontWeight: 400, color: "var(--text-secondary)" }}>の権限</span>
                  </h2>
                  {selectedRole.description && (
                    <p className="role-description">{selectedRole.description}</p>
                  )}
                  {isSystemRole && (
                    <p className="role-note">※ {t("roles.systemRole")}（権限編集は {hasPermission("roles.update") ? "不可" : "権限不足"}）</p>
                  )}
                </div>
                <div className="roles-main-actions">
                  {canEditPerms && !selectedRole.is_system && (
                    <>
                      <button className="btn-sm" onClick={() => openEditRole(selectedRole)}>{t("common.edit")}</button>
                      {hasPermission("roles.delete") && (
                        <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(selectedRole)}>{t("common.delete")}</button>
                      )}
                    </>
                  )}
                  <button className="btn-secondary" disabled={!dirty || savingPerms} onClick={cancelEdits}>
                    {t("roles.cancelChanges")}
                  </button>
                  <button className="btn-primary" disabled={!dirty || savingPerms || !canEditPerms} onClick={savePermissions}>
                    {savingPerms ? t("common.saving") : t("roles.saveChanges")}
                  </button>
                </div>
              </div>

              <div className="permission-groups">
                {grouped.map(([category, perms]) => {
                  const meta = CATEGORY_META[category] ?? { icon: "📁", order: 100 };
                  const menuVisible = isCategoryMenuVisible(category);
                  const allChecked = perms.every((p) => editedPermIds.has(p.id));
                  return (
                    <section key={category} className="permission-group">
                      <header className="permission-group-header">
                        <div className="permission-group-title">
                          <span className="permission-group-icon">{meta.icon}</span>
                          <span>{category}ページ権限</span>
                        </div>
                        <div className="permission-group-toggles">
                          <label className="chk-label" title="このカテゴリ全ての権限を一括操作">
                            <input
                              type="checkbox"
                              checked={allChecked}
                              disabled={!canEditPerms}
                              onChange={(e) => toggleCategory(category, e.target.checked)}
                            />
                            全選択
                          </label>
                          {MENU_VIEW_KEY[category] && (
                            <label className="chk-label" title=".view 権限をON/OFFしてサイドバー表示を切り替え">
                              <input
                                type="checkbox"
                                checked={menuVisible}
                                disabled={!canEditPerms}
                                onChange={(e) => toggleMenuVisibility(category, e.target.checked)}
                              />
                              メニュー表示
                            </label>
                          )}
                        </div>
                      </header>
                      <div className="permission-group-body">
                        {perms.map((p) => (
                          <label key={p.id} className="permission-item">
                            <input
                              type="checkbox"
                              checked={editedPermIds.has(p.id)}
                              disabled={!canEditPerms}
                              onChange={() => togglePerm(p.id)}
                            />
                            <div className="permission-item-text">
                              <div className="permission-item-desc">{p.description}</div>
                            </div>
                          </label>
                        ))}
                      </div>
                    </section>
                  );
                })}
              </div>

              {dirty && (
                <div className="unsaved-banner">
                  ⚠ {t("roles.unsavedChanges")}「{t("roles.saveChanges")}」ボタンをクリックして変更を反映してください。
                </div>
              )}
            </>
          ) : (
            <div className="empty">左から役割を選択してください</div>
          )}
        </main>
      </div>

      {/* === ロール作成/編集モーダル === */}
      {showRoleForm && (
        <div className="modal-overlay" onClick={() => setShowRoleForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editingRoleId ? t("roles.editRole") : t("roles.newRole")}</h3>
            <form onSubmit={submitRoleForm}>
              <div className="form-group"><label>{t("roles.roleName")} *</label>
                <input required value={roleForm.name} onChange={(e) => setRoleForm({ ...roleForm, name: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("roles.color")}</label>
                <div className="color-picker" role="radiogroup" aria-label={t("roles.color")}>
                  {/* 既存ロールの色がパレットに無い場合は「現在の色」として表示 */}
                  {roleForm.color && !COLOR_PALETTE.includes(roleForm.color.toLowerCase()) && !COLOR_PALETTE.includes(roleForm.color) && (
                    <label
                      className="color-swatch selected color-swatch-legacy"
                      style={{ background: roleForm.color }}
                      title={`現在の色（${roleForm.color}）`}
                    >
                      <input
                        type="radio"
                        name="role-color"
                        value={roleForm.color}
                        checked
                        readOnly
                      />
                    </label>
                  )}
                  {COLOR_PALETTE.map((c) => (
                    <label
                      key={c}
                      className={`color-swatch ${roleForm.color === c ? "selected" : ""}`}
                      style={{ background: c }}
                      title={c}
                    >
                      <input
                        type="radio"
                        name="role-color"
                        value={c}
                        checked={roleForm.color === c}
                        onChange={(e) => setRoleForm({ ...roleForm, color: e.target.value })}
                      />
                    </label>
                  ))}
                </div>
              </div>
              <div className="form-group"><label>{t("roles.priority")}</label>
                <select
                  value={roleForm.priority}
                  onChange={(e) => setRoleForm({ ...roleForm, priority: Number(e.target.value) })}
                >
                  {PRIORITY_OPTIONS.map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                  {!PRIORITY_OPTIONS.find((p) => p.value === roleForm.priority) && (
                    <option value={roleForm.priority}>カスタム (P{roleForm.priority})</option>
                  )}
                </select>
              </div>
              <div className="form-group"><label>{t("common.description")}</label>
                <textarea value={roleForm.description} onChange={(e) => setRoleForm({ ...roleForm, description: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowRoleForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{editingRoleId ? t("common.update") : t("common.create")}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* === ユーザー割当モーダル === */}
      {userAssignOpen && (
        <div className="modal-overlay" onClick={closeUserAssign}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{t("roles.assignUsers")}</h3>
            <div className="form-group"><label>対象ユーザーID *</label>
              <input type="number" min="1" required value={targetUserId} onChange={(e) => setTargetUserId(e.target.value)} />
            </div>
            <div className="form-group"><label>付与するロール</label>
              {roles.map((r) => (
                <label key={r.id} style={{ display: "block", padding: 4 }}>
                  <input type="checkbox" checked={selectedRoleIds.has(r.id)} onChange={() => toggleUserRole(r.id)} />{" "}
                  <span className="badge" style={{ background: r.color || "var(--bg-hover)", color: "var(--on-accent)" }}>{r.name}</span>
                  <small style={{ marginLeft: 8, color: "var(--text-muted)" }}>priority: {r.priority}</small>
                </label>
              ))}
            </div>
            <div className="form-actions">
              <button type="button" className="btn-secondary" onClick={closeUserAssign}>{t("common.cancel")}</button>
              <button type="button" className="btn-primary" onClick={saveUserRoles} disabled={!targetUserId}>{t("common.save")}</button>
            </div>
          </div>
        </div>
      )}

      {/* === 削除確認 === */}
      <ConfirmModal
        open={!!deleteTarget}
        title={t("roles.deleteRole")}
        message={<><strong>{deleteTarget?.name}</strong> を削除します。<br />このロールを持つユーザーは自動的に剥奪されます。</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
