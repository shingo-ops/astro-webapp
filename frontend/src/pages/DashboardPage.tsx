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
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

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
  const { t } = useTranslation();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Dashboard>("/dashboard").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="page"><div className="error-message">Error: {error}</div></div>;
  if (!data) return <div className="page"><div className="loading">{t("common.loading")}</div></div>;

  // 通貨フォーマット (円表示)
  // 背景: backend は Decimal 列を JSON 上は文字列で返すため (例: `amount * probability / 100.0`
  // から得られる `weighted_amount` は "192000.0000000000000000" のような Postgres NUMERIC 由来
  // の長い小数文字列になる)、`toLocaleString()` だけだと文字列のまま桁分割もされず表示されてしまう。
  // 文字列→数値変換 + maximumFractionDigits:0 で「¥1,200,000」のように整円表示に統一する。
  const fmt = (n: number | string | null | undefined) => {
    if (n === null || n === undefined) return "¥0";
    const num = typeof n === "string" ? parseFloat(n) : n;
    if (Number.isNaN(num)) return "¥0";
    return `¥${num.toLocaleString("ja-JP", { maximumFractionDigits: 0 })}`;
  };

  const DEAL_STATUS_LABELS: Record<string, string> = {
    open: t("deals.status_open"),
    negotiating: t("deals.status_negotiating"),
    won: t("deals.status_won"),
    lost: t("deals.status_lost"),
    on_hold: t("deals.status_on_hold"),
  };
  const STAGE_LABELS: Record<string, string> = {
    open: t("dashboard.firstContact"),
    negotiating: t("dashboard.discovery"),
    proposal: t("dashboard.proposalSent"),
    on_hold: t("dashboard.onHold"),
  };

  return (
    <div className="page">
      <h2>{t("dashboard.title")}</h2>

      {/* === 営業 KPI === */}
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>{t("dashboard.sales")}</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.customer_count}</div><div className="kpi-label">{t("dashboard.customers")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.lead_count}</div><div className="kpi-label">{t("dashboard.leads")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.lead_inbound_count} / {data.lead_outbound_count}</div><div className="kpi-label">{t("dashboard.inboundOutbound")}</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{data.lead_conversion_rate}%</div><div className="kpi-label">{t("dashboard.conversionRate")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.deal_open_count}</div><div className="kpi-label">{t("dashboard.openDeals")}</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{data.deal_won_count}</div><div className="kpi-label">{t("dashboard.wonDeals")}</div></div>
        <div className="kpi-card accent"><div className="kpi-value">{fmt(data.deal_won_amount)}</div><div className="kpi-label">{t("dashboard.wonAmount")}</div></div>
      </div>

      {/* === パイプライン === */}
      {data.pipeline_by_stage.length > 0 && (
        <>
          <h3 style={{ marginTop: 24, marginBottom: 8, color: "var(--text-secondary)" }}>{t("dashboard.pipeline")}</h3>
          <div style={{ background: "var(--bg-surface)", borderRadius: 8, padding: 16, boxShadow: "var(--shadow-sm)", marginBottom: 24 }}>
            <table className="data-table">
              <thead>
                <tr><th>{t("dashboard.stage")}</th><th>{t("dashboard.count")}</th><th>{t("dashboard.amount")}</th><th>{t("dashboard.weightedAmount")}</th></tr>
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
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>{t("dashboard.finance")}</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.quote_count}</div><div className="kpi-label">{t("dashboard.quotes")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.quote_approved_amount)}</div><div className="kpi-label">{t("dashboard.approvedQuoteAmount")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.invoice_count}</div><div className="kpi-label">{t("dashboard.invoices")}</div></div>
        <div className="kpi-card" style={{ borderLeft: data.invoice_unpaid_count > 0 ? "3px solid var(--danger)" : undefined }}>
          <div className="kpi-value" style={{ color: data.invoice_unpaid_count > 0 ? "var(--danger)" : undefined }}>{data.invoice_unpaid_count}</div>
          <div className="kpi-label">{t("dashboard.unpaid")}</div>
        </div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.order_total_amount)}</div><div className="kpi-label">{t("dashboard.orderTotal")}</div></div>
      </div>

      {/* === 在庫・仕入 KPI === */}
      <h3 style={{ marginTop: 16, marginBottom: 8, color: "var(--text-secondary)" }}>{t("dashboard.inventoryPurchasing")}</h3>
      <div className="kpi-grid">
        <div className="kpi-card"><div className="kpi-value">{data.product_count}</div><div className="kpi-label">{t("dashboard.products")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{fmt(data.inventory_value)}</div><div className="kpi-label">{t("dashboard.inventoryValue")}</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.supplier_count}</div><div className="kpi-label">Suppliers</div></div>
        <div className="kpi-card"><div className="kpi-value">{data.po_pending_count}</div><div className="kpi-label">{t("dashboard.pendingPos")}</div></div>
      </div>

      {/* === 直近データ === */}
      <div className="dashboard-tables">
        <div className="card">
          <h3>{t("dashboard.recentCustomers")}</h3>
          <table>
            <thead><tr><th>{t("common.name")}</th><th>{t("common.company")}</th><th>{t("common.createdAt")}</th></tr></thead>
            <tbody>
              {data.recent_customers.map((c) => (
                <tr key={c.id}><td>{c.name || c.customer_code}</td><td>{c.company || "-"}</td><td>{new Date(c.created_at).toLocaleDateString("en-US")}</td></tr>
              ))}
              {data.recent_customers.length === 0 && <tr><td colSpan={3} className="empty">{t("dashboard.noData")}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>{t("dashboard.recentDeals")}</h3>
          <table>
            <thead><tr><th>{t("deals.dealTitle")}</th><th>{t("dashboard.amount")}</th><th>{t("common.status")}</th></tr></thead>
            <tbody>
              {data.recent_deals.map((d) => (
                <tr key={d.id}><td>{d.title}</td><td>{d.amount ? fmt(d.amount) : "-"}</td>
                  <td><span className={`badge badge-${d.status}`}>{DEAL_STATUS_LABELS[d.status] || d.status}</span></td></tr>
              ))}
              {data.recent_deals.length === 0 && <tr><td colSpan={3} className="empty">{t("dashboard.noData")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
