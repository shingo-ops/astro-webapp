import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface Dashboard {
  customer_count: number;
  deal_count: number;
  deal_open_count: number;
  deal_won_count: number;
  deal_total_amount: number;
  deal_won_amount: number;
  order_count: number;
  order_pending_count: number;
  order_total_amount: number;
  recent_customers: Array<{ id: number; name: string; company: string | null; created_at: string }>;
  recent_deals: Array<{ id: number; title: string; amount: number | null; status: string; created_at: string }>;
}

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<Dashboard>("/dashboard").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error-message">エラー: {error}</div>;
  if (!data) return <div className="loading">読み込み中...</div>;

  const fmt = (n: number) => n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });

  return (
    <div className="page">
      <h2>ダッシュボード</h2>

      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-value">{data.customer_count}</div>
          <div className="kpi-label">顧客数</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value">{data.deal_open_count}</div>
          <div className="kpi-label">進行中の商談</div>
        </div>
        <div className="kpi-card accent">
          <div className="kpi-value">{data.deal_won_count}</div>
          <div className="kpi-label">成約商談</div>
        </div>
        <div className="kpi-card accent">
          <div className="kpi-value">{fmt(data.deal_won_amount)}</div>
          <div className="kpi-label">成約金額</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value">{data.order_count}</div>
          <div className="kpi-label">注文数</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-value">{fmt(data.order_total_amount)}</div>
          <div className="kpi-label">注文総額</div>
        </div>
      </div>

      <div className="dashboard-tables">
        <div className="card">
          <h3>最近の顧客</h3>
          <table>
            <thead>
              <tr><th>名前</th><th>会社</th><th>登録日</th></tr>
            </thead>
            <tbody>
              {data.recent_customers.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.company || "-"}</td>
                  <td>{new Date(c.created_at).toLocaleDateString("ja-JP")}</td>
                </tr>
              ))}
              {data.recent_customers.length === 0 && (
                <tr><td colSpan={3} className="empty">データなし</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>最近の商談</h3>
          <table>
            <thead>
              <tr><th>タイトル</th><th>金額</th><th>ステータス</th></tr>
            </thead>
            <tbody>
              {data.recent_deals.map((d) => (
                <tr key={d.id}>
                  <td>{d.title}</td>
                  <td>{d.amount ? fmt(d.amount) : "-"}</td>
                  <td><span className={`badge badge-${d.status}`}>{d.status}</span></td>
                </tr>
              ))}
              {data.recent_deals.length === 0 && (
                <tr><td colSpan={3} className="empty">データなし</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
