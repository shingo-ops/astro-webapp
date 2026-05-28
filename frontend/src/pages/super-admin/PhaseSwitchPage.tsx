/**
 * /super-admin/phase-switch — スプレッドシート並走 Phase 表示・切替画面 (Sprint 9 / F9 v1.3)。
 *
 * spec.md v1.3 F9 / AC9.3 / AC9.5:
 *   - is_super_admin=true のみアクセス可（false なら 403 メッセージ + 二重ガード）
 *   - 現在 Phase（A / B / C）を表示
 *   - v1.3 では 'B' 標準運用、'A' (緊急戻し) も技術的に許可、'C' ボタンのみ
 *     disabled + ツールチップで「別 ADR で検討中（spec v1.3）」を表示
 *   - 'A' / 'B' クリックは冪等な再設定（audit_log のみ記録）
 *
 * 設計判断:
 *   - 単一テナント運用 + 中央 admin の前提なので、URL パラメータでテナント ID を
 *     受け取らず、useMe で現ユーザの tenant_id を解決する経路を採用する。
 *     現状 useSuperAdmin だけでは tenant_id を返さないので、別途
 *     /api/v1/me を fetch する。
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../../lib/api";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
import { PageLayout } from "../../components/PageLayout";

type Phase = "A" | "B" | "C";

interface PhaseResponse {
  tenant_id: number;
  phase: Phase;
  allowed_phases: Phase[];
  scoped_phases: Phase[];
}

interface MePermissionsResponse {
  permissions: string[];
  is_super_admin: boolean;
  tenant_id: number;
}

export default function PhaseSwitchPage() {
  const { t } = useTranslation();
  const { isSuperAdmin, loading: superAdminLoading } = useSuperAdmin();

  const [tenantId, setTenantId] = useState<number | null>(null);
  const [data, setData] = useState<PhaseResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");

  const load = useCallback(async (tid: number) => {
    setError("");
    setLoading(true);
    try {
      const d = await api.get<PhaseResponse>(
        `/super-admin/phase-switch/${tid}`,
      );
      setData(d);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  // 中央 admin の自テナント ID を /me/permissions から取得 (Sprint 9 で tenant_id を追加)
  useEffect(() => {
    if (!isSuperAdmin) return;
    (async () => {
      try {
        const me = await api.get<MePermissionsResponse>("/me/permissions");
        if (me.tenant_id) {
          setTenantId(me.tenant_id);
          await load(me.tenant_id);
        } else {
          setError(t("superAdmin.phaseSwitch.tenantIdMissing"));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : t("common.fetchError"));
      }
    })();
  }, [isSuperAdmin, load, t]);

  const handleSwitch = async (newPhase: Phase) => {
    if (!tenantId || !data) return;
    if (!data.scoped_phases.includes(newPhase)) {
      // フロント側ガード（バックも 400 を返すが UX 上ここで止める）
      setError(t("superAdmin.phaseSwitch.outOfScope", { phase: newPhase }));
      return;
    }
    setError("");
    setInfo("");
    setSubmitting(true);
    try {
      const resp = await api.put<PhaseResponse>(
        `/super-admin/phase-switch/${tenantId}`,
        { phase: newPhase },
      );
      setData(resp);
      setInfo(t("superAdmin.phaseSwitch.switchSuccess", { phase: newPhase }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        setError(t("superAdmin.phaseSwitch.outOfScope", { phase: newPhase }));
      } else {
        setError(e instanceof Error ? e.message : t("common.operationError"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const isScoped = useCallback(
    (p: Phase) => data?.scoped_phases.includes(p) ?? false,
    [data],
  );

  if (superAdminLoading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!isSuperAdmin) {
    return (
      <PageLayout navKey="nav.superAdminPhaseSwitch">
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout navKey="nav.superAdminPhaseSwitch" subtitleKey="superAdmin.phaseSwitch.subtitle">

      {/* spec v1.3: Phase A は緊急戻し状態のみ。Phase A 時のみ警告バナー表示 */}
      {data?.phase === "A" && (
        <div
          className="info-banner"
          role="status"
          data-testid="phase-a-banner"
          style={{
            backgroundColor: "var(--warning-bg)",
            color: "var(--warning-text)",
            border: "1px solid var(--border-strong)",
            padding: "0.75rem 1rem",
            borderRadius: "var(--radius-sm)",
            marginBottom: "var(--space-4)",
          }}
        >
          {t("superAdmin.phaseSwitch.phaseABanner")}
        </div>
      )}

      {error && (
        <div className="error-message" role="alert" data-testid="phase-switch-error">
          {error}
        </div>
      )}
      {info && (
        <div className="info-message" role="status" data-testid="phase-switch-info">
          {info}
        </div>
      )}

      {loading && <div>{t("common.loading")}</div>}

      {data && (
        <>
          <div className="phase-current" style={{ marginBottom: "var(--space-6)" }}>
            <strong>{t("superAdmin.phaseSwitch.currentLabel")}: </strong>
            <span data-testid="current-phase" style={{ fontSize: "var(--font-2xl)" }}>
              Phase {data.phase}
            </span>
            {data.phase === "A" && (
              <span style={{ marginLeft: "var(--space-2)", color: "var(--warning-text)" }}>
                ({t("superAdmin.phaseSwitch.phaseADesc")})
              </span>
            )}
            {data.phase === "B" && (
              <span style={{ marginLeft: "var(--space-2)", color: "var(--text-muted)" }}>
                ({t("superAdmin.phaseSwitch.phaseBDesc")})
              </span>
            )}
          </div>

          <div className="phase-buttons" style={{ display: "flex", gap: "var(--space-2)" }}>
            {(["A", "B", "C"] as Phase[]).map((p) => {
              const scoped = isScoped(p);
              const current = data.phase === p;
              return (
                <button
                  key={p}
                  type="button"
                  disabled={!scoped || submitting || current}
                  onClick={() => handleSwitch(p)}
                  title={
                    !scoped
                      ? t("superAdmin.phaseSwitch.outOfScopeTooltip")
                      : current
                        ? t("superAdmin.phaseSwitch.currentTooltip")
                        : t("superAdmin.phaseSwitch.switchTo", { phase: p })
                  }
                  data-testid={`phase-btn-${p}`}
                  data-scoped={scoped ? "true" : "false"}
                  data-current={current ? "true" : "false"}
                >
                  Phase {p}
                  {!scoped && (
                    <span style={{ marginLeft: "var(--space-1)", fontSize: "var(--font-xs)" }}>
                      ({t("superAdmin.phaseSwitch.outOfScopeBadge")})
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          <div className="phase-help" style={{ marginTop: "var(--space-6)", fontSize: "var(--font-sm)" }}>
            <ul>
              <li>{t("superAdmin.phaseSwitch.helpPhaseA")}</li>
              <li>{t("superAdmin.phaseSwitch.helpPhaseB")}</li>
              <li>{t("superAdmin.phaseSwitch.helpPhaseC")}</li>
            </ul>
          </div>
        </>
      )}
    </PageLayout>
  );
}
