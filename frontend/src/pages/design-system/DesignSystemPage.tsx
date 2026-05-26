/**
 * ADR-069: デザインシステム パーツ保管庫
 * 開発環境専用（import.meta.env.DEV が true の時のみ App.tsx でルート登録）
 * アクセス: /design-system
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { PageLayout } from "../../components/PageLayout";
import "./DesignSystemPage.css";

/* ---- Color Section ---- */
const COLOR_TOKENS = [
  { name: "--accent",          label: "Accent (primary action)" },
  { name: "--accent-hover",    label: "Accent hover" },
  { name: "--bg-surface",      label: "Surface (card/panel)" },
  { name: "--bg-subtle",       label: "Subtle background" },
  { name: "--bg-hover",        label: "Hover background" },
  { name: "--bg-active",       label: "Active background" },
  { name: "--text-primary",    label: "Text primary" },
  { name: "--text-secondary",  label: "Text secondary" },
  { name: "--text-muted",      label: "Text muted" },
  { name: "--border",          label: "Border" },
  { name: "--success-bg",      label: "Success background" },
  { name: "--success-text",    label: "Success text" },
  { name: "--warning-bg",      label: "Warning background" },
  { name: "--warning-text",    label: "Warning text" },
  { name: "--danger-bg",       label: "Danger background" },
  { name: "--danger-text",     label: "Danger text" },
  { name: "--info-bg",         label: "Info background" },
];

function ColorsSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Color Tokens</h3>
      <div className="ds-color-grid">
        {COLOR_TOKENS.map((t) => (
          <div key={t.name} className="ds-color-swatch">
            <div className="ds-color-preview" style={{ background: `var(${t.name})` }} />
            <div className="ds-color-meta">
              <span className="ds-token-name">{t.name}</span>
              <span className="ds-token-label">{t.label}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Typography Section ---- */
const TYPE_ROLES = [
  { role: "Page title",    size: "--font-xl",   weight: "--font-weight-semi",   sample: "ページタイトル / Page Title" },
  { role: "Section title", size: "--font-lg",   weight: "--font-weight-semi",   sample: "セクション見出し / Section Heading" },
  { role: "Card title",    size: "--font-md",   weight: "--font-weight-semi",   sample: "カード内見出し / Card Title" },
  { role: "Body",          size: "--font-base", weight: "--font-weight-normal", sample: "本文テキスト / Body text copy" },
  { role: "Caption",       size: "--font-xs",   weight: "--font-weight-normal", sample: "補足ラベル / Caption & badge text" },
];

function TypographySection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Typography Roles</h3>
      <table className="ds-type-table">
        <thead>
          <tr>
            <th>Role</th>
            <th>Size token</th>
            <th>Weight</th>
            <th>Sample</th>
          </tr>
        </thead>
        <tbody>
          {TYPE_ROLES.map((r) => (
            <tr key={r.role}>
              <td className="ds-token-name">{r.role}</td>
              <td className="ds-token-name">{r.size}</td>
              <td className="ds-token-name">{r.weight}</td>
              <td style={{ fontSize: `var(${r.size})`, fontWeight: `var(${r.weight})` }}>{r.sample}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/* ---- Components Section ---- */
function ComponentsSection() {
  const [activeTab, setActiveTab] = useState("tab1");
  const [activePill, setActivePill] = useState("all");

  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Standard Components (ADR-069)</h3>
      <div className="ds-component-grid">

        {/* Tab Bar */}
        <div className="ds-component-block">
          <p className="ds-component-label">.tab-bar / .tab-item</p>
          <div className="tab-bar" style={{ borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
            {["tab1", "tab2", "tab3"].map((id) => (
              <button
                key={id}
                className={`tab-item${activeTab === id ? " active" : ""}`}
                onClick={() => setActiveTab(id)}
              >
                {id === "tab1" ? "すべて" : id === "tab2" ? "進行中" : "完了"}
              </button>
            ))}
          </div>
        </div>

        {/* Filter Pills */}
        <div className="ds-component-block">
          <p className="ds-component-label">.filter-pill</p>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {["all", "active", "pending", "done"].map((p) => (
              <button
                key={p}
                className={`filter-pill${activePill === p ? " active" : ""}`}
                onClick={() => setActivePill(p)}
              >
                {p === "all" ? "すべて" : p === "active" ? "アクティブ" : p === "pending" ? "保留中" : "完了"}
              </button>
            ))}
          </div>
        </div>

        {/* Buttons */}
        <div className="ds-component-block">
          <p className="ds-component-label">Buttons</p>
          <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn-primary">btn-primary</button>
            <button className="btn-secondary">btn-secondary</button>
            <button className="btn-sm">btn-sm</button>
            <button className="btn-sm btn-danger">btn-sm danger</button>
            <button className="icon-btn" aria-label="icon button">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
                <line x1="8" y1="5" x2="8" y2="8" stroke="currentColor" strokeWidth="1.5" />
                <circle cx="8" cy="11" r="0.75" fill="currentColor" />
              </svg>
            </button>
          </div>
        </div>

        {/* Badges */}
        <div className="ds-component-block">
          <p className="ds-component-label">Badges</p>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            <span className="badge badge-open">open</span>
            <span className="badge badge-negotiating">negotiating</span>
            <span className="badge badge-won">won</span>
            <span className="badge badge-lost">lost</span>
            <span className="status-badge status-active">active</span>
            <span className="status-badge status-inactive">inactive</span>
            <span className="status-badge status-pending_dedup_review">pending_dedup</span>
          </div>
        </div>

        {/* Panel Shell demo */}
        <div className="ds-component-block ds-component-block--wide">
          <p className="ds-component-label">.panel-shell / .panel-left / .panel-center</p>
          <div className="panel-shell" style={{ height: 'var(--ds-panel-size)', border: "1px solid var(--border)", borderRadius: "var(--radius-lg)", overflow: "hidden" }}>
            <div className="panel-left" style={{ width: 'var(--ds-panel-size)' }}>
              <div className="panel-header" style={{ minHeight: "auto", padding: "var(--space-2) var(--space-3)" }}>
                <span style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>Left panel</span>
              </div>
            </div>
            <div className="panel-center">
              <div className="panel-header" style={{ minHeight: "auto", padding: "var(--space-2) var(--space-3)" }}>
                <span style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>Center panel header</span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </section>
  );
}

/* ---- Main Page ---- */
export default function DesignSystemPage() {
  const { t } = useTranslation();

  return (
    <PageLayout
      navKey="nav.designSystem"
      headerAction={
        <span className="ds-dev-badge">{t("common.devOnly")}</span>
      }
    >
      <div className="ds-page">
        <ColorsSection />
        <TypographySection />
        <ComponentsSection />
      </div>
    </PageLayout>
  );
}
