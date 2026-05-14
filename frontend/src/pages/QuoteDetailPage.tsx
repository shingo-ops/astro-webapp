/**
 * 見積もり詳細ページ。
 * 見積ヘッダー + 明細表示、ステータスアクション（送付/承認/却下/請求書変換）。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface QuoteItem {
  id: number;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight: number | null;
  subtotal: number;
}

interface QuoteDetail {
  id: number;
  quote_code: string | null;
  deal_id: number | null;
  // Step 5d: 旧 customer_id を撤去、company_id を必須化
  company_id: number;
  currency: string;
  subtotal: number | null;
  shipping_fee: number | null;
  tax_amount: number | null;
  total_amount: number | null;
  status: string;
  validity_date: string | null;
  notes: string | null;
  created_at: string;
  items: QuoteItem[];
}

export default function QuoteDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const [quote, setQuote] = useState<QuoteDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const data = await api.get<QuoteDetail>(`/quotes/${id}`);
      setQuote(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const doAction = async (action: string) => {
    try {
      await api.post(`/quotes/${id}/${action}`, {});
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  const convertToInvoice = async () => {
    try {
      const result = await api.post<{ id: number }>(`/invoices/from-quote/${id}`, {});
      navigate(`/invoices/${result.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  const fmt = (n: number | null) => {
    if (n == null) return "-";
    return n.toLocaleString();
  };

  if (loading) return <div className="page"><div className="loading">{t("common.loading")}</div></div>;
  if (!quote) return <div className="page"><div className="error-message">{error || t("common.fetchError")}</div></div>;

  return (
    <div className="page">
      <div className="page-header">
        <h2>{t("quotes.title")} — {quote.quote_code || `#${quote.id}`}</h2>
        <div className="actions" style={{ display: "flex", gap: 8 }}>
          {quote.status === "draft" && hasPermission("quotes.update") && (
            <button className="btn-primary" onClick={() => doAction("send")}>{t("quotes.send")}</button>
          )}
          {quote.status === "sent" && hasPermission("quotes.approve") && (
            <>
              <button className="btn-primary" onClick={() => doAction("approve")}>{t("quotes.approve")}</button>
              <button className="btn-danger" onClick={() => doAction("reject")}>{t("quotes.reject")}</button>
            </>
          )}
          {quote.status === "approved" && hasPermission("invoices.create") && (
            <button className="btn-primary" onClick={convertToInvoice}>{t("quotes.convertToInvoice")}</button>
          )}
          <button className="btn-secondary" onClick={() => navigate("/quotes")}>{t("common.back")}</button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div style={{ background: "var(--bg-surface)", padding: 24, borderRadius: 8, boxShadow: "var(--shadow-sm)", marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <div><strong>{t("common.status")}:</strong> <span className={`badge badge-${quote.status === "approved" ? "won" : quote.status === "rejected" ? "lost" : "pending"}`}>{t(`quotes.status_${quote.status}`)}</span></div>
          <div><strong>{t("common.currency")}:</strong> {quote.currency}</div>
          <div><strong>{t("quotes.validityDate")}:</strong> {quote.validity_date || "-"}</div>
          <div><strong>{t("common.createdAt")}:</strong> {new Date(quote.created_at).toLocaleDateString()}</div>
          <div><strong>{t("common.notes")}:</strong> {quote.notes || "-"}</div>
        </div>
      </div>

      <h3 style={{ marginBottom: 12 }}>{t("quotes.items")}</h3>
      <table className="data-table" style={{ marginBottom: 24 }}>
        <thead>
          <tr>
            <th>{t("quotes.product")}</th>
            <th>{t("quotes.quantity")}</th>
            <th>{t("quotes.unitPrice")}</th>
            <th>{t("quotes.weight")}</th>
            <th>{t("quotes.subtotal")}</th>
          </tr>
        </thead>
        <tbody>
          {quote.items.map((item) => (
            <tr key={item.id}>
              <td>{item.product_name}</td>
              <td>{item.quantity}</td>
              <td>{fmt(item.unit_price)}</td>
              <td>{item.weight != null ? `${item.weight}kg` : "-"}</td>
              <td style={{ fontWeight: 600 }}>{fmt(item.subtotal)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 600 }}>{t("quotes.subtotal")}</td><td style={{ fontWeight: 600 }}>{fmt(quote.subtotal)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>{t("quotes.shippingFee")}</td><td>{fmt(quote.shipping_fee)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>{t("quotes.tax")}</td><td>{fmt(quote.tax_amount)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 700, fontSize: "1.1rem" }}>{t("quotes.total")}</td><td style={{ fontWeight: 700, fontSize: "1.1rem" }}>{fmt(quote.total_amount)} {quote.currency}</td></tr>
        </tfoot>
      </table>
    </div>
  );
}
