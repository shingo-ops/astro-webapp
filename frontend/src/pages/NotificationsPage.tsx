import { useEffect, useState, FormEvent } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Channel { id: number; channel_name: string; webhook_url: string; event_types: string; is_active: boolean; created_at: string; }

export default function NotificationsPage() {
  const { hasPermission } = usePermissions();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ channel_name: "", webhook_url: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setChannels(await api.get<Channel[]>("/notification-channels")); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); setError("");
    try {
      await api.post("/notification-channels", { channel_name: form.channel_name, webhook_url: form.webhook_url });
      setShowForm(false); setForm({ channel_name: "", webhook_url: "" }); load();
    } catch (e) { setError(e instanceof Error ? e.message : "保存失敗"); }
  };

  const handleDelete = async (id: number) => {
    try { await api.delete(`/notification-channels/${id}`); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "削除失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>通知設定（Discord Webhook）</h2>
        {hasPermission("notifications.manage") && <button className="btn-primary" onClick={() => setShowForm(true)}>チャンネル追加</button>}
      </div>
      {error && <div className="error-message">{error}</div>}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Discord Webhookチャンネル追加</h3>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>チャンネル名 *</label><input required value={form.channel_name} onChange={e => setForm({ ...form, channel_name: e.target.value })} placeholder="例: #crm-activity" /></div>
              <div className="form-group"><label>Webhook URL *</label><input required value={form.webhook_url} onChange={e => setForm({ ...form, webhook_url: e.target.value })} placeholder="https://discord.com/api/webhooks/..." /></div>
              <div className="form-actions">
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>キャンセル</button>
                <button type="submit" className="btn-primary">追加</button>
              </div>
            </form>
          </div>
        </div>
      )}
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>チャンネル名</th><th>Webhook URL</th><th>状態</th><th>操作</th></tr></thead>
          <tbody>
            {channels.map(ch => (
              <tr key={ch.id}>
                <td>{ch.channel_name}</td>
                <td className="mono" style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>{ch.webhook_url}</td>
                <td><span className={`badge badge-${ch.is_active ? "won" : "lost"}`}>{ch.is_active ? "有効" : "無効"}</span></td>
                <td className="actions">
                  {hasPermission("notifications.manage") && <button className="btn-sm btn-danger" onClick={() => handleDelete(ch.id)}>削除</button>}
                </td>
              </tr>
            ))}
            {channels.length === 0 && <tr><td colSpan={4} className="empty">通知チャンネルが設定されていません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
