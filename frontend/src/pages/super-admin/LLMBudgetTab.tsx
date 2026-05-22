/**
 * /super-admin/masters — LLM 予算管理タブ（5 番目のタブ）。
 *
 * spec.md v1.1 F4 (Sprint 4) / AC4.6:
 *   - public.tenant_llm_budgets の一覧 + 編集
 *   - 各 tenant の monthly_budget_usd / current_month_usd / hard_stop / notify_admin
 *   - Jarvis 運用 admin（is_super_admin=true）のみ操作可（API 側で require_super_admin）
 *   - テナント admin は MastersPage 側で 403 ガード
 *
 * 変更履歴:
 *   2026-05-22: 初版（Sprint 4）
 */
import { useCallback, useEffect, useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";

interface LLMBudget {
  tenant_id: number;
  tenant_code: string | null;
  tenant_name: string | null;
  monthly_budget_usd: string; // pydantic Decimal は JSON で文字列化
  current_month_usd: string;
  last_reset_at: string;
  hard_stop: boolean;
  notify_admin: boolean;
  created_at: string | null;
  updated_at: string | null;
}

interface EditState {
  tenant_id: number;
  monthly_budget_usd: string;
  hard_stop: boolean;
  notify_admin: boolean;
}

export default function LLMBudgetTab() {
  const { t } = useTranslation();
  const [items, setItems] = useState<LLMBudget[]>([]);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await api.get<LLMBudget[]>("/super-admin/llm-budget");
      setItems(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const formatUsd = (s: string): string => {
    const n = Number.parseFloat(s);
    if (Number.isNaN(n)) return s;
    return `$${n.toFixed(4)}`;
  };

  const utilizationPercent = (b: LLMBudget): number => {
    const budget = Number.parseFloat(b.monthly_budget_usd);
    const used = Number.parseFloat(b.current_month_usd);
    if (budget <= 0) return used > 0 ? 100 : 0;
    return Math.min(100, Math.max(0, (used / budget) * 100));
  };

  const startEdit = (b: LLMBudget) => {
    setEdit({
      tenant_id: b.tenant_id,
      monthly_budget_usd: b.monthly_budget_usd,
      hard_stop: b.hard_stop,
      notify_admin: b.notify_admin,
    });
    setInfo("");
    setError("");
  };

  const cancelEdit = () => setEdit(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!edit) return;
    setError("");
    try {
      await api.put<LLMBudget>(
        `/super-admin/llm-budget/${edit.tenant_id}`,
        {
          monthly_budget_usd: edit.monthly_budget_usd,
          hard_stop: edit.hard_stop,
          notify_admin: edit.notify_admin,
        },
      );
      setInfo(t("superAdmin.llmBudget.savedNotice"));
      setEdit(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    }
  };

  return (
    <div className="super-admin-llm-budget-tab" data-testid="super-admin-llm-budget-tab">
      <h3>{t("superAdmin.llmBudget.title")}</h3>
      <p className="page-subtitle">{t("superAdmin.llmBudget.subtitle")}</p>

      {error && (
        <div className="error-message" role="alert" data-testid="llm-budget-error">
          {error}
        </div>
      )}
      {info && (
        <div className="success-message" role="status" data-testid="llm-budget-info">
          {info}
        </div>
      )}

      <table className="data-table" style={{ width: "100%", marginTop: "var(--space-4)" }}>
        <thead>
          <tr>
            <th>{t("superAdmin.llmBudget.fields.tenantId")}</th>
            <th>{t("superAdmin.llmBudget.fields.tenantName")}</th>
            <th>{t("superAdmin.llmBudget.fields.monthlyBudget")}</th>
            <th>{t("superAdmin.llmBudget.fields.currentMonth")}</th>
            <th>{t("superAdmin.llmBudget.fields.utilization")}</th>
            <th>{t("superAdmin.llmBudget.fields.hardStop")}</th>
            <th>{t("superAdmin.llmBudget.fields.notifyAdmin")}</th>
            <th>{t("superAdmin.llmBudget.fields.lastResetAt")}</th>
            <th>{t("common.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((b) => (
            <tr key={b.tenant_id} data-testid={`llm-budget-row-${b.tenant_id}`}>
              <td>{b.tenant_id}</td>
              <td>{b.tenant_name || b.tenant_code || "-"}</td>
              <td>${Number.parseFloat(b.monthly_budget_usd).toFixed(2)}</td>
              <td data-testid={`llm-budget-used-${b.tenant_id}`}>
                {formatUsd(b.current_month_usd)}
              </td>
              <td>{utilizationPercent(b).toFixed(1)}%</td>
              <td>{b.hard_stop ? "ON" : "OFF"}</td>
              <td>{b.notify_admin ? "ON" : "OFF"}</td>
              <td style={{ fontSize: "var(--font-sm)" }}>{b.last_reset_at.split("T")[0]}</td>
              <td>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => startEdit(b)}
                  data-testid={`llm-budget-edit-${b.tenant_id}`}
                >
                  {t("common.edit")}
                </button>
              </td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr>
              <td colSpan={9} style={{ textAlign: "center", padding: "var(--space-4)" }}>
                {t("superAdmin.llmBudget.noRows")}
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {edit && (
        <form
          onSubmit={submit}
          style={{
            border: "1px solid var(--border-color)",
            padding: "var(--space-4)",
            marginTop: "var(--space-4)",
            borderRadius: "var(--radius-sm)",
          }}
          data-testid="llm-budget-edit-form"
        >
          <h4>
            {t("superAdmin.llmBudget.editTitle", { tenant_id: edit.tenant_id })}
          </h4>
          <div style={{ marginBottom: "var(--space-2)" }}>
            <label>
              {t("superAdmin.llmBudget.fields.monthlyBudget")}:{" "}
              <input
                type="number"
                step="0.01"
                min="0"
                value={edit.monthly_budget_usd}
                onChange={(e) =>
                  setEdit({ ...edit, monthly_budget_usd: e.target.value })
                }
                data-testid="llm-budget-input-monthly-budget"
                required
              />
            </label>
          </div>
          <div style={{ marginBottom: "var(--space-2)" }}>
            <label>
              <input
                type="checkbox"
                checked={edit.hard_stop}
                onChange={(e) =>
                  setEdit({ ...edit, hard_stop: e.target.checked })
                }
                data-testid="llm-budget-input-hard-stop"
              />
              {t("superAdmin.llmBudget.fields.hardStop")}
            </label>
          </div>
          <div style={{ marginBottom: "var(--space-2)" }}>
            <label>
              <input
                type="checkbox"
                checked={edit.notify_admin}
                onChange={(e) =>
                  setEdit({ ...edit, notify_admin: e.target.checked })
                }
                data-testid="llm-budget-input-notify-admin"
              />
              {t("superAdmin.llmBudget.fields.notifyAdmin")}
            </label>
          </div>
          <div>
            <button
              type="submit"
              className="btn-primary"
              data-testid="llm-budget-save"
            >
              {t("common.save")}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={cancelEdit}
              style={{ marginLeft: "var(--space-2)" }}
              data-testid="llm-budget-cancel"
            >
              {t("common.cancel")}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
