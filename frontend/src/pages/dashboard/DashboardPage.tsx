/**
 * ダッシュボードページ（Sprint 4: 受注統合カード＋期間連動グラフ）
 *
 * - 営業担当 / リード担当 / チーム タブ切り替え
 * - 表示期間プルダウン（1w / 1m / 3m / 6m / 12m）
 * - 固定エリア: 目標 / フォローアップ（2枚に整理）
 * - 受注統合カード（営業/チームのみ）: 確定売上・件数・着地予測＋期間連動グラフ
 *   - 1w/1m → 日次棒グラフ、3m/6m/12m → 月次棒グラフ
 * - 期間連動エリア: リード / 商談（受注は統合カードに移動）
 *
 * 変更履歴:
 *   2026-04-17: Phase 3 拡張
 *   2026-05-25: ダッシュボード強化
 *   2026-05-31: Sprint 1–3 ロール別・グラフ・先月比
 *   2026-06-01: Sprint 4 受注統合カード＋期間連動グラフ
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  ResponsiveContainer,
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { api } from "../../lib/api";
import { PageLayout } from "../../components/PageLayout";
import { DashboardIcons } from "../../constants/icons";
import "./DashboardPage.css";

const TrendUpIcon = DashboardIcons.forecast;
const BellIcon = DashboardIcons.reminder;
const CalendarCheckIcon = DashboardIcons.goalDone;
const ArrowRightIcon = DashboardIcons.arrowRight;
const FlagIcon = DashboardIcons.goalFlag;
const TrendUpArrow = DashboardIcons.trendUp;
const TrendDownArrow = DashboardIcons.trendDown;

// ─── 型定義 ──────────────────────────────────────────────────

type Tab = "sales" | "lead" | "team";
type Period = "1w" | "1m" | "3m" | "6m" | "12m";

interface GoalWithActual {
  id: number | null;
  kpi_type: string;
  target_value: number;
  actual_value: number;
  achievement_rate: number;
}

interface GoalSummary {
  monthly: GoalWithActual[];
  weekly: GoalWithActual[];
}

interface Forecast {
  forecast_amount: number;
  open_deal_count: number;
  won_amount: number;
  period_start: string;
  period_end: string;
}

interface FollowUpItem {
  id: number;
  customer_name: string;
  next_action: string | null;
  next_action_date: string | null;
  days_overdue: number;
}

interface FollowUps {
  overdue: FollowUpItem[];
  due_today: FollowUpItem[];
  upcoming: FollowUpItem[];
}

interface StalledDeal {
  id: number;
  title: string;
  stage: string | null;
  days_stalled: number;
}

interface StalledDealsReport {
  stalled_count: number;
  stalled_deals: StalledDeal[];
}

interface DashboardSummary {
  period: string;
  start_date: string;
  end_date: string;
  leads: {
    total: number;
    converted: number;
    excluded: number;
    conversion_rate: number;
  };
  deals: {
    total: number;
    active: number;
    won: number;
    win_rate: number;
  };
  orders: {
    total_revenue: number;
    order_count: number;
    active_count: number;
  };
  comparison: PeriodComparison;
}

interface RevenueChartEntry {
  label: string;        // 月次: "2026-01" / 日次: "2026-05-31"
  actual: number;
  forecast: number | null;
  remaining: number;
  is_current: boolean;
}

interface RevenueChartResponse {
  granularity: "daily" | "monthly";
  entries: RevenueChartEntry[];
}

interface KpiChange {
  pct: number | null;
  direction: "up" | "down" | "flat";
}

interface PeriodComparison {
  leads_total: KpiChange;
  leads_cv_rate: KpiChange;
  deals_active: KpiChange;
  deals_won: KpiChange;
  deals_win_rate: KpiChange;
  orders_revenue: KpiChange;
  orders_count: KpiChange;
}

// ─── 定数 ────────────────────────────────────────────────────

const KPI_LABEL_KEYS: Record<string, string> = {
  revenue:         "dashboard.kpiRevenue",
  deal_count:      "dashboard.kpiDealCount",
  close_rate:      "dashboard.kpiCloseRate",
  lead_count:      "dashboard.kpiLeadCount",
  conversion_rate: "dashboard.kpiConversionRate",
};

const KPI_UNIT: Record<string, string> = {
  revenue:         "¥",
  deal_count:      "",
  close_rate:      "%",
  lead_count:      "",
  conversion_rate: "%",
};

// タブ別に表示するKPIタイプを絞り込む
const LEAD_KPI_TYPES = new Set(["lead_count", "conversion_rate"]);
const SALES_KPI_TYPES = new Set(["revenue", "deal_count", "close_rate"]);

const filterGoalsByTab = (goals: GoalWithActual[], tab: Tab): GoalWithActual[] => {
  if (tab === "team") return goals;
  const allowed = tab === "lead" ? LEAD_KPI_TYPES : SALES_KPI_TYPES;
  return goals.filter((g) => allowed.has(g.kpi_type));
};

// チャート用カラー（CSS変数を直接使えないため getComputedStyle で取得）
const getChartColors = () => {
  const root = document.documentElement;
  const style = getComputedStyle(root);
  const accent = style.getPropertyValue("--accent").trim() || "#1877F2";
  return { actual: accent, remaining: `${accent}40` };
};

// YAxis フォーマット（万単位）— 単位文字はコンポーネント内で t() 経由で渡す
const formatYValue = (value: number, unitMan: string, unitOku: string): string => {
  if (value === 0) return "0";
  if (value >= 100_000_000) return `${Math.round(value / 100_000_000)}${unitOku}`;
  if (value >= 10_000) return `${Math.round(value / 10_000)}${unitMan}`;
  return String(value);
};

// XAxis フォーマット（月次）: "2026-01" → "1月"
const formatXMonth = (label: string, unitMonth: string): string => {
  const m = label.split("-")[1];
  return m ? `${parseInt(m, 10)}${unitMonth}` : label;
};

// XAxis フォーマット（日次）: "2026-05-31" → "5/31"
const formatXDay = (label: string): string => {
  const parts = label.split("-");
  return parts.length === 3 ? `${parseInt(parts[1], 10)}/${parseInt(parts[2], 10)}` : label;
};

// フロントのタブ → バックエンドの tab パラメータに変換
// sales/lead はどちらも個人視点（future: ロール別 API 拡張時に分岐）
const toApiTab = (tab: Tab): "team" | "individual" =>
  tab === "team" ? "team" : "individual";

// ─── サブコンポーネント ────────────────────────────────────────

function AchievementBar({ rate }: { rate: number }) {
  const clamped = Math.min(rate, 100);
  const color =
    clamped >= 100
      ? "var(--success)"
      : clamped >= 70
      ? "var(--accent)"
      : clamped >= 40
      ? "var(--warning-text)"
      : "var(--danger)";

  return (
    <div className="db-progress-wrap">
      <div
        className="db-progress-bar"
        style={{ width: `${clamped}%`, background: color }}
      />
    </div>
  );
}

function GoalRow({
  g,
  t,
}: {
  g: GoalWithActual;
  t: (k: string, opts?: Record<string, unknown>) => string;
}) {
  const labelKey = KPI_LABEL_KEYS[g.kpi_type] ?? g.kpi_type;
  const unit = KPI_UNIT[g.kpi_type] ?? "";
  const isPercent = unit === "%";
  const isMoney = unit === "¥";
  const fmt = (v: number) =>
    isMoney
      ? `¥${v.toLocaleString("ja-JP", { maximumFractionDigits: 0 })}`
      : isPercent
      ? `${v}%`
      : String(v);

  // 達成率が100%未満かつ数値系KPIのみ逆算表示（率KPIは逆算が不自然なので非表示）
  const remaining =
    !isPercent && g.target_value > 0 && g.achievement_rate < 100
      ? g.target_value - g.actual_value
      : null;

  return (
    <div className="db-goal-row">
      <span className="db-goal-label">{t(labelKey)}</span>
      <span className="db-goal-values">
        <span className="db-goal-actual">{fmt(g.actual_value)}</span>
        <span className="db-goal-sep">/</span>
        <span className="db-goal-target">{g.target_value > 0 ? fmt(g.target_value) : "-"}</span>
      </span>
      <span
        className="db-goal-rate"
        style={{
          color:
            g.achievement_rate >= 100
              ? "var(--success)"
              : g.achievement_rate >= 70
              ? "var(--accent)"
              : "var(--danger)",
        }}
      >
        {g.target_value > 0 ? `${g.achievement_rate}%` : "-"}
      </span>
      {remaining !== null && remaining > 0 && (
        <span className="db-goal-remaining">
          {t("dashboard.goalRemaining", { value: fmt(remaining) })}
        </span>
      )}
      {g.target_value > 0 && <AchievementBar rate={g.achievement_rate} />}
    </div>
  );
}

function VsPrev({ change }: { change: KpiChange }) {
  if (change.pct === null) return null;
  const abs = Math.abs(change.pct);
  if (change.direction === "flat") {
    return <span className="db-vs-prev db-vs-flat">—</span>;
  }
  const ArrowIcon = change.direction === "up" ? TrendUpArrow : TrendDownArrow;
  return (
    <span className={`db-vs-prev db-vs-${change.direction}`}>
      <ArrowIcon aria-hidden="true" size={12} />
      {abs}%
    </span>
  );
}

// ─── メインコンポーネント ──────────────────────────────────────

export default function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // デフォルトは営業担当ビュー。
  // team タブには team_id 選択 UI が未実装のため graceful fallback は backend 側で対応済。
  const [tab, setTab] = useState<Tab>("sales");
  const [period, setPeriod] = useState<Period>("1m");

  const [goals, setGoals] = useState<GoalSummary | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [followups, setFollowups] = useState<FollowUps | null>(null);
  const [stalled, setStalled] = useState<StalledDealsReport | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [revenueChart, setRevenueChart] = useState<RevenueChartResponse | null>(null);

  const [loadingFixed, setLoadingFixed] = useState(true);
  const [loadingPeriod, setLoadingPeriod] = useState(true);
  const [loadingChart, setLoadingChart] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoadingFixed(true);
    Promise.all([
      api.get<GoalSummary>(`/goals/summary?tab=${toApiTab(tab)}`),
      api.get<Forecast>("/analytics/forecast"),
      api.get<FollowUps>("/analytics/followups"),
      api.get<StalledDealsReport>("/analytics/stalled-deals?threshold_days=14"),
    ])
      .then(([g, f, fu, sd]) => {
        setGoals(g);
        setForecast(f);
        setFollowups(fu);
        setStalled(sd);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoadingFixed(false));
  }, [tab]);

  useEffect(() => {
    setLoadingPeriod(true);
    api
      .get<DashboardSummary>(`/analytics/summary?period=${period}&tab=${toApiTab(tab)}`)
      .then(setSummary)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingPeriod(false));
  }, [tab, period]);

  // チャートフォーマッター（t() が必要なため component 内で定義）
  const yTickFormatter = (value: number) =>
    formatYValue(value, t("common.unitMan"), t("common.unitOku"));
  const xTickFormatter = (label: string) =>
    revenueChart?.granularity === "daily"
      ? formatXDay(label)
      : formatXMonth(label, t("common.unitMonth"));

  // 受注グラフ: リードビューでは不要。タブ・期間変更時に再取得
  useEffect(() => {
    if (tab === "lead") {
      setLoadingChart(false);
      return;
    }
    setLoadingChart(true);
    api
      .get<RevenueChartResponse>(`/analytics/monthly-revenue?period=${period}`)
      .then(setRevenueChart)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingChart(false));
  }, [tab, period]);

  const fmt = (n: number | null | undefined) => {
    if (n === null || n === undefined) return "¥0";
    return `¥${n.toLocaleString("ja-JP", { maximumFractionDigits: 0 })}`;
  };

  const urgentCount =
    (followups?.overdue.length ?? 0) +
    (followups?.due_today.length ?? 0) +
    (stalled?.stalled_count ?? 0);

  if (error) {
    return (
      <PageLayout navKey="nav.dashboard" subtitleKey="dashboard.subtitle">
        <div className="error-message">{error}</div>
      </PageLayout>
    );
  }

  // 着地予測カードを統合カードに移動したため常に2カラム
  const fixedAreaClass = "db-fixed-area db-two-cols";

  return (
    <PageLayout
      navKey="nav.dashboard"
      subtitleKey="dashboard.subtitle"
      headerLeft={
        <div className="db-tabs">
          <button
            className={`db-tab${tab === "sales" ? " active" : ""}`}
            onClick={() => setTab("sales")}
          >
            {t("dashboard.tabSales")}
          </button>
          <button
            className={`db-tab${tab === "lead" ? " active" : ""}`}
            onClick={() => setTab("lead")}
          >
            {t("dashboard.tabLead")}
          </button>
          <button
            className={`db-tab${tab === "team" ? " active" : ""}`}
            onClick={() => setTab("team")}
          >
            {t("dashboard.tabTeam")}
          </button>
        </div>
      }
      headerAction={
        <div className="page-header-actions">
          <select
            className="page-header-select"
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
            aria-label={t("dashboard.periodLabel")}
          >
            <option value="1w">{t("dashboard.period1w")}</option>
            <option value="1m">{t("dashboard.period1m")}</option>
            <option value="3m">{t("dashboard.period3m")}</option>
            <option value="6m">{t("dashboard.period6m")}</option>
            <option value="12m">{t("dashboard.period12m")}</option>
          </select>
        </div>
      }
    >

      {/* -------------------------------------------------
          固定エリア（期間変更でも不変）
      ------------------------------------------------- */}

      <div className={fixedAreaClass}>

        {/* ── 目標セクション ── */}
        <div className="db-section-card db-goals-card">
          <div className="db-section-header">
            <FlagIcon aria-hidden="true" className="db-section-icon" />
            <h3>{t("dashboard.goalsTitle")}</h3>
            <button
              className="db-set-goals-btn"
              onClick={() => navigate("/goals/settings")}
            >
              {t("dashboard.setGoals")}
              <ArrowRightIcon aria-hidden="true" size={14} />
            </button>
          </div>

          {loadingFixed ? (
            <div className="db-loading">{t("common.loading")}</div>
          ) : (
            <div className="db-goals-body">
              <div className="db-goals-period-block">
                <span className="db-goals-period-label">{t("dashboard.thisMonth")}</span>
                {(() => {
                  const filtered = goals ? filterGoalsByTab(goals.monthly, tab) : [];
                  return filtered.length > 0 ? (
                    filtered.map((g) => <GoalRow key={g.kpi_type} g={g} t={t} />)
                  ) : (
                    <p className="db-no-goals">{t("dashboard.noGoalsSet")}</p>
                  );
                })()}
              </div>
              <div className="db-goals-period-block">
                <span className="db-goals-period-label">{t("dashboard.thisWeek")}</span>
                {(() => {
                  const filtered = goals ? filterGoalsByTab(goals.weekly, tab) : [];
                  return filtered.length > 0 ? (
                    filtered.map((g) => <GoalRow key={g.kpi_type} g={g} t={t} />)
                  ) : (
                    <p className="db-no-goals">{t("dashboard.noGoalsSet")}</p>
                  );
                })()}
              </div>
            </div>
          )}
        </div>

        {/* ── フォローアップリマインド ── */}
        <div className={`db-section-card db-followup-card${urgentCount > 0 ? " db-has-urgent" : ""}`}>
          <div className="db-section-header">
            <BellIcon aria-hidden="true" className="db-section-icon" />
            <h3>
              {t("dashboard.followupTitle")}
              {urgentCount > 0 && (
                <span className="db-badge-urgent">{urgentCount}</span>
              )}
            </h3>
          </div>
          {loadingFixed ? (
            <div className="db-loading">{t("common.loading")}</div>
          ) : (
            <div className="db-followup-body">
              {followups && followups.overdue.map((item) => (
                <div
                  key={item.id}
                  className="db-followup-item db-overdue db-followup-clickable"
                  onClick={() => navigate("/crm/customers")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate("/crm/customers")}
                >
                  <span className="db-followup-badge">{t("dashboard.overdue")}</span>
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                  <span className="db-followup-date">{item.days_overdue}{t("dashboard.daysAgo")}</span>
                </div>
              ))}
              {followups && followups.due_today.map((item) => (
                <div
                  key={item.id}
                  className="db-followup-item db-due-today db-followup-clickable"
                  onClick={() => navigate("/crm/customers")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate("/crm/customers")}
                >
                  <span className="db-followup-badge db-badge-today">{t("dashboard.dueToday")}</span>
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                </div>
              ))}
              {stalled && stalled.stalled_deals.slice(0, 3).map((d) => (
                <div
                  key={d.id}
                  className="db-followup-item db-stalled db-followup-clickable"
                  onClick={() => navigate("/deals")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate("/deals")}
                >
                  <span className="db-followup-badge db-badge-stalled">{t("dashboard.stalled")}</span>
                  <span className="db-followup-name">{d.title}</span>
                  <span className="db-followup-date">{d.days_stalled}{t("dashboard.daysNoUpdate")}</span>
                </div>
              ))}
              {followups && followups.upcoming.slice(0, 3).map((item) => (
                <div
                  key={item.id}
                  className="db-followup-item db-followup-clickable"
                  onClick={() => navigate("/crm/customers")}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === "Enter" && navigate("/crm/customers")}
                >
                  <CalendarCheckIcon aria-hidden="true" size={14} className="db-followup-icon" />
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                  <span className="db-followup-date">{item.next_action_date}</span>
                </div>
              ))}
              {urgentCount === 0 && followups?.upcoming.length === 0 && (
                <p className="db-empty">{t("dashboard.noFollowups")}</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* -------------------------------------------------
          受注統合カード（営業/チームビューのみ）
          確定売上 + 着地予測 + 期間連動グラフ
      ------------------------------------------------- */}

      {tab !== "lead" && (
        <div className="db-chart-card">
          <div className="db-section-header">
            <TrendUpIcon aria-hidden="true" className="db-section-icon" />
            <h3>{t("dashboard.sectionOrders")}</h3>
          </div>

          {/* KPI + 着地予測 統計行 */}
          {!loadingFixed && !loadingPeriod && summary && (
            <div className="db-revenue-stats">
              <div className="db-revenue-stat">
                <span className="db-revenue-stat-label">{t("dashboard.orderRevenue")}</span>
                <span className="db-revenue-stat-value">{fmt(summary.orders.total_revenue)}</span>
                <VsPrev change={summary.comparison.orders_revenue} />
              </div>
              <div className="db-revenue-stat">
                <span className="db-revenue-stat-label">{t("dashboard.orderCount")}</span>
                <span className="db-revenue-stat-value">{summary.orders.order_count}</span>
                <VsPrev change={summary.comparison.orders_count} />
              </div>
              {forecast && (
                <div className="db-revenue-stat db-revenue-forecast">
                  <span className="db-revenue-stat-label">{t("dashboard.forecastTitle")}</span>
                  <span className="db-revenue-stat-value db-revenue-forecast-value">
                    {fmt(forecast.forecast_amount)}
                  </span>
                  <span className="db-revenue-stat-sub">
                    {t("dashboard.openDealCount")}: {forecast.open_deal_count}{t("dashboard.unitDeal")}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* グラフ */}
          {loadingChart ? (
            <div className="db-loading">{t("common.loading")}</div>
          ) : revenueChart && revenueChart.entries.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <ComposedChart
                data={revenueChart.entries}
                margin={{ top: 8, right: 16, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-muted)" vertical={false} />
                <XAxis
                  dataKey="label"
                  tickFormatter={xTickFormatter}
                  tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                  interval={revenueChart.granularity === "daily" ? "preserveStartEnd" : 0}
                />
                <YAxis
                  tickFormatter={yTickFormatter}
                  tick={{ fontSize: 12, fill: "var(--text-secondary)" }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    const actual = Number(payload.find((p) => p.dataKey === "actual")?.value ?? 0);
                    const remaining = Number(payload.find((p) => p.dataKey === "remaining")?.value ?? 0);
                    return (
                      <div className="db-chart-tooltip">
                        <p className="db-chart-tooltip-label">{xTickFormatter(label as string)}</p>
                        <p>{t("dashboard.chartActual")}: ¥{actual.toLocaleString("ja-JP")}</p>
                        {remaining > 0 && (
                          <p>{t("dashboard.chartTooltipForecast")}: ¥{(actual + remaining).toLocaleString("ja-JP")}</p>
                        )}
                      </div>
                    );
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                <Bar
                  dataKey="actual"
                  name={t("dashboard.chartActual")}
                  stackId="rev"
                  fill={getChartColors().actual}
                  radius={[0, 0, 0, 0]}
                  maxBarSize={revenueChart.granularity === "daily" ? 24 : 48}
                />
                {revenueChart.granularity === "monthly" && (
                  <Bar
                    dataKey="remaining"
                    name={t("dashboard.chartRemaining")}
                    stackId="rev"
                    fill={getChartColors().remaining}
                    radius={[3, 3, 0, 0]}
                    maxBarSize={48}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <p className="db-empty">{t("dashboard.noData")}</p>
          )}
        </div>
      )}

      {/* -------------------------------------------------
          期間連動エリア（ロール別）
      ------------------------------------------------- */}

      <div className="db-period-area">
        {loadingPeriod ? (
          <div className="db-loading">{t("common.loading")}</div>
        ) : summary ? (
          <>
            {/* リード（リードビューとチームビューのみ表示）*/}
            {(tab === "lead" || tab === "team") && (
              <div className="db-metric-card">
                <div className="db-metric-title">{t("dashboard.sectionLeads")}</div>
                <div className="kpi-grid">
                  <div className="kpi-card">
                    <div className="kpi-value">{summary.leads.total}</div>
                    <div className="kpi-label">{t("dashboard.leadTotal")}</div>
                    <VsPrev change={summary.comparison.leads_total} />
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-value">{summary.leads.converted}</div>
                    <div className="kpi-label">{t("dashboard.leadConverted")}</div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-value">{summary.leads.excluded}</div>
                    <div className="kpi-label">{t("dashboard.leadExcluded")}</div>
                  </div>
                  <div className="kpi-card accent">
                    <div className="kpi-value">{summary.leads.conversion_rate}%</div>
                    <div className="kpi-label">{t("dashboard.conversionRate")}</div>
                    <VsPrev change={summary.comparison.leads_cv_rate} />
                  </div>
                </div>
              </div>
            )}

            {/* 商談（営業ビューとチームビューのみ表示・totalは削除）*/}
            {(tab === "sales" || tab === "team") && (
              <div className="db-metric-card">
                <div className="db-metric-title">{t("dashboard.sectionDeals")}</div>
                <div className="kpi-grid">
                  <div className="kpi-card">
                    <div className="kpi-value">{summary.deals.active}</div>
                    <div className="kpi-label">{t("dashboard.dealActive")}</div>
                    <VsPrev change={summary.comparison.deals_active} />
                  </div>
                  <div className="kpi-card accent">
                    <div className="kpi-value">{summary.deals.won}</div>
                    <div className="kpi-label">{t("dashboard.dealWon")}</div>
                    <VsPrev change={summary.comparison.deals_won} />
                  </div>
                  <div className="kpi-card accent">
                    <div className="kpi-value">{summary.deals.win_rate}%</div>
                    <div className="kpi-label">{t("dashboard.winRate")}</div>
                    <VsPrev change={summary.comparison.deals_win_rate} />
                  </div>
                </div>
              </div>
            )}

            {/* 受注は統合カードに移動 */}
          </>
        ) : null}
      </div>
    </PageLayout>
  );
}
