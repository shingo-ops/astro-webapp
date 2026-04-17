import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface PO { id: number; po_number: string | null; supplier_id: number; status: string; total_amount: number | null; ordered_at: string | null; received_at: string | null; created_at: string; }
const STATUS_LABELS: Record<string, string> = { draft: "下書き", ordered: "発注済", received: "入荷済", cancelled: "キャンセル" };

export default function PurchaseOrdersPage() {
  const { hasPermission } = usePermissions();
  const navigate = useNavigate();
  const [pos, setPos] = useState<PO[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try { setPos(await api.get<PO[]>(`/purchase-orders${statusFilter ? `?status=${statusFilter}` : ""}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "取得失敗"); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [statusFilter]);

  const doAction = async (id: number, action: string) => {
    try { await api.post(`/purchase-orders/${id}/${action}`, {}); load(); }
    catch (e) { setError(e instanceof Error ? e.message : "操作失敗"); }
  };

  return (
    <div className="page">
      <div className="page-header"><h2>仕入注文管理</h2></div>
      <div className="filter-bar">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">全ステータス</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {error && <div className="error-message">{error}</div>}
      {loading ? <div className="loading">読み込み中...</div> : (
        <table className="data-table">
          <thead><tr><th>PO番号</th><th>合計金額</th><th>ステータス</th><th>発注日</th><th>入荷日</th><th>操作</th></tr></thead>
          <tbody>
            {pos.map(p => (
              <tr key={p.id}>
                <td className="mono">{p.po_number || "-"}</td>
                <td>{p.total_amount != null ? `¥${p.total_amount.toLocaleString()}` : "-"}</td>
                <td><span className={`badge badge-${p.status === "received" ? "won" : p.status === "cancelled" ? "lost" : p.status === "ordered" ? "negotiating" : "pending"}`}>{STATUS_LABELS[p.status]}</span></td>
                <td>{p.ordered_at ? new Date(p.ordered_at).toLocaleDateString() : "-"}</td>
                <td>{p.received_at ? new Date(p.received_at).toLocaleDateString() : "-"}</td>
                <td className="actions">
                  {p.status === "draft" && hasPermission("purchase_orders.update") && <button className="btn-sm btn-primary" onClick={() => doAction(p.id, "order")}>発注</button>}
                  {p.status === "ordered" && hasPermission("purchase_orders.receive") && <button className="btn-sm btn-primary" onClick={() => doAction(p.id, "receive")}>入荷</button>}
                  {(p.status === "draft" || p.status === "ordered") && <button className="btn-sm btn-danger" onClick={() => doAction(p.id, "cancel")}>取消</button>}
                </td>
              </tr>
            ))}
            {pos.length === 0 && <tr><td colSpan={6} className="empty">仕入注文がありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
