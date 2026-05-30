/**
 * 請求書一覧ページ。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { PageLayout } from "../../components/PageLayout";

interface Invoice {
  id: number;
  invoice_number: string | null;
  // Step 5d: 旧 customer_id を撤去、company_id を必須化
  company_id: number;
  currency: string;
  total_amount: number | null;
  amount_jpy: number | null;
  status: string;
  issued_at: string | null;
  due_date: string | null;
  paid_at: string | null;
  created_at: string;
}

const INVOICE_STATUSES = ["draft", "sent", "paid", "overdue", "cancelled"];

export default function InvoicesPage() {
  const { t } = useTranslation();
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
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [statusFilter]);

  const fmt = (n: number | null, ccy: string) => {
    if (n == null) return "-";
    try { return n.toLocaleString("ja-JP", { style: "currency", currency: ccy }); }
    catch { return `${ccy} ${n.toLocaleString()}`; }
  };

  return (
    <PageLayout
      navKey="nav.quotesInvoices"
      subtitleKey="invoices.subtitle"
      headerAction={
        <button className="btn-primary" onClick={() => navigate("/invoices/new")}>
          {t("invoices.createTitle")}
        </button>
      }
    >
      <nav className="tab-nav">
        <button onClick={() => navigate("/quotes")}>{t("nav.quoteHistory")}</button>
        <button className="tab-active">{t("nav.invoices")}</button>
      </nav>

      <div className="filter-bar">
        <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">{t("invoices.allStatuses")}</option>
          {INVOICE_STATUSES.map((s) => <option key={s} value={s}>{t(`invoices.status_${s}`)}</option>)}
        </select>
      </div>

      {error && <div className="error-message">{error}</div>}

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("invoices.invoiceCode")}</th>
              <th>{t("common.currency")}</th>
              <th>{t("common.amount")}</th>
              <th>{t("invoices.jpyEquiv")}</th>
              <th>{t("common.status")}</th>
              <th>{t("invoices.issuedAt")}</th>
              <th>{t("invoices.dueDate")}</th>
              <th>{t("invoices.paidAt")}</th>
              <th>{t("common.actions")}</th>
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
                  {t(`invoices.status_${inv.status}`) || inv.status}
                </span></td>
                <td>{inv.issued_at ? new Date(inv.issued_at).toLocaleDateString() : "-"}</td>
                <td>{inv.due_date || "-"}</td>
                <td>{inv.paid_at ? new Date(inv.paid_at).toLocaleDateString() : "-"}</td>
                <td className="actions">
                  <button className="btn-sm" onClick={() => navigate(`/invoices/${inv.id}`)}>{t("common.detail")}</button>
                </td>
              </tr>
            ))}
            {invoices.length === 0 && <tr><td colSpan={9} className="empty">{t("invoices.noInvoices")}</td></tr>}
          </tbody>
        </table>
      )}
    </PageLayout>
  );
}
