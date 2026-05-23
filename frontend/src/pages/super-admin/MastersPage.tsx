/**
 * /super-admin/masters — 中央 admin マスタ編集タブコンテナ。
 *
 * spec.md v1.1 F2 (Sprint 2) / AC2.1 / F4 (Sprint 4) AC4.6:
 *   - is_super_admin=true のみアクセス可（false なら 403 メッセージを表示し、
 *     サイドバーからの誤導線もない、二重ガード）
 *   - 5 タブ: Knowledge / TCG / Dex / Suppliers / LLM Budget
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2、4 タブ）
 *   2026-05-22: Sprint 4 で LLM Budget タブ追加（5 タブ）
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
import KnowledgeAliasesTab from "./KnowledgeAliasesTab";
import TcgSeriesTab from "./TcgSeriesTab";
import DexTab from "./DexTab";
import SuppliersAdminTab from "./SuppliersAdminTab";
import LLMBudgetTab from "./LLMBudgetTab";

type TabKey = "knowledge" | "tcg" | "dex" | "suppliers" | "llmBudget";

export default function MastersPage() {
  const { t } = useTranslation();
  const { isSuperAdmin, loading } = useSuperAdmin();
  const [tab, setTab] = useState<TabKey>("knowledge");

  if (loading) {
    return <div className="page">{t("common.loading")}</div>;
  }

  if (!isSuperAdmin) {
    return (
      <div className="page">
        <div className="page-header">
          <h2>{t("superAdmin.title")}</h2>
        </div>
        <div className="error-message" role="alert">
          {t("superAdmin.accessDenied")}
        </div>
      </div>
    );
  }

  const tabs: { key: TabKey; label: string }[] = [
    { key: "knowledge", label: t("superAdmin.tabs.knowledge") },
    { key: "tcg", label: t("superAdmin.tabs.tcg") },
    { key: "dex", label: t("superAdmin.tabs.dex") },
    { key: "suppliers", label: t("superAdmin.tabs.suppliers") },
    { key: "llmBudget", label: t("superAdmin.tabs.llmBudget") },
  ];

  return (
    <div className="page super-admin-masters-page">
      <div className="page-header">
        <h2>{t("superAdmin.title")}</h2>
        <p className="page-subtitle">{t("superAdmin.subtitle")}</p>
      </div>
      <div
        className="super-admin-tabs"
        role="tablist"
        aria-label="super-admin master tabs"
        style={{ display: "flex", gap: "var(--space-2)", margin: "1rem 0", borderBottom: "1px solid var(--border-light)" }}
      >
        {tabs.map((tt) => (
          <button
            key={tt.key}
            role="tab"
            aria-selected={tab === tt.key}
            className={tab === tt.key ? "btn-primary" : "btn-secondary"}
            onClick={() => setTab(tt.key)}
            style={{ padding: "var(--space-2) var(--space-4)" }}
            data-testid={`super-admin-tab-${tt.key}`}
          >
            {tt.label}
          </button>
        ))}
      </div>
      <div className="super-admin-tab-content" role="tabpanel">
        {tab === "knowledge" && <KnowledgeAliasesTab />}
        {tab === "tcg" && <TcgSeriesTab />}
        {tab === "dex" && <DexTab />}
        {tab === "suppliers" && <SuppliersAdminTab />}
        {tab === "llmBudget" && <LLMBudgetTab />}
      </div>
    </div>
  );
}
