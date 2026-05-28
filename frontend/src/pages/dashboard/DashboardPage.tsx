/**
 * ダッシュボードページ（強化版）。
 *
 * - チーム / 個人 タブ切り替え
 * - 表示期間プルダウン（1w / 1m / 3m / 6m / 12m）
 * - 固定エリア: 目標（今月・今週） / 着地予測 / フォローアップリマインド
 * - 期間連動エリア: リード / 商談 / 受注
 *
 * 変更履歴:
 *   2026-04-17: Phase 3 拡張
 *   2026-05-25: ダッシュボード強化（タブ・期間・目標・着地予測・フォローアップ）
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../../lib/api";
import { PageLayout } from "../../components/PageLayout";
import { DashboardIcons } from "../../constants/icons";
import "./DashboardPage.css";

const TrendUpIcon = DashboardIcons.forecast;
const BellIcon = DashboardIcons.reminder;
const CalendarCheckIcon = DashboardIcons.goalDone;
const ArrowRightIcon = DashboardIcons.arrowRight;
const FlagIcon = DashboardIcons.goalFlag;

// ─── 型定義 ──────────────────────────────────────────────────

type Tab = "team" | "individual";
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

function GoalRow({ g, t }: { g: GoalWithActual; t: (k: string) => string }) {
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
      {g.target_value > 0 && <AchievementBar rate={g.achievement_rate} />}
    </div>
  );
}

// ─── メインコンポーネント ──────────────────────────────────────

export default function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // hotfix: default を "individual" にして team_id 未指定での 422 を避ける。
  // team タブには team_id 選択 UI が未実装のため、ユーザーが手動で切替えた
  // 場合のみ team モードに入る (graceful fallback は backend 側で対応済)。
  const [tab, setTab] = useState<Tab>("individual");
  const [period, setPeriod] = useState<Period>("1m");

  const [goals, setGoals] = useState<GoalSummary | null>(null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [followups, setFollowups] = useState<FollowUps | null>(null);
  const [stalled, setStalled] = useState<StalledDealsReport | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  const [loadingFixed, setLoadingFixed] = useState(true);
  const [loadingPeriod, setLoadingPeriod] = useState(true);
  const [error, setError] = useState("");

  // 固定エリアデータ取得（タブ変更時に再取得）
  useEffect(() => {
    setLoadingFixed(true);
    Promise.all([
      api.get<GoalSummary>(`/goals/summary?tab=${tab}`),
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

  // 期間連動エリアデータ取得（タブ・期間変更時に再取得）
  useEffect(() => {
    setLoadingPeriod(true);
    api
      .get<DashboardSummary>(`/analytics/summary?period=${period}&tab=${tab}`)
      .then(setSummary)
      .catch((e) => setError(e.message))
      .finally(() => setLoadingPeriod(false));
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

  return (
    <PageLayout
      navKey="nav.dashboard"
      subtitleKey="dashboard.subtitle"
      headerLeft={
        <div className="db-tabs">
          <button
            className={`db-tab${tab === "team" ? " active" : ""}`}
            onClick={() => setTab("team")}
          >
            {t("dashboard.tabTeam")}
          </button>
          <button
            className={`db-tab${tab === "individual" ? " active" : ""}`}
            onClick={() => setTab("individual")}
          >
            {t("dashboard.tabIndividual")}
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

      <div className="db-fixed-area">
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
              {/* 今月の目標 */}
              <div className="db-goals-period-block">
                <span className="db-goals-period-label">{t("dashboard.thisMonth")}</span>
                {goals && goals.monthly.length > 0 ? (
                  goals.monthly.map((g) => (
                    <GoalRow key={g.kpi_type} g={g} t={t} />
                  ))
                ) : (
                  <p className="db-no-goals">{t("dashboard.noGoalsSet")}</p>
                )}
              </div>
              {/* 今週の目標 */}
              <div className="db-goals-period-block">
                <span className="db-goals-period-label">{t("dashboard.thisWeek")}</span>
                {goals && goals.weekly.length > 0 ? (
                  goals.weekly.map((g) => (
                    <GoalRow key={g.kpi_type} g={g} t={t} />
                  ))
                ) : (
                  <p className="db-no-goals">{t("dashboard.noGoalsSet")}</p>
                )}
              </div>
            </div>
          )}
        </div>

        {/* ── 着地予測 ── */}
        <div className="db-section-card db-forecast-card">
          <div className="db-section-header">
            <TrendUpIcon aria-hidden="true" className="db-section-icon" />
            <h3>{t("dashboard.forecastTitle")}</h3>
          </div>
          {loadingFixed ? (
            <div className="db-loading">{t("common.loading")}</div>
          ) : forecast ? (
            <div className="db-forecast-body">
              <div className="db-forecast-main">
                <span className="db-forecast-label">{t("dashboard.forecastAmount")}</span>
                <span className="db-forecast-value">
                  {fmt(forecast.forecast_amount)}
                </span>
              </div>
              <div className="db-forecast-sub">
                <span>{t("dashboard.wonAmountThisMonth")}: {fmt(forecast.won_amount)}</span>
                <span>{t("dashboard.openDealCount")}: {forecast.open_deal_count}{t("dashboard.unitDeal")}</span>
              </div>
            </div>
          ) : null}
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
              {/* 期限切れ */}
              {followups && followups.overdue.map((item) => (
                <div key={item.id} className="db-followup-item db-overdue">
                  <span className="db-followup-badge">{t("dashboard.overdue")}</span>
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                  <span className="db-followup-date">{item.days_overdue}{t("dashboard.daysAgo")}</span>
                </div>
              ))}
              {/* 今日期限 */}
              {followups && followups.due_today.map((item) => (
                <div key={item.id} className="db-followup-item db-due-today">
                  <span className="db-followup-badge db-badge-today">{t("dashboard.dueToday")}</span>
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                </div>
              ))}
              {/* 停滞商談 */}
              {stalled && stalled.stalled_deals.slice(0, 3).map((d) => (
                <div key={d.id} className="db-followup-item db-stalled">
                  <span className="db-followup-badge db-badge-stalled">{t("dashboard.stalled")}</span>
                  <span className="db-followup-name">{d.title}</span>
                  <span className="db-followup-date">{d.days_stalled}{t("dashboard.daysNoUpdate")}</span>
                </div>
              ))}
              {/* 直近フォローアップ */}
              {followups && followups.upcoming.slice(0, 3).map((item) => (
                <div key={item.id} className="db-followup-item">
                  <CalendarCheckIcon aria-hidden="true" size={14} className="db-followup-icon" />
                  <span className="db-followup-name">{item.customer_name}</span>
                  <span className="db-followup-action">{item.next_action || "-"}</span>
                  <span className="db-followup-date">{item.next_action_date}</span>
                </div>
              ))}
              {urgentCount === 0 &&
                followups?.upcoming.length === 0 && (
                  <p className="db-empty">{t("dashboard.noFollowups")}</p>
                )}
            </div>
          )}
        </div>
      </div>

      {/* -------------------------------------------------
          期間連動エリア
      ------------------------------------------------- */}

      <div className="db-period-area">
        {loadingPeriod ? (
          <div className="db-loading">{t("common.loading")}</div>
        ) : summary ? (
          <>
            {/* リード */}
            <div className="db-metric-card">
              <div className="db-metric-title">{t("dashboard.sectionLeads")}</div>
              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-value">{summary.leads.total}</div>
                  <div className="kpi-label">{t("dashboard.leadTotal")}</div>
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
                </div>
              </div>
            </div>

            {/* 商談 */}
            <div className="db-metric-card">
              <div className="db-metric-title">{t("dashboard.sectionDeals")}</div>
              <div className="kpi-grid">
                <div className="kpi-card">
                  <div className="kpi-value">{summary.deals.total}</div>
                  <div className="kpi-label">{t("dashboard.dealTotal")}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-value">{summary.deals.active}</div>
                  <div className="kpi-label">{t("dashboard.dealActive")}</div>
                </div>
                <div className="kpi-card accent">
                  <div className="kpi-value">{summary.deals.won}</div>
                  <div className="kpi-label">{t("dashboard.dealWon")}</div>
                </div>
                <div className="kpi-card accent">
                  <div className="kpi-value">{summary.deals.win_rate}%</div>
                  <div className="kpi-label">{t("dashboard.winRate")}</div>
                </div>
              </div>
            </div>

            {/* 受注 */}
            <div className="db-metric-card">
              <div className="db-metric-title">{t("dashboard.sectionOrders")}</div>
              <div className="kpi-grid">
                <div className="kpi-card accent">
                  <div className="kpi-value">{fmt(summary.orders.total_revenue)}</div>
                  <div className="kpi-label">{t("dashboard.orderRevenue")}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-value">{summary.orders.order_count}</div>
                  <div className="kpi-label">{t("dashboard.orderCount")}</div>
                </div>
                <div className="kpi-card">
                  <div className="kpi-value">{summary.orders.active_count}</div>
                  <div className="kpi-label">{t("dashboard.orderActive")}</div>
                </div>
              </div>
            </div>
          </>
        ) : null}
      </div>
    </PageLayout>
  );
}

