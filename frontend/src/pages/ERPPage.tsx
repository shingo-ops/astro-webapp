import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface SyncLog { id: number; sync_type: string; direction: string; record_count: number; status: string; error_message: string | null; started_at: string; completed_at: string | null; }

export default function ERPPage() {
  const { hasPermission } = usePermissions();
  const [logs, setLogs] = useState<SyncLog[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const load = async () => {
    try { setLogs(await api.get<SyncLog[]>("/erp/sync-logs")); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const exportInvoices = async () => {
    setExporting(true); setError("");
    try {
      const resp = await fetch("/api/v1/erp/export-invoices", {
        method: "POST",
        headers: { Authorization: `Bearer ${await (await import("firebase/auth")).getAuth().currentUser?.getIdToken()}`, "Content-Type": "application/json" },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "erp_invoices.csv"; a.click();
      URL.revokeObjectURL(url);
      load();
    } catch (e) { setError(e instanceof Error ? e.message : "エクスポート失敗"); }
    finally { setExporting(false); }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>ERP連携</h2>
        {hasPermission("erp.sync") && (
          <button className="btn-primary" onClick={exportInvoices} disabled={exporting}>
            {exporting ? "エクスポート中..." : "請求書CSVエクスポート"}
          </button>
        )}
      </div>
      {error && <div className="error-message">{error}</div>}
      <h3 style={{ marginBottom: 12 }}>同期ログ</h3>
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>種別</th><th>方向</th><th>件数</th><th>ステータス</th><th>開始日時</th><th>完了日時</th><th>エラー</th></tr></thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id}>
                <td>{l.sync_type}</td>
                <td>{l.direction === "export" ? "エクスポート" : "インポート"}</td>
                <td>{l.record_count}</td>
                <td><span className={`badge badge-${l.status === "completed" ? "won" : l.status === "failed" ? "lost" : "pending"}`}>{l.status}</span></td>
                <td>{new Date(l.started_at).toLocaleString()}</td>
                <td>{l.completed_at ? new Date(l.completed_at).toLocaleString() : "-"}</td>
                <td style={{ color: "var(--danger)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{l.error_message || "-"}</td>
              </tr>
            ))}
            {logs.length === 0 && <tr><td colSpan={7} className="empty">同期ログがありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
