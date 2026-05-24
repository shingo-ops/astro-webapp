/**
 * 目標設定ページ。
 *
 * ダッシュボードの「目標を設定する」ボタンから遷移する。
 * チームリーダー: チーム目標 + 個人目標を入力可能
 * 一般担当者: 自分の個人目標のみ入力可能
 *
 * ルート: /goals/settings
 *
 * 変更履歴:
 *   2026-05-25: 初版作成（ダッシュボード強化）
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { PageLayout } from "../components/PageLayout";
import { STATUS_ICONS } from "../constants/icons";
import "./GoalSettingPage.css";

const CheckIcon = STATUS_ICONS.check;

// ─── 型定義 ──────────────────────────────────────────────────

type KpiType =
  | "revenue"
  | "deal_count"
  | "close_rate"
  | "lead_count"
  | "conversion_rate";

type PeriodType = "monthly" | "weekly";

interface GoalResponse {
  id: number;
  user_id: number | null;
  team_id: number | null;
  period_type: PeriodType;
  period_year: number;
  period_num: number;
  kpi_type: KpiType;
  target_value: number;
}

interface Team {
  id: number;
  name: string;
  leader_id: number | null;
}

interface CurrentUser {
  id: number;
  role: string;
}

// ─── 定数 ────────────────────────────────────────────────────

const INDIVIDUAL_KPIS: KpiType[] = ["revenue", "deal_count", "close_rate"];
const TEAM_KPIS: KpiType[] = [
  "revenue",
  "deal_count",
  "close_rate",
  "lead_count",
  "conversion_rate",
];

const KPI_LABEL_KEYS: Record<KpiType, string> = {
  revenue:         "dashboard.kpiRevenue",
  deal_count:      "dashboard.kpiDealCount",
  close_rate:      "dashboard.kpiCloseRate",
  lead_count:      "dashboard.kpiLeadCount",
  conversion_rate: "dashboard.kpiConversionRate",
};

const KPI_PLACEHOLDER: Record<KpiType, string> = {
  revenue:         "3000000",
  deal_count:      "10",
  close_rate:      "30",
  lead_count:      "20",
  conversion_rate: "50",
};

function currentYearMonth() {
  const d = new Date();
  return { year: d.getFullYear(), month: d.getMonth() + 1 };
}

function currentYearWeek() {
  const d = new Date();
  const startOfYear = new Date(d.getFullYear(), 0, 1);
  const week = Math.ceil(
    ((d.getTime() - startOfYear.getTime()) / 86400000 + startOfYear.getDay() + 1) / 7
  );
  return { year: d.getFullYear(), week };
}

// ─── GoalInputRow ─────────────────────────────────────────────

interface GoalInputRowProps {
  kpiType: KpiType;
  value: string;
  onChange: (v: string) => void;
  saved: boolean;
  t: (k: string) => string;
}

function GoalInputRow({ kpiType, value, onChange, saved, t }: GoalInputRowProps) {
  return (
    <div className="gs-row">
      <label className="gs-label">{t(KPI_LABEL_KEYS[kpiType])}</label>
      <div className="gs-input-wrap">
        <input
          type="number"
          min="0"
          step="1"
          className={`gs-input${saved ? " gs-input-saved" : ""}`}
          placeholder={KPI_PLACEHOLDER[kpiType]}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        {saved && <span className="gs-saved-mark"><CheckIcon size={14} aria-hidden="true" /></span>}
      </div>
    </div>
  );
}

// ─── GoalBlock（月次/週次 × 個人/チーム） ───────────────────────

interface GoalBlockProps {
  title: string;
  kpis: KpiType[];
  values: Record<KpiType, string>;
  savedKeys: Set<KpiType>;
  onChange: (kpi: KpiType, v: string) => void;
  onSave: () => void;
  saving: boolean;
  t: (k: string) => string;
}

function GoalBlock({
  title, kpis, values, savedKeys, onChange, onSave, saving, t,
}: GoalBlockProps) {
  return (
    <div className="gs-block">
      <h4 className="gs-block-title">{title}</h4>
      <div className="gs-rows">
        {kpis.map((kpi) => (
          <GoalInputRow
            key={kpi}
            kpiType={kpi}
            value={values[kpi] ?? ""}
            onChange={(v) => onChange(kpi, v)}
            saved={savedKeys.has(kpi)}
            t={t}
          />
        ))}
      </div>
      <button className="btn-primary gs-save-btn" onClick={onSave} disabled={saving}>
        {saving ? t("common.saving") : t("goals.save")}
      </button>
    </div>
  );
}

// ─── メインコンポーネント ──────────────────────────────────────

export default function GoalSettingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const [teams, setTeams] = useState<Team[]>([]);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);

  // 個人目標 value マップ
  const [indivMonthValues, setIndivMonthValues] = useState<Record<KpiType, string>>({} as Record<KpiType, string>);
  const [indivWeekValues, setIndivWeekValues] = useState<Record<KpiType, string>>({} as Record<KpiType, string>);
  // チーム目標 value マップ
  const [teamMonthValues, setTeamMonthValues] = useState<Record<KpiType, string>>({} as Record<KpiType, string>);
  const [teamWeekValues, setTeamWeekValues] = useState<Record<KpiType, string>>({} as Record<KpiType, string>);

  const [savedIndivMonth, setSavedIndivMonth] = useState<Set<KpiType>>(new Set());
  const [savedIndivWeek, setSavedIndivWeek] = useState<Set<KpiType>>(new Set());
  const [savedTeamMonth, setSavedTeamMonth] = useState<Set<KpiType>>(new Set());
  const [savedTeamWeek, setSavedTeamWeek] = useState<Set<KpiType>>(new Set());

  const [savingIndivMonth, setSavingIndivMonth] = useState(false);
  const [savingIndivWeek, setSavingIndivWeek] = useState(false);
  const [savingTeamMonth, setSavingTeamMonth] = useState(false);
  const [savingTeamWeek, setSavingTeamWeek] = useState(false);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const { year: curYear, month: curMonth } = currentYearMonth();
  const { year: weekYear, week: curWeek } = currentYearWeek();

  const isLeader = (user: CurrentUser | null, team: Team | null) =>
    user?.role === "admin" ||
    (team !== null && team.leader_id === user?.id);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get<{ id: number; role: string }>("/auth/me"),
      api.get<Team[]>("/teams"),
    ])
      .then(([me, teamList]) => {
        setCurrentUser(me);
        setTeams(teamList);
        if (teamList.length > 0) setSelectedTeamId(teamList[0].id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // 既存目標をロード
  useEffect(() => {
    if (!currentUser) return;
    // 個人目標
    api
      .get<GoalResponse[]>(`/goals?user_id=${currentUser.id}&period_year=${curYear}`)
      .then((rows) => {
        const mvals: Record<string, string> = {};
        const wvals: Record<string, string> = {};
        rows.forEach((r) => {
          if (r.period_type === "monthly" && r.period_num === curMonth)
            mvals[r.kpi_type] = String(r.target_value);
          if (r.period_type === "weekly" && r.period_num === curWeek)
            wvals[r.kpi_type] = String(r.target_value);
        });
        setIndivMonthValues(mvals as Record<KpiType, string>);
        setIndivWeekValues(wvals as Record<KpiType, string>);
      })
      .catch(() => {});
  }, [currentUser, curYear, curMonth, curWeek]);

  useEffect(() => {
    if (!selectedTeamId) return;
    api
      .get<GoalResponse[]>(`/goals?team_id=${selectedTeamId}&period_year=${curYear}`)
      .then((rows) => {
        const mvals: Record<string, string> = {};
        const wvals: Record<string, string> = {};
        rows.forEach((r) => {
          if (r.period_type === "monthly" && r.period_num === curMonth)
            mvals[r.kpi_type] = String(r.target_value);
          if (r.period_type === "weekly" && r.period_num === curWeek)
            wvals[r.kpi_type] = String(r.target_value);
        });
        setTeamMonthValues(mvals as Record<KpiType, string>);
        setTeamWeekValues(wvals as Record<KpiType, string>);
      })
      .catch(() => {});
  }, [selectedTeamId, curYear, curMonth, curWeek]);

  async function saveGoals(
    kpis: KpiType[],
    values: Record<KpiType, string>,
    periodType: PeriodType,
    periodNum: number,
    ownerId: number,
    ownerType: "user" | "team",
    setSaving: (v: boolean) => void,
    setSaved: (s: Set<KpiType>) => void,
  ) {
    setSaving(true);
    try {
      const saved = new Set<KpiType>();
      for (const kpi of kpis) {
        const raw = values[kpi];
        if (!raw && raw !== "0") continue;
        const val = parseFloat(raw);
        if (Number.isNaN(val)) continue;
        await api.post("/goals", {
          [ownerType === "user" ? "user_id" : "team_id"]: ownerId,
          period_type: periodType,
          period_year: periodType === "monthly" ? curYear : weekYear,
          period_num: periodNum,
          kpi_type: kpi,
          target_value: val,
        });
        saved.add(kpi);
      }
      setSaved(saved);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const selectedTeam = teams.find((t) => t.id === selectedTeamId) ?? null;
  const canEditTeam = isLeader(currentUser, selectedTeam);

  if (loading) {
    return (
      <PageLayout navKey="nav.goalSettings">
        <div className="loading">{t("common.loading")}</div>
      </PageLayout>
    );
  }

  return (
    <PageLayout navKey="nav.goalSettings">
      {error && <div className="error-message">{error}</div>}

      {/* 戻るボタン */}
      <button
        className="gs-back-btn"
        onClick={() => navigate("/")}
      >
        ← {t("goals.backToDashboard")}
      </button>

      <div className="gs-layout">
        {/* ── 個人目標 ── */}
        <section className="gs-section">
          <h3 className="gs-section-title">{t("goals.individualTitle")}</h3>
          <GoalBlock
            title={t("goals.monthlyGoal", { month: curMonth })}
            kpis={INDIVIDUAL_KPIS}
            values={indivMonthValues}
            savedKeys={savedIndivMonth}
            onChange={(kpi, v) =>
              setIndivMonthValues((prev) => ({ ...prev, [kpi]: v }))
            }
            onSave={() =>
              saveGoals(
                INDIVIDUAL_KPIS,
                indivMonthValues,
                "monthly",
                curMonth,
                currentUser!.id,
                "user",
                setSavingIndivMonth,
                setSavedIndivMonth,
              )
            }
            saving={savingIndivMonth}
            t={t}
          />
          <GoalBlock
            title={t("goals.weeklyGoal", { week: curWeek })}
            kpis={INDIVIDUAL_KPIS}
            values={indivWeekValues}
            savedKeys={savedIndivWeek}
            onChange={(kpi, v) =>
              setIndivWeekValues((prev) => ({ ...prev, [kpi]: v }))
            }
            onSave={() =>
              saveGoals(
                INDIVIDUAL_KPIS,
                indivWeekValues,
                "weekly",
                curWeek,
                currentUser!.id,
                "user",
                setSavingIndivWeek,
                setSavedIndivWeek,
              )
            }
            saving={savingIndivWeek}
            t={t}
          />
        </section>

        {/* ── チーム目標（リーダー以上のみ） ── */}
        {teams.length > 0 && (
          <section className="gs-section">
            <h3 className="gs-section-title">{t("goals.teamTitle")}</h3>

            {/* チーム選択 */}
            <div className="gs-team-select-wrap">
              <label className="gs-label">{t("goals.selectTeam")}</label>
              <select
                className="gs-select"
                value={selectedTeamId ?? ""}
                onChange={(e) => setSelectedTeamId(Number(e.target.value))}
              >
                {teams.map((tm) => (
                  <option key={tm.id} value={tm.id}>
                    {tm.name}
                  </option>
                ))}
              </select>
            </div>

            {canEditTeam ? (
              <>
                <GoalBlock
                  title={t("goals.monthlyGoal", { month: curMonth })}
                  kpis={TEAM_KPIS}
                  values={teamMonthValues}
                  savedKeys={savedTeamMonth}
                  onChange={(kpi, v) =>
                    setTeamMonthValues((prev) => ({ ...prev, [kpi]: v }))
                  }
                  onSave={() =>
                    saveGoals(
                      TEAM_KPIS,
                      teamMonthValues,
                      "monthly",
                      curMonth,
                      selectedTeamId!,
                      "team",
                      setSavingTeamMonth,
                      setSavedTeamMonth,
                    )
                  }
                  saving={savingTeamMonth}
                  t={t}
                />
                <GoalBlock
                  title={t("goals.weeklyGoal", { week: curWeek })}
                  kpis={TEAM_KPIS}
                  values={teamWeekValues}
                  savedKeys={savedTeamWeek}
                  onChange={(kpi, v) =>
                    setTeamWeekValues((prev) => ({ ...prev, [kpi]: v }))
                  }
                  onSave={() =>
                    saveGoals(
                      TEAM_KPIS,
                      teamWeekValues,
                      "weekly",
                      curWeek,
                      selectedTeamId!,
                      "team",
                      setSavingTeamWeek,
                      setSavedTeamWeek,
                    )
                  }
                  saving={savingTeamWeek}
                  t={t}
                />
              </>
            ) : (
              <p className="gs-no-permission">{t("goals.noEditPermission")}</p>
            )}
          </section>
        )}
      </div>
    </PageLayout>
  );
}
