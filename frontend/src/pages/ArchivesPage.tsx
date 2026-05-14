import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Archive { id: number; source_table: string; source_id: number; archived_by: number | null; archived_at: string; restored_at: string | null; }

export default function ArchivesPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [archives, setArchives] = useState<Archive[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setArchives(await api.get<Archive[]>("/archives")); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.fetchError")); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const restore = async (id: number) => {
    try { await api.post(`/archives/${id}/restore`, {}); load(); }
    catch (e) { setError(e instanceof Error ? e.message : t("common.operationError")); }
  };

  return (
    <div className="page">
      <div className="page-header"><h2>{t("archives.title")}</h2></div>
      {error && <div className="error-message">{error}</div>}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table">
          <thead><tr><th>{t("common.type")}</th><th>元ID</th><th>{t("common.date")}</th><th>復元日</th><th>{t("common.actions")}</th></tr></thead>
          <tbody>
            {archives.map(a => (
              <tr key={a.id}>
                <td>{a.source_table}</td><td>{a.source_id}</td>
                <td>{new Date(a.archived_at).toLocaleDateString()}</td>
                <td>{a.restored_at ? new Date(a.restored_at).toLocaleDateString() : "-"}</td>
                <td className="actions">
                  {!a.restored_at && hasPermission("archive.manage") && <button className="btn-sm btn-primary" onClick={() => restore(a.id)}>復元</button>}
                  {a.restored_at && <span className="badge badge-won">復元済</span>}
                </td>
              </tr>
            ))}
            {archives.length === 0 && <tr><td colSpan={5} className="empty">{t("common.noData")}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
