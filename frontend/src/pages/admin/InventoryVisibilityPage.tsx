/**
 * /admin/inventory-visibility — テナント admin 向け在庫表示権限マトリクス UI。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.8 / AC7.9:
 *   - 自テナント内のロール × inventory.visibility.{full,staff,viewer} の ON/OFF
 *   - tenant.inventory_visibility.edit 権限が必要
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { usePermissions } from "../../hooks/usePermissions";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import { usePageTitle } from "../../hooks/usePageTitle";

interface MatrixRow {
  role_id: number;
  role_name: string;
  permission_key: string;
  is_granted: boolean;
}

interface MatrixResponse {
  visibility_keys: string[];
  rows: MatrixRow[];
}

interface RoleVisibility {
  role_id: number;
  role_name: string;
  // key -> is_granted
  grants: Record<string, boolean>;
}

export default function InventoryVisibilityPage() {
  const { t } = useTranslation();
  const { hasPermission, loading: permsLoading } = usePermissions();
  const title = usePageTitle();
  const [matrix, setMatrix] = useState<RoleVisibility[]>([]);
  const [keys, setKeys] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingFor, setSavingFor] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [savedFor, setSavedFor] = useState<number | null>(null);

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await api.get<MatrixResponse>(
        "/admin/inventory-visibility/matrix",
      );
      setKeys(data.visibility_keys);
      const byRole = new Map<number, RoleVisibility>();
      for (const r of data.rows) {
        if (!byRole.has(r.role_id)) {
          byRole.set(r.role_id, {
            role_id: r.role_id,
            role_name: r.role_name,
            grants: {},
          });
        }
        byRole.get(r.role_id)!.grants[r.permission_key] = r.is_granted;
      }
      setMatrix(Array.from(byRole.values()));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!permsLoading) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permsLoading]);

  const toggle = (roleId: number, key: string) => {
    setMatrix((prev) =>
      prev.map((r) =>
        r.role_id === roleId
          ? { ...r, grants: { ...r.grants, [key]: !r.grants[key] } }
          : r,
      ),
    );
  };

  const saveRole = async (row: RoleVisibility) => {
    setSavingFor(row.role_id);
    setError("");
    setSavedFor(null);
    try {
      const visibility_keys = Object.entries(row.grants)
        .filter(([, on]) => on)
        .map(([k]) => k);
      await api.put(`/admin/inventory-visibility/roles/${row.role_id}`, {
        role_id: row.role_id,
        visibility_keys,
      });
      setSavedFor(row.role_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.saveError"));
    } finally {
      setSavingFor(null);
    }
  };

  if (permsLoading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!hasPermission("tenant.inventory_visibility.edit")) {
    return (
      <div className="page">
        <div className="page-header">
          <h2>{title}</h2>
        </div>
        <div className="error-message" role="alert">
          {t("inventoryVisibility.permissionRequired")}
        </div>
      </div>
    );
  }

  return (
    <div className="page inventory-visibility-page">
      <div className="page-header">
        <h2>{title}</h2>
        <p className="page-subtitle">{t("inventoryVisibility.subtitle")}</p>
      </div>
      {error && <div className="error-message">{error}</div>}
      {loading ? (
        <div>{t("inventoryVisibility.loadingMatrix")}</div>
      ) : matrix.length === 0 ? (
        <div>{t("inventoryVisibility.noRoles")}</div>
      ) : (
        <table className="data-table" data-testid="visibility-matrix">
          <thead>
            <tr>
              <th>{t("inventoryVisibility.roleColumn")}</th>
              {keys.map((k) => {
                // i18next は dot を nested key として扱うため、
                // "inventory.visibility.full" → "full" の末尾セグメントを使う
                const shortKey = k.split(".").pop() || k;
                return <th key={k}>{t(`inventoryVisibility.keys.${shortKey}`, k)}</th>;
              })}
              <th>{t("inventoryVisibility.save")}</th>
            </tr>
          </thead>
          <tbody>
            {matrix.map((row) => (
              <tr key={row.role_id}>
                <td>{row.role_name}</td>
                {keys.map((k) => (
                  <td key={k}>
                    <input
                      type="checkbox"
                      checked={Boolean(row.grants[k])}
                      onChange={() => toggle(row.role_id, k)}
                      aria-label={`${row.role_name} ${k}`}
                      data-testid={`vis-${row.role_id}-${k}`}
                    />
                  </td>
                ))}
                <td>
                  <button
                    onClick={() => saveRole(row)}
                    className="btn-primary"
                    disabled={savingFor === row.role_id}
                  >
                    {savingFor === row.role_id
                      ? t("common.saving")
                      : t("inventoryVisibility.save")}
                  </button>
                  {savedFor === row.role_id && (
                    <span style={{ marginLeft: "var(--space-2)", color: "var(--success)" }}>
                      <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" />{" "}{t("inventoryVisibility.saved")}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
