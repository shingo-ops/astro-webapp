/**
 * CommissionSettingsPage — ADR-021 Phase 5 / Sprint 5: 報酬設定ページ。
 *
 * テナント別の報酬計算 rate 設定（5 ロール × type/value）を編集する。
 *
 * 操作:
 *   - GET /tenant-commission-settings で初期表示（なければ default 作成）
 *   - PATCH /tenant-commission-settings で 5 ロールの type/value を一括保存
 *   - 月次レポート「現在月の報酬集計」をテキストで表示（GET /commissions/monthly）
 */

import { FormEvent, useEffect, useState } from "react";
import { api } from "../lib/api";

type RoleKey = "sales" | "order" | "ship" | "purchase" | "trouble";
type RateType = "rate" | "fixed";

interface RateConfig {
  type: RateType;
  value: number;
}

interface CommissionSettingsDto {
  id: number;
  tenant_id: number;
  commission_rates: Record<RoleKey, RateConfig>;
  created_at: string;
  updated_at: string;
}

interface MonthlyByStaff {
  staff_id: number | null;
  staff_name: string | null;
  total: number;
}

interface MonthlyByRole {
  role: string;
  total: number;
}

interface MonthlySummaryDto {
  year: number;
  month: number;
  by_staff: MonthlyByStaff[];
  by_role: MonthlyByRole[];
  total: number;
}

const ROLE_LABELS: Record<RoleKey, string> = {
  sales: "営業",
  order: "受注",
  ship: "発送",
  purchase: "仕入",
  trouble: "トラブル",
};

const ALL_ROLES: RoleKey[] = ["sales", "order", "ship", "purchase", "trouble"];

interface FormState {
  sales: RateConfig;
  order: RateConfig;
  ship: RateConfig;
  purchase: RateConfig;
  trouble: RateConfig;
}

const DEFAULT_FORM: FormState = {
  sales: { type: "rate", value: 0.1 },
  order: { type: "rate", value: 0.1 },
  ship: { type: "fixed", value: 200 },
  purchase: { type: "fixed", value: 100 },
  trouble: { type: "fixed", value: 500 },
};

