/**
 * Bot 管理ページ。Phase 1 再設計版。
 *
 * bots テーブルの CRUD。API キーは作成/再発行時のみ平文表示。
 */

import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import ConfirmModal from "../../components/ConfirmModal";
import { usePermissions } from "../../hooks/usePermissions";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import { PageLayout } from "../../components/PageLayout";

interface Bot {
  id: number;
  tenant_id: number;
  bot_code: string;
  display_name: string;
  purpose: string;
  status: string;
  discord_user_id: string | null;
  sender_email: string | null;
  owner_staff_id: number;
  owner_staff_name: string | null;
  last_executed_at: string | null;
  execution_count: number;
  created_at: string;
  updated_at: string;
}

interface BotCreated extends Bot {
  api_key: string;
}

interface Staff {
  id: number;
  staff_code: string;
  surname_jp: string;
  given_name_jp: string;
}

type FormState = {
  bot_code: string;
  display_name: string;
  purpose: string;
  status: string;
  discord_user_id: string;
  sender_email: string;
  owner_staff_id: string;
};

const emptyForm: FormState = {
  bot_code: "", display_name: "", purpose: "invoice", status: "active",
  discord_user_id: "", sender_email: "", owner_staff_id: "",
};


export default function BotsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [bots, setBots] = useState<Bot[]>([]);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Bot | null>(null);
  const [rotateTarget, setRotateTarget] = useState<Bot | null>(null);
  const [newApiKey, setNewApiKey] = useState<string | null>(null);

  const purposeLabel = (p: string) => (({ invoice: t("bots.purposeInvoice"), shipment: t("bots.purposeShipment"), notification: t("bots.purposeNotification"), custom: t("bots.purposeCustom") } as Record<string, string>)[p] ?? p);
  const statusLabel  = (s: string) => (({ active: t("bots.statusActive"), inactive: t("bots.statusInactive"), maintenance: t("bots.statusMaintenance") } as Record<string, string>)[s] ?? s);

  const loadAll = async () => {
    try {
      const [b, s] = await Promise.all([
        api.get<Bot[]>("/bots"),
        api.get<Staff[]>("/staff"),
      ]);
      setBots(b);
      setStaff(s);
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
    if (submitting) return;
    setSubmitting(true);
    setError("");
    const payload: Record<string, unknown> = {
      display_name: form.display_name,
      purpose: form.purpose,
      status: form.status,
      discord_user_id: toNull(form.discord_user_id),
      sender_email: toNull(form.sender_email),
      owner_staff_id: parseInt(form.owner_staff_id, 10),
    };
    if (!editId && form.bot_code.trim()) payload.bot_code = form.bot_code.trim();
    try {
      if (editId) {
        await api.patch<Bot>(`/bots/${editId}`, payload);
      } else {
        const created = await api.post<BotCreated>("/bots", payload);
        setNewApiKey(created.api_key);
      }
      setShowForm(false);
      setEditId(null);
      setForm(emptyForm);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = (b: Bot) => {
    setEditId(b.id);
    setForm({
      bot_code: b.bot_code,
      display_name: b.display_name,
      purpose: b.purpose,
      status: b.status,
      discord_user_id: b.discord_user_id || "",
      sender_email: b.sender_email || "",
      owner_staff_id: String(b.owner_staff_id),
    });
    setShowForm(true);
  };

  const performRotate = async () => {
    if (!rotateTarget) return;
    const b = rotateTarget;
    setRotateTarget(null);
    try {
      const res = await api.post<BotCreated>(`/bots/${b.id}/rotate-key`, {});
      setNewApiKey(res.api_key);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.operationError"));
    }
  };

  const performDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    setDeleteTarget(null);
    try {
      await api.delete(`/bots/${id}`);
      loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.deleteError"));
    }
  };

  return (
    <PageLayout
      navKey="nav.bots"
      headerAction={hasPermission("bots.create") ? (
        <button className="btn-primary" onClick={() => { setShowForm(true); setEditId(null); setForm(emptyForm); }}>
          {t("bots.newBot")}
        </button>
      ) : undefined}
    >
      {error && <div className="error-message">{error}</div>}

      {newApiKey && (
        <div className="notice" style={{ padding: "var(--space-4)", background: "var(--warning-bg)", border: "1px solid var(--warning-text)", borderRadius: "var(--radius-sm)", margin: "16px 0" }}>
          <strong><STATUS_ICONS.warning size={ICON.sm} aria-hidden="true" /> {t("bots.apiKeyIssued")}</strong>
          <div className="mono" style={{ padding: "var(--space-2)", background: "var(--bg-surface)", marginTop: "var(--space-2)", wordBreak: "break-all" }}>{newApiKey}</div>
          <button className="btn-sm" onClick={() => setNewApiKey(null)} style={{ marginTop: "var(--space-2)" }}>{t("bots.apiKeyConfirm")}</button>
        </div>
      )}

      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>{editId ? t("bots.editBot") : t("bots.newBot")}</h3>
            <form onSubmit={handleSubmit}>
              {!editId && (
                <div className="form-group">
                  <label>{t("bots.botCodeLabel")}</label>
                  <input value={form.bot_code} placeholder={t("bots.botCodePlaceholder")} onChange={(e) => setForm({ ...form, bot_code: e.target.value })} />
                </div>
              )}
              <div className="form-group"><label>{t("bots.displayName")} *</label>
                <input required value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("bots.purposeLabel")} *</label>
                <select required value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })}>
                  <option value="invoice">{t("bots.purposeInvoice")}</option>
                  <option value="shipment">{t("bots.purposeShipment")}</option>
                  <option value="notification">{t("bots.purposeNotification")}</option>
                  <option value="custom">{t("bots.purposeCustom")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("common.status")}</label>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="active">{t("bots.statusActive")}</option>
                  <option value="inactive">{t("bots.statusInactive")}</option>
                  <option value="maintenance">{t("bots.statusMaintenance")}</option>
                </select>
              </div>
              <div className="form-group"><label>{t("bots.ownerStaff")} *</label>
                <select required value={form.owner_staff_id} onChange={(e) => setForm({ ...form, owner_staff_id: e.target.value })}>
                  <option value="">{t("common.pleaseSelect")}</option>
                  {staff.map((s) => <option key={s.id} value={s.id}>{s.staff_code} {s.surname_jp} {s.given_name_jp}</option>)}
                </select>
              </div>
              <div className="form-group"><label>Discord Bot ID</label>
                <input value={form.discord_user_id} onChange={(e) => setForm({ ...form, discord_user_id: e.target.value })} />
              </div>
              <div className="form-group"><label>{t("bots.senderEmail")}</label>
                <input type="email" value={form.sender_email} onChange={(e) => setForm({ ...form, sender_email: e.target.value })} />
              </div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)} disabled={submitting}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary" disabled={submitting}>
                  {submitting ? t("common.submitting") : editId ? t("common.update") : t("bots.registerIssueKey")}
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
              <th>{t("common.name")}</th>
              <th>{t("bots.purposeLabel")}</th>
              <th>{t("common.status")}</th>
              <th>{t("bots.ownerStaff")}</th>
              <th>{t("bots.executionCount")}</th>
              <th>{t("bots.lastExecuted")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {bots.map((b) => (
              <tr key={b.id}>
                <td className="mono">{b.bot_code}</td>
                <td>{b.display_name}</td>
                <td>{purposeLabel(b.purpose)}</td>
                <td><span className={`badge badge-${b.status === "active" ? "won" : "lost"}`}>{statusLabel(b.status)}</span></td>
                <td>{b.owner_staff_name || "-"}</td>
                <td>{b.execution_count.toLocaleString("ja-JP")}</td>
                <td>{b.last_executed_at ? new Date(b.last_executed_at).toLocaleDateString("ja-JP") : "-"}</td>
                <td className="actions">
                  {hasPermission("bots.update") && <button className="btn-sm" onClick={() => handleEdit(b)}>{t("common.edit")}</button>}
                  {hasPermission("bots.update") && <button className="btn-sm" onClick={() => setRotateTarget(b)}>{t("bots.rotateKey")}</button>}
                  {hasPermission("bots.delete") && <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(b)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {bots.length === 0 && <tr><td colSpan={8} className="empty">{t("bots.noB")}</td></tr>}
          </tbody>
        </table>
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("bots.deleteBot")}
        message={<><strong>{deleteTarget?.display_name}</strong>{t("common.deleteConfirmSuffix")}<br />{t("common.irreversible")}</>}
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
      <ConfirmModal
        open={!!rotateTarget}
        title={t("bots.rotateKeyTitle")}
        message={
          <>
            <strong>{rotateTarget?.display_name}</strong>{t("bots.rotateKeyDescSuffix")}<br />
            <strong>{t("bots.rotateKeyWarn1")}</strong><br />
            {t("bots.rotateKeyWarn2")}
          </>
        }
        confirmLabel={t("bots.rotateKeyConfirm")}
        danger
        onConfirm={performRotate}
        onCancel={() => setRotateTarget(null)}
      />
    </PageLayout>
  );
}
