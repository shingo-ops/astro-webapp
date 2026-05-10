/**
 * ダッシュボードページ（Phase 3 拡張版）。
 *
 * KPI: 顧客/リード（Inbound/Outbound/コンバージョン率）/案件/注文/
 *      見積/請求（未入金）/在庫/仕入先/PO
 * パイプライン: ステージ別の件数・金額・加重金額
 * 直近データ: 顧客/案件/リード/見積
 *
 * 変更履歴:
 *   2026-04-17: Phase 3 拡張（見積/請求/在庫/パイプライン/コンバージョン率）
 */

import { useEffect, useState } from "react";
import { api } from "../lib/api";

const DEAL_STATUS_LABELS: Record<string, string> = {
  open: "Open", negotiating: "Negotiating", won: "Won", lost: "Lost", on_hold: "On hold",
};
const STAGE_LABELS: Record<string, string> = {
  open: "First contact", negotiating: "Discovery", proposal: "Proposal sent", on_hold: "On hold",
};

interface PipelineStage {
  stage: string;
  count: number;
  amount: number;
  weighted_amount: number;
}

interface Dashboard {
  customer_count: number;
  lead_count: number;
  lead_open_count: number;
  lead_inbound_count: number;
  lead_outbound_count: number;
  lead_conversion_rate: number;
  deal_count: number;
  deal_open_count: number;
  deal_won_count: number;
  deal_total_amount: number;
  deal_won_amount: number;
  order_count: number;
  order_pending_count: number;
  order_total_amount: number;
  team_count: number;
  quote_count: number;
  quote_draft_count: number;
  quote_approved_amount: number;
  invoice_count: number;
  invoice_unpaid_count: number;
  invoice_unpaid_amount: number;
  product_count: number;
  inventory_value: number;
  supplier_count: number;
  po_pending_count: number;
  pipeline_by_stage: PipelineStage[];
  recent_customers: Array<{ id: number; customer_code: string; name: string | null; company: string | null; created_at: string }>;
  recent_deals: Array<{ id: number; title: string; amount: number | null; status: string; created_at: string }>;
  recent_leads: Array<{ id: number; customer_name: string; status: string; prospect_rank: string | null; created_at: string }>;
  recent_quotes: Array<{ id: number; quote_code: string; total_amount: number | null; status: string; created_at: string }>;
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Dashboard>("/dashboard").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="page"><div className="error-message">Error: {error}</div></div>;
  if (!data) return <div className="page"><div className="loading">Loading...</div></div>;

  const fmt = (n: number) => `¥${n.toLocaleString()}`;

  return (
    <div className="page">
      <h2>Dashboard</h2>

      {/* === 営業 KPI === */}
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>Sales</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.customer_count}</div><div className="kpi-label">Customers</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.lead_count}</div><div className="kpi-label">Leads</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.lead_inbound_count} / {data.lead_outbound_count}</div><div className="kpi-label">Inbound / Outbound</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{data.lead_conversion_rate}%</div><div className="kpi-label">Conversion rate</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.deal_open_count}</div><div className="kpi-label">Open deals</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{data.deal_won_count}</div><div className="kpi-label">Won deals</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{fmt(data.deal_won_amount)}</div><div className="kpi-label">Won amount</div></div>
      </div>

      {/* === パイプライン === */}
      {data.pipeline_by_stage.length > 0 && (
        <>
          <h3 style={{ marginTop: 24, marginBottom: 8, color: "var(--text-secondary)" }}>Pipeline (by stage)</h3>
          <div style={{ background: "var(--bg-surface)", borderRadius: 8, padding: 16, boxShadow: "var(--shadow-sm)", marginBottom: 24 }}>
            <table className="data-table">
              <thead>
                <tr><th>Stage</th><th>Count</th><th>Amount</th><th>Weighted amount</th></tr>
              </thead>
              <tbody>
                {data.pipeline_by_stage.map((s) => (
                  <tr key={s.stage}>
                    <td>{STAGE_LABELS[s.stage] || s.stage}</td>
                    <td>{s.count}</td>
                    <td>{fmt(s.amount)}</td>
                    <td style={{ fontWeight: 600 }}>{fmt(s.weighted_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* === 財務 KPI === */}
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>Finance</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.quote_count}</div><div className="kpi-label">Quotes</div></div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.quote_approved_amount)}</div><div className="kpi-label">Approved quote amount</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.invoice_count}</div><div className="kpi-label">Invoices</div></div>
        <div className="kpi-card" style={{ borderLeft: data.invoice_unpaid_count > 0 ? "3px solid var(--danger)" : undefined }}>
          <div className="kpi-value" style={{ color: data.invoice_unpaid_count > 0 ? "var(--danger)" : undefined }}>{data.invoice_unpaid_count}</div>
          <div className="kpi-label">Unpaid</div>
        </div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.order_total_amount)}</div><div className="kpi-label">Order total</div></div>
      </div>

      {/* === 在庫・仕入 KPI === */}
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>Inventory & purchasing</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.product_count}</div><div className="kpi-label">Products</div></div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.inventory_value)}</div><div className="kpi-label">Inventory value</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.supplier_count}</div><div className="kpi-label">Suppliers</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.po_pending_count}</div><div className="kpi-label">Pending POs</div></div>
      </div>

      {/* === 直近データ === */}
      <div className="dashboard-tables">
        <div className="card">
          <h3>Recent customers</h3>
          <table>
            <thead><tr><th>Name</th><th>Company</th><th>Created</th></tr></thead>
            <tbody>
              {data.recent_customers.map((c) => (
                <tr key={c.id}><td>{c.name || c.customer_code}</td><td>{c.company || "-"}</td><td>{new Date(c.created_at).toLocaleDateString("en-US")}</td></tr>
              ))}
              {data.recent_customers.length === 0 && <tr><td colSpan={3} className="empty">No data</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Recent deals</h3>
          <table>
            <thead><tr><th>Title</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody>
              {data.recent_deals.map((d) => (
                <tr key={d.id}><td>{d.title}</td><td>{d.amount ? fmt(d.amount) : "-"}</td>
                  <td><span className={`badge badge-${d.status}`}>{DEAL_STATUS_LABELS[d.status] || d.status}</span></td></tr>
              ))}
              {data.recent_deals.length === 0 && <tr><td colSpan={3} className="empty">No data</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
