/**
 * スタッフ管理ページ。Phase 1 再設計版。
 *
 * staff テーブル + staff_emails + staff_ui_preferences の CRUD。
 * UI設定はネストでまとめて編集可能。
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import ConfirmModal from "../components/ConfirmModal";
import { usePermissions } from "../hooks/usePermissions";
import { useUiPrefs } from "../contexts/UiPrefsContext";

interface StaffUIPreferences {
  dark_mode: boolean;
  show_chat_menu: boolean;
  show_sales_menu: boolean;
  show_settings_menu: boolean;
  show_admin_menu: boolean;
  show_buddy_menu: boolean;
  show_sidebar: boolean;
}

interface Staff {
  id: number;
  tenant_id: number;
  user_id: number | null;
  staff_code: string;
  surname_jp: string;
  given_name_jp: string;
  surname_kana: string | null;
  given_name_kana: string | null;
  surname_en: string | null;
  given_name_en: string | null;
  primary_email: string;
  discord_user_id: string | null;
  role_id: number;
  role_name: string | null;
  status: string;
  firebase_uid: string | null;
  emails: string[];
  ui_preferences: StaffUIPreferences | null;
  created_at: string;
  updated_at: string;
}

interface Role {
  id: number;
  name: string;
}

const emptyPrefs: StaffUIPreferences = {
  dark_mode: false,
  show_chat_menu: true,
  show_sales_menu: true,
  show_settings_menu: true,
  show_admin_menu: false,
  show_buddy_menu: true,
  show_sidebar: true,
};

type FormState = {
  staff_code: string;
  surname_jp: string;
  given_name_jp: string;
  surname_kana: string;
  given_name_kana: string;
  surname_en: string;
  given_name_en: string;
  primary_email: string;
  discord_user_id: string;
  role_id: string;
  status: string;
  firebase_uid: string;
  ui_preferences: StaffUIPreferences;
};

const emptyForm: FormState = {
  staff_code: "", surname_jp: "", given_name_jp: "",
  surname_kana: "", given_name_kana: "", surname_en: "", given_name_en: "",
  primary_email: "", discord_user_id: "", role_id: "", status: "active",
  firebase_uid: "", ui_preferences: { ...emptyPrefs },
};

export default function StaffPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const { refresh: refreshUiPrefs, selfStaffId } = useUiPrefs();
  const [staff, setStaff] = useState<Staff[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Staff | null>(null);

  const loadAll = async () => {
    try {
      const [s, r] = await Promise.all([
        api.get<Staff[]>("/staff"),
        api.get<Role[]>("/roles"),
      ]);
      setStaff(s);
      setRoles(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { loadAll(); }, []);

  const toNull = (v: string) => (v ? v : null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (submitting) return;
    setSubmitting(true);
    const payload: Record<string, unknown> = {
      surname_jp: form.surname_jp,
      given_name_jp: form.given_name_jp,
      surname_kana: toNull(form.surname_kana),
      given_name_kana: toNull(form.given_name_kana),
      surname_en: toNull(form.surname_en),
      given_name_en: toNull(form.given_name_en),
      primary_email: form.primary_email,
      discord_user_id: toNull(form.discord_user_id),
      role_id: parseInt(form.role_id, 10),
      status: form.status,
      firebase_uid: toNull(form.firebase_uid),
      ui_preferences: form.ui_preferences,
    };
    if (!editId && form.staff_code.trim()) {
      payload.staff_code = form.staff_code.trim();
    }
    try {
      if (editId) await api.patch(`/staff/${editId}`, payload);
      else await api.post("/staff", payload);
      // PR #166 F4: 自分の staff レコードを編集した時のみ UI prefs を refresh する。
      // 他人を編集したケースでの不要な /staff/me 呼び出しを抑制し、かつ
      // loadAll() と refreshUiPrefs() をシーケンシャル await にしてレースを防ぐ。
      const editedSelf = editId !== null && selfStaffId !== null && editId === selfStaffId;
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      await loadAll();
      if (editedSelf) {
        await refreshUiPrefs();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = (s: Staff) => {
    setEditId(s.id);
    setForm({
      staff_code: s.staff_code,
      surname_jp: s.surname_jp,
      given_name_jp: s.given_name_jp,
      surname_kana: s.surname_kana || "",
      given_name_kana: s.given_name_kana || "",
      surname_en: s.surname_en || "",
      given_name_en: s.given_name_en || "",
      primary_email: s.primary_email,
      discord_user_id: s.discord_user_id || "",
      role_id: String(s.role_id),
      status: s.status,
      firebase_uid: s.firebase_uid || "",
      ui_preferences: s.ui_preferences || { ...emptyPrefs },
    });
    setShowForm(true);
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/staff/${id}`);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("staff.title")}</h2>
        {hasPermission("staff.create") && (
          <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>
            {t("staff.newStaff")}
          </button>
        )}
      </div>

      {error && <div className="error-message">{error}</div>}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("staff.editStaff") : t("staff.newStaff")}</h3>
            <form onSubmit={handleSubmit}>
              {!editId && (
                <div className="form-group">
                  <label>{t("staff.staffCode")}（空欄なら自動採番 EMP-00001 形式）</label>
                  <input value={form.staff_code} placeholder="例: EMP-00001" onChange={(e) => setForm({ ...form, staff_code: e.target.value })} />
                </div>
              )}
              <div className="form-group"><label>{t("staff.surnameJp")} *</label>
                <input required value={form.surname_jp} onChange={(e) => setForm({ ...form, surname_jp: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("staff.givenNameJp")} *</label>
                <input required value={form.given_name_jp} onChange={(e) => setForm({ ...form, given_name_jp: e.target.value })} />
              </div>
              <div className="form-group"><label>苗字ふりがな</label>
                <input value={form.surname_kana} onChange={(e) => setForm({ ...form, surname_kana: e.target.value })} />
              </div>
              <div className="form-group"><label>名前ふりがな</label>
                <input value={form.given_name_kana} onChange={(e) => setForm({ ...form, given_name_kana: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("staff.surnameEn")}</label>
                <input value={form.surname_en} onChange={(e) => setForm({ ...form, surname_en: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("staff.givenNameEn")}</label>
                <input value={form.given_name_en} onChange={(e) => setForm({ ...form, given_name_en: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("staff.primaryEmail")} *</label>
                <input required type="email" value={form.primary_email} onChange={(e) => setForm({ ...form, primary_email: e.target.value })} />
              </div>
              <div className="form-group"><label>Discord ID</label>
                <input value={form.discord_user_id} onChange={(e) => setForm({ ...form, discord_user_id: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("staff.role")} *</label>
                <select required value={form.role_id} onChange={(e) => setForm({ ...form, role_id: e.target.value })}>
                  <option value="">選択してください</option>
                  {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                </select>
              </div>
              <div className="form-group"><label>{t("staff.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">{t("staff.status_active")}</option>
                  <option value="inactive">{t("staff.status_inactive")}</option>
                  <option value="pending">保留</option>
                </select>
              </div>
              <h4>{t("staff.uiPreferences")}</h4>
              {(() => {
                // Record<keyof StaffUIPreferences, string> で網羅性を型保証。
                // StaffUIPreferences にフィールド追加した時にコンパイル時エラーで検知できる。
                const labels: Record<keyof StaffUIPreferences, string> = {
                  dark_mode: t("staff.darkMode"),
                  show_chat_menu: t("staff.showChatMenu"),
                  show_sales_menu: t("staff.showSalesMenu"),
                  show_settings_menu: t("staff.showSettingsMenu"),
                  show_admin_menu: t("staff.showAdminMenu"),
                  show_buddy_menu: t("staff.showBuddyMenu"),
                  show_sidebar: t("staff.showSidebar"),
                };
                return (Object.entries(labels) as Array<[keyof StaffUIPreferences, string]>).map(([k, label]) => (
                  <div className="form-group" key={k}>
                    <label>
                      <input type="checkbox" checked={form.ui_preferences[k]} onChange={(e) => setForm({ ...form, ui_preferences: { ...form.ui_preferences, [k]: e.target.checked } })} />
                      {" "}{label}
                    </label>
                  </div>
                ));
              })()}
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)} disabled={submitting}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? "送信中..." : editId ? t("common.update") : t("common.register")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.code")}</th>
              <th>氏名</th>
              <th>{t("common.email")}</th>
              <th>{t("staff.role")}</th>
              <th>{t("staff.status")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {staff.map((s) => (
              <tr key={s.id}>
                <td className="mono">{s.staff_code}</td>
                <td>{s.surname_jp} {s.given_name_jp}</td>
                <td>
                  {s.primary_email}
                  {s.emails.length > 0 && <span style={{ fontSize: "0.8em", color: "#888" }}> (+{s.emails.length})</span>}
                </td>
                <td>{s.role_name || "-"}</td>
                <td><span className={`badge badge-${s.status === "active" ? "won" : "lost"}`}>{s.status === "active" ? t("staff.status_active") : s.status === "inactive" ? t("staff.status_inactive") : s.status}</span></td>
                <td className="actions">
                  {hasPermission("staff.update") && <button className="btn-sm" onClick={() => handleEdit(s)}>{t("common.edit")}</button>}
                  {hasPermission("staff.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(s)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {staff.length === 0 && <tr><td colSpan={6} className="empty">{t("staff.noStaff")}</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("staff.deleteStaff")}
        message={<><strong>{deleteTarget?.surname_jp} {deleteTarget?.given_name_jp}</strong> を削除します。<br />この操作は取り消せません。</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
