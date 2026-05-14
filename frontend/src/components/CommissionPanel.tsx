/**
 * CommissionPanel — ADR-021 Phase 5 / Sprint 5: 担当者報酬パネル。
 *
 * 1 受注に紐づく 5 ロール（営業 / 受注 / 発送 / 仕入 / トラブル）の担当者割当 +
 * 再計算結果を 1 つのモーダルで操作する。
 *
 * 主要操作:
 *   - 各ロールの「担当者 select」変更 → POST /orders/{id}/commissions/assign で UPSERT
 *   - 「担当解除」ボタン → DELETE /orders/{id}/commissions/{role}
 *   - 「再計算」ボタン → POST /orders/{id}/commissions/recalc で全ロール再計算
 *
 * 親 (`OrdersPage`) は `orderId` を渡すだけ。`onClose` / `onSaved` で
 * 一覧側の合計報酬列を更新する。
 */

import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../lib/api";

const ROLES: { key: RoleKey; labelKey: string }[] = [
  { key: "sales", labelKey: "commissions.role_sales" },
  { key: "order", labelKey: "commissions.role_order" },
  { key: "ship", labelKey: "commissions.role_ship" },
  { key: "purchase", labelKey: "commissions.role_purchase" },
  { key: "trouble", labelKey: "commissions.role_trouble" },
];

export type RoleKey = "sales" | "order" | "ship" | "purchase" | "trouble";

export interface OrderCommissionDto {
  id: number;
  order_id: number;
  tenant_id: number;
  role: string;
  staff_id: number | null;
  staff_name: string | null;
  calculated_amount: number;
  calculated_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderCommissionsBundleDto {
  order_id: number;
  commissions: Record<string, OrderCommissionDto | null>;
}

interface StaffMini {
  id: number;
  surname_jp: string;
  given_name_jp: string;
  primary_email: string;
  is_employee?: boolean;
}

interface Props {
  orderId: number;
  orderNumber: string;
  onClose: () => void;
  onSaved?: (bundle: OrderCommissionsBundleDto) => void;
}

export default function CommissionPanel({
  orderId,
  orderNumber,
  onClose,
  onSaved,
}: Props) {
  const { t } = useTranslation();
  const [bundle, setBundle] = useState<OrderCommissionsBundleDto | null>(null);
  const [staffList, setStaffList] = useState<StaffMini[]>([]);
  const [loading, setLoading] = useState(true);
  const [recalcing, setRecalcing] = useState(false);
  const [savingRole, setSavingRole] = useState<RoleKey | null>(null);
  const [error, setError] = useState("");

  // 初回ロード: bundle + staff 一覧
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const [b, s] = await Promise.all([
          api.get<OrderCommissionsBundleDto>(
            `/orders/${orderId}/commissions`,
          ),
          api.get<StaffMini[]>("/staff?per_page=100"),
        ]);
        if (cancelled) return;
        setBundle(b);
        setStaffList(s);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : t("common.fetchError"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [orderId]);

  const staffOptions = useMemo(() => {
    return staffList.map((s) => ({
      value: s.id,
      label: `${s.surname_jp} ${s.given_name_jp}${s.is_employee ? t("commission.isEmployee") : ""}`,
    }));
  }, [staffList, t]);

  const handleAssign = async (role: RoleKey, staffId: number | null) => {
    setSavingRole(role);
    setError("");
    try {
      await api.post<OrderCommissionDto>(
        `/orders/${orderId}/commissions/assign`,
        { role, staff_id: staffId },
      );
      // bundle を再取得（recalc は別ボタンで明示）
      const b = await api.get<OrderCommissionsBundleDto>(
        `/orders/${orderId}/commissions`,
      );
      setBundle(b);
      onSaved?.(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    } finally {
      setSavingRole(null);
    }
  };

  const handleUnassign = async (role: RoleKey) => {
    setSavingRole(role);
    setError("");
    try {
      await api.delete(`/orders/${orderId}/commissions/${role}`);
      const b = await api.get<OrderCommissionsBundleDto>(
        `/orders/${orderId}/commissions`,
      );
      setBundle(b);
      onSaved?.(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    } finally {
      setSavingRole(null);
    }
  };

  const handleRecalc = async () => {
    setRecalcing(true);
    setError("");
    try {
      const b = await api.post<OrderCommissionsBundleDto>(
        `/orders/${orderId}/commissions/recalc`,
        {},
      );
      setBundle(b);
      onSaved?.(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    } finally {
      setRecalcing(false);
    }
  };

  const fmt = (n: number | string | null | undefined) => {
    if (n === null || n === undefined) return "-";
    const v = typeof n === "string" ? Number(n) : n;
    if (!Number.isFinite(v)) return "-";
    return v.toLocaleString("ja-JP", { style: "currency", currency: "JPY" });
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 760, maxHeight: "90vh", overflowY: "auto" }}
        role="dialog"
        aria-label={t("commission.assignedStaff")}
      >
        <h3>{t("commission.assignedStaff")} — {orderNumber}</h3>
        {loading ? (
          <div className="loading">{t("common.loading")}</div>
        ) : (
          <>
            {error && <div className="error-message">{error}</div>}
            <table className="data-table" data-testid="commission-table">
              <thead>
                <tr>
                  <th style={{ width: "20%" }}>{t("commissions.colRole")}</th>
                  <th style={{ width: "45%" }}>{t("commission.assignedStaff")}</th>
                  <th style={{ width: "20%" }}>{t("commission.calcResult")}</th>
                  <th style={{ width: "15%" }}>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {ROLES.map(({ key, labelKey }) => {
                  const label = t(labelKey);
                  const row = bundle?.commissions[key] ?? null;
                  const currentStaffId = row?.staff_id ?? null;
                  return (
                    <tr key={key} data-testid={`commission-row-${key}`}>
                      <td>{label}</td>
                      <td>
                        <select
                          aria-label={`${label}${t("commission.assignedStaff")}`}
                          data-testid={`commission-staff-${key}`}
                          value={currentStaffId !== null ? String(currentStaffId) : ""}
                          disabled={savingRole === key}
                          onChange={(e) => {
                            const v = e.target.value;
                            handleAssign(key, v === "" ? null : Number(v));
                          }}
                        >
                          <option value="">{t("commission.unassigned")}</option>
                          {staffOptions.map((opt) => (
                            <option key={opt.value} value={String(opt.value)}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td data-testid={`commission-amount-${key}`}>
                        {row ? fmt(row.calculated_amount) : "-"}
                      </td>
                      <td>
                        {row && row.staff_id !== null ? (
                          <button
                            className="btn-sm"
                            type="button"
                            data-testid={`commission-unassign-${key}`}
                            disabled={savingRole === key}
                            onClick={() => handleUnassign(key)}
                          >
                            {t("commission.unassignBtn")}
                          </button>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <div
              className="form-actions"
              style={{
                marginTop: "1rem",
                display: "flex",
                justifyContent: "space-between",
                gap: "0.5rem",
              }}
            >
              <button
                type="button"
                className="btn-primary"
                onClick={handleRecalc}
                disabled={recalcing}
                data-testid="commission-recalc"
              >
                {recalcing ? t("commission.recalculating") : t("commission.recalc")}
              </button>
              <button
                type="button"
                className="btn-secondary"
                onClick={onClose}
              >
                {t("common.close")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
