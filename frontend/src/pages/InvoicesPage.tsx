/**
 * 請求書一覧ページ。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

interface Invoice {
  id: number;
  invoice_number: string | null;
  customer_id: number;
  currency: string;
  total_amount: number | null;
  amount_jpy: number | null;
  status: string;
  issued_at: string | null;
  due_date: string | null;
  paid_at: string | null;
  created_at: string;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "下書き", issued: "発行済", paid: "入金済", overdue: "期限超過", voided: "無効",
};

export default function InvoicesPage() {
  const navigate = useNavigate();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Invoice[]>(`/invoices${params}`);
      setInvoices(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [statusFilter]);

  const fmt = (n: number | null, ccy: string) => {
    if (n == null) return "-";
    try { return n.toLocaleString("ja-JP", { style: "currency", currency: ccy }); }
    catch { return `${ccy} ${n.toLocaleString()}`; }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>請求書管理</h2>
      </div>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">全ステータス</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>請求番号</th>
              <th>通貨</th>
              <th>合計</th>
              <th>JPY換算</th>
              <th>ステータス</th>
              <th>発行日</th>
              <th>支払期限</th>
              <th>入金日</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td className="mono">{inv.invoice_number || "-"}</td>
                <td>{inv.currency}</td>
                <td>{fmt(inv.total_amount, inv.currency)}</td>
                <td>{inv.amount_jpy != null ? `¥${inv.amount_jpy.toLocaleString()}` : "-"}</td>
                <td><span className={`badge badge-${inv.status === "paid" ? "won" : inv.status === "voided" ? "lost" : inv.status === "overdue" ? "cancelled" : inv.status === "issued" ? "negotiating" : "pending"}`}>
                  {STATUS_LABELS[inv.status] || inv.status}
                </span></td>
                <td>{inv.issued_at ? new Date(inv.issued_at).toLocaleDateString() : "-"}</td>
                <td>{inv.due_date || "-"}</td>
                <td>{inv.paid_at ? new Date(inv.paid_at).toLocaleDateString() : "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => navigate(`/invoices/${inv.id}`)}>詳細</button>
                </td>
              </tr>
            ))}
            {invoices.length === 0 && <tr><td colSpan={9} className="empty">請求書がありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
