/**
 * 見積もり一覧ページ。
 * ステータスフィルター + 見積一覧テーブル。新規作成はQuoteCreatePageに遷移。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Quote {
  id: number;
  quote_code: string | null;
  deal_id: number | null;
  customer_id: number;
  currency: string;
  subtotal: number | null;
  total_amount: number | null;
  status: string;
  validity_date: string | null;
  created_at: string;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "下書き", sent: "送付済", approved: "承認済", rejected: "却下", expired: "期限切れ",
};

export default function QuotesPage() {
  const { hasPermission } = usePermissions();
  const navigate = useNavigate();
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const params = statusFilter ? `?status=${statusFilter}` : "";
      const data = await api.get<Quote[]>(`/quotes${params}`);
      setQuotes(data);
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
        <h2>見積もり履歴</h2>
        {hasPermission("quotes.create") && (
          <button className="btn-primary" onClick={() => navigate("/quotes/new")}>見積もり作成</button>
        )}
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
              <th>見積番号</th>
              <th>通貨</th>
              <th>合計</th>
              <th>ステータス</th>
              <th>有効期限</th>
              <th>作成日</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => (
              <tr key={q.id}>
                <td className="mono">{q.quote_code || "-"}</td>
                <td>{q.currency}</td>
                <td>{fmt(q.total_amount, q.currency)}</td>
                <td><span className={`badge badge-${q.status === "approved" ? "won" : q.status === "rejected" ? "lost" : q.status === "expired" ? "cancelled" : q.status === "sent" ? "negotiating" : "pending"}`}>
                  {STATUS_LABELS[q.status] || q.status}
                </span></td>
                <td>{q.validity_date || "-"}</td>
                <td>{new Date(q.created_at).toLocaleDateString()}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => navigate(`/quotes/${q.id}`)}>詳細</button>
                </td>
              </tr>
            ))}
            {quotes.length === 0 && <tr><td colSpan={7} className="empty">見積もりがありません</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
