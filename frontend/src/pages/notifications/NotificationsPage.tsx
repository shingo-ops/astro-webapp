import { useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { PageLayout } from "../../components/PageLayout";
import { usePermissions } from "../../hooks/usePermissions";

interface Channel { id: number; channel_name: string; webhook_url: string; event_types: string; is_active: boolean; created_at: string; }

export default function NotificationsPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ channel_name: "", webhook_url: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setChannels(await api.get<Channel[]>("/notification-channels")); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/notification-channels", { channel_name: form.channel_name, webhook_url: form.webhook_url });
      setShowForm(false); setForm({ channel_name: "", webhook_url: "" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : t("common.saveError")); }
  };

  const handleDelete = async (id: number) => {
    try { await api.delete(`/notification-channels/${id}`); load(); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.deleteError")); }
  };

  return (
    <PageLayout
      navKey="nav.notifications"
      headerAction={
        hasPermission("notifications.manage") ? (
          <button className="btn-primary" onClick={() => setShowForm(true)}>{t("settings.addChannel")}</button>
        ) : undefined
      }
    >
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>{t("settings.addDiscordWebhook")}</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>{t("settings.channelName")} *</label><input required value={form.channel_name} onChange={e => setForm({ ...form, channel_name: e.target.value })} placeholder="例: #crm-activity" /></div>
              <div className="form-group"><label>Webhook URL *</label><input required value={form.webhook_url} onChange={e => setForm({ ...form, webhook_url: e.target.value })} placeholder="https://discord.com/api/webhooks/..." /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>{t("common.cancel")}</button>
                <button type="submit" className="btn-primary">{t("common.add")}</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table">
          <thead><tr><th>{t("settings.channelName")}</th><th>Webhook URL</th><th>{t("common.status")}</th><th>{t("common.actions")}</th></tr></thead>
          <tbody>
            {channels.map(ch => (
              <tr key={ch.id}>
                <td>{ch.channel_name}</td>
                <td className="mono" style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>{ch.webhook_url}</td>
                <td><span className={`badge badge-${ch.is_active ? "won" : "lost"}`}>{ch.is_active ? t("common.active") : t("common.inactive")}</span></td>
                <td className="actions">
                  {hasPermission("notifications.manage") && <button className="btn-sm btn-danger" onClick={() => handleDelete(ch.id)}>{t("common.delete")}</button>}
                </td>
              </tr>
            ))}
            {channels.length === 0 && <tr><td colSpan={4} className="empty">{t("settings.noChannels")}</td></tr>}
          </tbody>
        </table>
      )}
    </PageLayout>
  );
}
