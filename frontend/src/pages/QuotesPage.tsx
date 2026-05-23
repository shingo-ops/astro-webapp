/**
 * 見積もり一覧ページ。
 * ステータスフィルター + 見積一覧テーブル。新規作成はQuoteCreatePageに遷移。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface Quote {
  id: number;
  quote_code: string | null;
  deal_id: number | null;
  // Step 5d: 旧 customer_id を撤去、company_id を必須化
  company_id: number;
  currency: string;
  subtotal: number | null;
  total_amount: number | null;
  status: string;
  validity_date: string | null;
  created_at: string;
}

const QUOTE_STATUSES = ["draft", "sent", "approved", "rejected", "expired"];

export default function QuotesPage() {
  const { t } = useTranslation();
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
      setError(e instanceof Error ? e.message : t("common.fetchError"));
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
        <h2>{t("nav.quotesInvoices")}</h2>
        {hasPermission("quotes.create") && (
          <button className="btn-primary" onClick={() => navigate("/quotes/new")}>{t("quotes.newQuote")}</button>
        )}
      </div>

      <nav className="tab-nav">
        <button className="tab-active">{t("nav.quoteHistory")}</button>
        <button onClick={() => navigate("/invoices")}>{t("nav.invoices")}</button>
      </nav>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">{t("quotes.allStatuses")}</option>
          {QUOTE_STATUSES.map((s) => <option key={s} value={s}>{t(`quotes.status_${s}`)}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("quotes.quoteCode")}</th>
              <th>{t("common.currency")}</th>
              <th>{t("quotes.total")}</th>
              <th>{t("common.status")}</th>
              <th>{t("quotes.validityDate")}</th>
              <th>{t("common.createdAt")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {quotes.map((q) => (
              <tr key={q.id}>
                <td className="mono">{q.quote_code || "-"}</td>
                <td>{q.currency}</td>
                <td>{fmt(q.total_amount, q.currency)}</td>
                <td><span className={`badge badge-${q.status === "approved" ? "won" : q.status === "rejected" ? "lost" : q.status === "expired" ? "cancelled" : q.status === "sent" ? "negotiating" : "pending"}`}>
                  {t(`quotes.status_${q.status}`) || q.status}
                </span></td>
                <td>{q.validity_date || "-"}</td>
                <td>{new Date(q.created_at).toLocaleDateString()}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => navigate(`/quotes/${q.id}`)}>{t("common.detail")}</button>
                </td>
              </tr>
            ))}
            {quotes.length === 0 && <tr><td colSpan={7} className="empty">{t("quotes.noQuotes")}</td></tr>}
          </tbody>
        </table>
      )}
    </div>
  );
}
