/**
 * 見積もり詳細ページ。
 * 見積ヘッダー + 明細表示、ステータスアクション（送付/承認/却下/請求書変換）。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
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
  customer_id: number;
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

const STATUS_LABELS: Record<string, string> = {
  draft: "下書き", sent: "送付済", approved: "承認済", rejected: "却下", expired: "期限切れ",
};

export default function QuoteDetailPage() {
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
      setError(e instanceof Error ? e.message : "取得に失敗しました");
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
      setError(e instanceof Error ? e.message : "操作に失敗しました");
    }
  };

  const convertToInvoice = async () => {
    try {
      const result = await api.post<{ id: number }>(`/invoices/from-quote/${id}`, {});
      navigate(`/invoices/${result.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "請求書変換に失敗しました");
    }
  };

  const fmt = (n: number | null) => {
    if (n == null) return "-";
    return n.toLocaleString();
  };

  if (loading) return <div className="page"><div className="loading">読み込み中...</div></div>;
  if (!quote) return <div className="page"><div className="error-message">{error || "見積もりが見つかりません"}</div></div>;

  return (
    <div className="page">
      <div className="page-header">
        <h2>見積もり詳細 — {quote.quote_code || `#${quote.id}`}</h2>
        <div className="actions" style={{ display: "flex", gap: 8 }}>
          {quote.status === "draft" && hasPermission("quotes.update") && (
            <button className="btn-primary" onClick={() => doAction("send")}>送付済にする</button>
          )}
          {quote.status === "sent" && hasPermission("quotes.approve") && (
            <>
              <button className="btn-primary" onClick={() => doAction("approve")}>承認</button>
              <button className="btn-danger" onClick={() => doAction("reject")}>却下</button>
            </>
          )}
          {quote.status === "approved" && hasPermission("invoices.create") && (
            <button className="btn-primary" onClick={convertToInvoice}>請求書に変換</button>
          )}
          <button className="btn-secondary" onClick={() => navigate("/quotes")}>一覧に戻る</button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div style={{ background: "var(--bg-surface)", padding: 24, borderRadius: 8, boxShadow: "var(--shadow-sm)", marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <div><strong>ステータス:</strong> <span className={`badge badge-${quote.status === "approved" ? "won" : quote.status === "rejected" ? "lost" : "pending"}`}>{STATUS_LABELS[quote.status]}</span></div>
          <div><strong>通貨:</strong> {quote.currency}</div>
          <div><strong>有効期限:</strong> {quote.validity_date || "-"}</div>
          <div><strong>作成日:</strong> {new Date(quote.created_at).toLocaleDateString()}</div>
          <div><strong>備考:</strong> {quote.notes || "-"}</div>
        </div>
      </div>

      <h3 style={{ marginBottom: 12 }}>明細</h3>
      <table className="data-table" style={{ marginBottom: 24 }}>
        <thead>
          <tr>
            <th>商品名</th>
            <th>数量</th>
            <th>単価</th>
            <th>重量</th>
            <th>小計</th>
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
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 600 }}>小計</td><td style={{ fontWeight: 600 }}>{fmt(quote.subtotal)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>送料</td><td>{fmt(quote.shipping_fee)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>税額</td><td>{fmt(quote.tax_amount)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 700, fontSize: "1.1rem" }}>合計</td><td style={{ fontWeight: 700, fontSize: "1.1rem" }}>{fmt(quote.total_amount)} {quote.currency}</td></tr>
        </tfoot>
      </table>
    </div>
  );
}
