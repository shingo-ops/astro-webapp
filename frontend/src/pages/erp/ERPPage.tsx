import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";

interface SyncLog { id: number; sync_type: string; direction: string; record_count: number; status: string; error_message: string | null; started_at: string; completed_at: string | null; }

export default function ERPPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [logs, setLogs] = useState<SyncLog[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const load = async () => {
    try { setLogs(await api.get<SyncLog[]>("/erp/sync-logs")); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, []);

  const exportInvoices = async () => {
    setExporting(true); setError("");
    try {
      const resp = await fetch("/api/v1/erp/export-invoices", {
        method: "POST",
        headers: { Authorization: `Bearer ${await (await import("firebase/auth")).getAuth().currentUser?.getIdToken()}`, "Content-Type": "application/json" },
      });
      if (!resp.ok) throw new Error(t("common.operationError"));
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "erp_invoices.csv"; a.click();
      URL.revokeObjectURL(url);
      load();
    } catch (e) { setError(e instanceof Error ? e.message : t("common.operationError")); }
    finally { setExporting(false); }
  };

  return (
    <PageLayout
      navKey="nav.dataManagement"
      subtitleKey="erp.subtitle"
      headerAction={hasPermission("erp.sync") ? (
        <button className="btn-primary" onClick={exportInvoices} disabled={exporting}>
          {exporting ? t("erp.exporting") : t("erp.exportInvoices")}
        </button>
      ) : undefined}
    >
      {error && <div className="error-message">{error}</div>}
      <h3 style={{ marginBottom: "var(--space-3)" }}>{t("erp.syncLogs")}</h3>
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table">
          <thead><tr><th>{t("erp.colType")}</th><th>{t("erp.colDirection")}</th><th>{t("erp.colCount")}</th><th>{t("common.status")}</th><th>{t("erp.colStartedAt")}</th><th>{t("erp.colCompletedAt")}</th><th>{t("common.error")}</th></tr></thead>
          <tbody>
            {logs.map(l => (
              <tr key={l.id}>
                <td>{l.sync_type}</td>
                <td>{l.direction === "export" ? t("erp.directionExport") : t("erp.directionImport")}</td>
                <td>{l.record_count}</td>
                <td><span className={`badge badge-${l.status === "completed" ? "won" : l.status === "failed" ? "lost" : "pending"}`}>{l.status}</span></td>
                <td>{new Date(l.started_at).toLocaleString()}</td>
                <td>{l.completed_at ? new Date(l.completed_at).toLocaleString() : "-"}</td>
                <td style={{ color: "var(--danger)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>{l.error_message || "-"}</td>
              </tr>
            ))}
            {logs.length === 0 && <tr><td colSpan={7} className="empty">{t("erp.noLogs")}</td></tr>}
          </tbody>
        </table>
      )}
    </PageLayout>
  );
}
