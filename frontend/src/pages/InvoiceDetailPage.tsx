/**
 * 請求書詳細ページ。
 * ステータスアクション（発行/入金/無効化）+ 明細表示。
 *
 * 変更履歴:
 *   2026-04-17: 初版作成（Phase 2）
 */

import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { usePermissions } from "../hooks/usePermissions";

interface InvoiceItem {
  id: number;
  product_name: string;
  quantity: number;
  unit_price: number;
  weight: number | null;
  subtotal: number;
}

interface InvoiceDetail {
  id: number;
  invoice_number: string | null;
  quote_id: number | null;
  customer_id: number;
  currency: string;
  subtotal: number | null;
  shipping_fee: number | null;
  tax_amount: number | null;
  total_amount: number | null;
  exchange_rate_jpy: number | null;
  exchange_rate_usd: number | null;
  amount_jpy: number | null;
  amount_usd: number | null;
  payment_method: string | null;
  status: string;
  branch_number: number | null;
  erp_key: string | null;
  issued_at: string | null;
  due_date: string | null;
  paid_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  notes: string | null;
  created_at: string;
  items: InvoiceItem[];
}

const STATUS_LABELS: Record<string, string> = {
  draft: "下書き", issued: "発行済", paid: "入金済", overdue: "期限超過", voided: "無効",
};

export default function InvoiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { hasPermission } = usePermissions();
  const [invoice, setInvoice] = useState<InvoiceDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [voidReason, setVoidReason] = useState("");
  const [showVoidForm, setShowVoidForm] = useState(false);

  const load = async () => {
    try {
      const data = await api.get<InvoiceDetail>(`/invoices/${id}`);
      setInvoice(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [id]);

  const doAction = async (action: string, body: unknown = {}) => {
    try {
      await api.post(`/invoices/${id}/${action}`, body);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作に失敗しました");
    }
  };

  const handleVoid = async () => {
    if (!voidReason.trim()) { setError("無効化理由を入力してください"); return; }
    await doAction("void", { reason: voidReason });
    setShowVoidForm(false);
    setVoidReason("");
  };

  const fmt = (n: number | null) => n != null ? n.toLocaleString() : "-";

  if (loading) return <div className="page"><div className="loading">読み込み中...</div></div>;
  if (!invoice) return <div className="page"><div className="error-message">{error || "請求書が見つかりません"}</div></div>;

  return (
    <div className="page">
      <div className="page-header">
        <h2>請求書詳細 — {invoice.invoice_number || `#${invoice.id}`}</h2>
        <div className="actions" style={{ display: "flex", gap: 8 }}>
          {invoice.status === "draft" && hasPermission("invoices.create") && (
            <button className="btn-primary" onClick={() => doAction("issue")}>発行する</button>
          )}
          {(invoice.status === "issued" || invoice.status === "overdue") && hasPermission("invoices.update") && (
            <button className="btn-primary" onClick={() => doAction("pay")}>入金登録</button>
          )}
          {invoice.status !== "voided" && hasPermission("invoices.void") && (
            <button className="btn-danger" onClick={() => setShowVoidForm(true)}>無効化</button>
          )}
          <button className="btn-secondary" onClick={() => navigate("/invoices/new")}>一覧に戻る</button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {showVoidForm && (
        <div style={{ background: "var(--danger-bg)", padding: 16, borderRadius: 8, marginBottom: 16 }}>
          <label style={{ display: "block", marginBottom: 8, fontWeight: 600, color: "var(--danger-text)" }}>無効化理由 *</label>
          <input style={{ width: "100%", padding: 8, borderRadius: 4, border: "1px solid var(--border)" }}
                 value={voidReason} onChange={(e) => setVoidReason(e.target.value)} placeholder="無効化の理由を入力..." />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <button className="btn-secondary" onClick={() => setShowVoidForm(false)}>キャンセル</button>
            <button className="btn-danger" onClick={handleVoid}>無効化実行</button>
          </div>
        </div>
      )}

      <div style={{ background: "var(--bg-surface)", padding: 24, borderRadius: 8, boxShadow: "var(--shadow-sm)", marginBottom: 24 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
          <div><strong>ステータス:</strong> <span className={`badge badge-${invoice.status === "paid" ? "won" : invoice.status === "voided" ? "lost" : "pending"}`}>{STATUS_LABELS[invoice.status]}</span></div>
          <div><strong>通貨:</strong> {invoice.currency}</div>
          <div><strong>支払方法:</strong> {invoice.payment_method || "-"}</div>
          <div><strong>発行日:</strong> {invoice.issued_at ? new Date(invoice.issued_at).toLocaleDateString() : "-"}</div>
          <div><strong>支払期限:</strong> {invoice.due_date || "-"}</div>
          <div><strong>入金日:</strong> {invoice.paid_at ? new Date(invoice.paid_at).toLocaleDateString() : "-"}</div>
          <div><strong>為替 JPY:</strong> {invoice.exchange_rate_jpy ?? "-"}</div>
          <div><strong>為替 USD:</strong> {invoice.exchange_rate_usd ?? "-"}</div>
          <div><strong>ERP Key:</strong> <span className="mono">{invoice.erp_key || "-"}</span></div>
          {invoice.void_reason && <div style={{ gridColumn: "1 / -1" }}><strong>無効化理由:</strong> {invoice.void_reason}</div>}
          {invoice.notes && <div style={{ gridColumn: "1 / -1" }}><strong>備考:</strong> {invoice.notes}</div>}
        </div>
      </div>

      <h3 style={{ marginBottom: 12 }}>明細</h3>
      <table className="data-table" style={{ marginBottom: 24 }}>
        <thead>
          <tr><th>商品名</th><th>数量</th><th>単価</th><th>重量</th><th>小計</th></tr>
        </thead>
        <tbody>
          {invoice.items.map((item) => (
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
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 600 }}>小計</td><td style={{ fontWeight: 600 }}>{fmt(invoice.subtotal)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>送料</td><td>{fmt(invoice.shipping_fee)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right" }}>税額</td><td>{fmt(invoice.tax_amount)}</td></tr>
          <tr><td colSpan={4} style={{ textAlign: "right", fontWeight: 700, fontSize: "1.1rem" }}>合計</td><td style={{ fontWeight: 700, fontSize: "1.1rem" }}>{fmt(invoice.total_amount)} {invoice.currency}</td></tr>
          {invoice.amount_jpy != null && <tr><td colSpan={4} style={{ textAlign: "right", color: "var(--text-muted)" }}>JPY換算</td><td style={{ color: "var(--text-muted)" }}>¥{invoice.amount_jpy.toLocaleString()}</td></tr>}
          {invoice.amount_usd != null && <tr><td colSpan={4} style={{ textAlign: "right", color: "var(--text-muted)" }}>USD換算</td><td style={{ color: "var(--text-muted)" }}>${invoice.amount_usd.toLocaleString()}</td></tr>}
        </tfoot>
      </table>
    </div>
  );
}