export default function CommissionSettingsPage() {
  const [settings, setSettings] = useState<CommissionSettingsDto | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [monthly, setMonthly] = useState<MonthlySummaryDto | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  // ADR-021 J2 fix (2026-05-13): 月選択の初期値は JST 業務日基準。
  // ブラウザのロケール TZ に依らず、常に JST の現在年月を表示する。
  // toLocaleString で TZ 指定の壁時計を取り、Date でパースし直す方式。
  const nowJst = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Tokyo" }),
  );
  const [year, setYear] = useState(nowJst.getFullYear());
  const [month, setMonth] = useState(nowJst.getMonth() + 1);

  const dtoToForm = (dto: CommissionSettingsDto): FormState => {
    const r = dto.commission_rates;
    const out: FormState = { ...DEFAULT_FORM };
    for (const role of ALL_ROLES) {
      const cfg = r[role];
      if (cfg) {
        out[role] = { type: cfg.type, value: Number(cfg.value) };
      }
    }
    return out;
  };

  const loadSettings = async () => {
    setLoading(true);
    setError("");
    try {
      const dto = await api.get<CommissionSettingsDto>(
        "/tenant-commission-settings",
      );
      setSettings(dto);
      setForm(dtoToForm(dto));
    } catch (e) {
      setError(e instanceof Error ? e.message : "報酬設定の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadMonthly = async (y: number, m: number) => {
    try {
      const dto = await api.get<MonthlySummaryDto>(
        `/commissions/monthly?year=${y}&month=${m}`,
      );
      setMonthly(dto);
    } catch {
      // 取得失敗は致命的でないので静かに無視
      setMonthly(null);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);
  useEffect(() => {
    loadMonthly(year, month);
  }, [year, month]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setInfo("");
    setSaving(true);
    try {
      const payload = { commission_rates: form };
      const updated = await api.patch<CommissionSettingsDto>(
        "/tenant-commission-settings",
        payload,
      );
      setSettings(updated);
      setForm(dtoToForm(updated));
      setInfo("保存しました");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存に失敗しました");
    } finally {
      setSaving(false);
    }
  };

  const updateRole = (role: RoleKey, patch: Partial<RateConfig>) => {
    setForm((prev) => ({ ...prev, [role]: { ...prev[role], ...patch } }));
  };

  const fmt = (n: number) =>
    n.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });

  return (
    <div className="page">
      <div className="page-header">
        <h2>報酬設定</h2>
      </div>

      {loading ? (
        <div className="loading">読み込み中...</div>
      ) : (
        <>
          {error && <div className="error-message">{error}</div>}
          {info && (
            <div className="info-message" style={{ color: "var(--success, #2e7d32)" }}>
              {info}
            </div>
          )}

          <form onSubmit={handleSubmit} data-testid="commission-settings-form">
            <fieldset>
              <legend>5 ロールの計算 rate</legend>
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: "20%" }}>ロール</th>
                    <th style={{ width: "30%" }}>計算タイプ</th>
                    <th style={{ width: "30%" }}>値</th>
                    <th>備考</th>
                  </tr>
                </thead>
                <tbody>
                  {ALL_ROLES.map((role) => {
                    const cfg = form[role];
                    return (
                      <tr key={role} data-testid={`settings-row-${role}`}>
                        <td>{ROLE_LABELS[role]}</td>
                        <td>
                          <select
                            value={cfg.type}
                            onChange={(e) =>
                              updateRole(role, { type: e.target.value as RateType })
                            }
                            aria-label={`${ROLE_LABELS[role]} 計算タイプ`}
                            data-testid={`settings-type-${role}`}
                          >
                            <option value="rate">売上 × rate</option>
                            <option value="fixed">固定額</option>
                          </select>
                        </td>
                        <td>
                          <input
                            type="number"
                            min={0}
                            step={cfg.type === "rate" ? 0.01 : 1}
                            value={cfg.value}
                            onChange={(e) =>
                              updateRole(role, { value: Number(e.target.value) })
                            }
                            aria-label={`${ROLE_LABELS[role]} 値`}
                            data-testid={`settings-value-${role}`}
                          />
                        </td>
                        <td>
                          {cfg.type === "rate"
                            ? `売上 × ${(cfg.value * 100).toFixed(1)}%`
                            : `${fmt(cfg.value)} 固定`}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </fieldset>

            <div
              className="form-actions"
              style={{
                marginTop: "1rem",
                display: "flex",
                justifyContent: "flex-end",
                gap: "0.5rem",
              }}
            >
              <button
                type="submit"
                className="btn-primary"
                disabled={saving}
                data-testid="settings-save"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
            {settings && (
              <p className="text-muted" style={{ fontSize: "0.85rem" }}>
                最終更新: {new Date(settings.updated_at).toLocaleString("ja-JP")}
              </p>
            )}
          </form>

          {/* 月次レポート（テキスト表示） */}
          <fieldset style={{ marginTop: "2rem" }}>
            <legend>月次集計</legend>
            <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <label>
                年:
                <input
                  type="number"
                  value={year}
                  min={2000}
                  max={2999}
                  onChange={(e) => setYear(Number(e.target.value))}
                  style={{ width: 90, marginLeft: 8 }}
                  data-testid="monthly-year"
                />
              </label>
              <label>
                月:
                <input
                  type="number"
                  value={month}
                  min={1}
                  max={12}
                  onChange={(e) => setMonth(Number(e.target.value))}
                  style={{ width: 60, marginLeft: 8 }}
                  data-testid="monthly-month"
                />
              </label>
            </div>

            {monthly ? (
              <div style={{ marginTop: "1rem" }}>
                <p data-testid="monthly-total">
                  合計: <strong>{fmt(monthly.total)}</strong>
                </p>
                <h4>担当者別</h4>
                <ul data-testid="monthly-by-staff">
                  {monthly.by_staff.length === 0 && <li className="text-muted">該当データなし</li>}
                  {monthly.by_staff.map((it) => (
                    <li key={`${it.staff_id ?? "null"}`}>
                      {it.staff_name ?? "（未割当）"}: {fmt(it.total)}
                    </li>
                  ))}
                </ul>
                <h4>ロール別</h4>
                <ul data-testid="monthly-by-role">
                  {monthly.by_role.length === 0 && <li className="text-muted">該当データなし</li>}
                  {monthly.by_role.map((it) => (
                    <li key={it.role}>
                      {ROLE_LABELS[it.role as RoleKey] ?? it.role}: {fmt(it.total)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-muted" style={{ marginTop: "1rem" }}>
                月次集計を取得できませんでした
              </p>
            )}
          </fieldset>
        </>
      )}
    </div>
  );
}
