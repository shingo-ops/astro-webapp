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
  { name: "--info-text",       label: "Info text" },
  { name: "--bg-primary",      label: "Page background" },
  { name: "--bg-disabled",     label: "Disabled background" },
  { name: "--bg-badge",        label: "Badge background" },
  { name: "--border-strong",   label: "Border strong" },
  { name: "--border-icon",     label: "Border icon frame" },
  { name: "--border-color",    label: "Border generic" },
  { name: "--border-light",    label: "Border light" },
  { name: "--danger",          label: "Danger base" },
  { name: "--danger-bg-subtle",   label: "Danger subtle background" },
  { name: "--accent-bg",          label: "Accent alt background" },
  { name: "--accent-bg-subtle",   label: "Accent subtle background" },
  { name: "--warning-bg-subtle",  label: "Warning subtle background" },
  { name: "--success",            label: "Success base" },
  { name: "--success-bg-subtle",  label: "Success subtle background" },
  // Inbox semantic tokens
  { name: "--inbox-separator",         label: "Inbox separator" },
  { name: "--inbox-hover",             label: "Inbox item hover" },
  { name: "--inbox-action-icon-color", label: "Inbox action icon" },
  { name: "--inbox-bulk-icon-color",   label: "Inbox bulk icon" },
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

/* ---- Spacing Section ---- */
const SPACE_TOKENS = [
  { name: "--space-1",  px: "4px" },
  { name: "--space-2",  px: "8px" },
  { name: "--space-3",  px: "12px" },
  { name: "--space-4",  px: "16px" },
  { name: "--space-5",  px: "20px" },
  { name: "--space-6",  px: "24px" },
  { name: "--space-8",  px: "32px" },
  { name: "--space-10", px: "40px" },
  { name: "--space-12", px: "48px" },
];

function SpacingSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Spacing Tokens</h3>
      <div className="ds-spacing-list">
        {SPACE_TOKENS.map((tok) => (
          <div key={tok.name} className="ds-spacing-row">
            <span className="ds-token-name ds-spacing-label-name">{tok.name}</span>
            <div className="ds-spacing-bar-wrap">
              <div className="ds-spacing-bar" style={{ width: `var(${tok.name})` }} />
            </div>
            <span className="ds-token-label ds-spacing-label-px">{tok.px}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Shadow Section ---- */
const SHADOW_TOKENS = [
  { name: "--shadow-xs",           label: "xs" },
  { name: "--shadow-sm",           label: "sm (card)" },
  { name: "--shadow-md",           label: "md (dropdown)" },
  { name: "--shadow-lg",           label: "lg (floating)" },
  { name: "--shadow-xl",           label: "xl (popover)" },
  { name: "--shadow-modal",        label: "modal" },
  { name: "--shadow-dropdown",     label: "dropdown" },
  { name: "--shadow-drop-sm",      label: "drop-sm" },
  { name: "--shadow-accent-hover", label: "accent-hover" },
];

function ShadowSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Shadow Tokens</h3>
      <div className="ds-shadow-grid">
        {SHADOW_TOKENS.map((tok) => (
          <div key={tok.name} className="ds-shadow-card" style={{ boxShadow: `var(${tok.name})` }}>
            <span className="ds-token-name">{tok.name}</span>
            <span className="ds-token-label">{tok.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Radius Section ---- */
const RADIUS_TOKENS = [
  { name: "--radius-xs",    label: "2px" },
  { name: "--radius-2xs",   label: "3px" },
  { name: "--radius-sm",    label: "4px" },
  { name: "--radius-md",    label: "6px" },
  { name: "--radius-lg",    label: "8px" },
  { name: "--radius-xl",    label: "12px" },
  { name: "--radius-badge", label: "10px (badge)" },
  { name: "--radius-pill",  label: "20px (pill)" },
  { name: "--radius-full",  label: "9999px" },
];

function RadiusSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Border Radius Tokens</h3>
      <div className="ds-radius-row">
        {RADIUS_TOKENS.map((tok) => (
          <div key={tok.name} className="ds-radius-item">
            <div className="ds-radius-box" style={{ borderRadius: `var(${tok.name})` }} />
            <span className="ds-token-name">{tok.name}</span>
            <span className="ds-token-label">{tok.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ---- Z-index Section ---- */
const Z_TOKENS = [
  { name: "--z-base",            value: "10",  label: "base content" },
  { name: "--z-dropdown",        value: "50",  label: "dropdown" },
  { name: "--z-topbar",          value: "100", label: "topbar" },
  { name: "--z-sidebar",         value: "200", label: "sidebar" },
  { name: "--z-sidebar-overlay", value: "210", label: "sidebar overlay" },
  { name: "--z-backdrop",        value: "298", label: "backdrop" },
  { name: "--z-drawer",          value: "299", label: "drawer" },
  { name: "--z-avatar",          value: "300", label: "avatar button" },
  { name: "--z-modal",           value: "400", label: "modal" },
  { name: "--z-toast",           value: "500", label: "toast" },
];

function ZIndexSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Z-Index Tokens</h3>
      <table className="ds-type-table">
        <thead>
          <tr>
            <th>Token</th>
            <th>Value</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {Z_TOKENS.map((tok) => (
            <tr key={tok.name}>
              <td className="ds-token-name">{tok.name}</td>
              <td className="ds-token-label">{tok.value}</td>
              <td style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)" }}>{tok.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

/* ---- Motion Section ---- */
const TRANSITION_TOKENS = [
  { name: "--transition-micro",   label: "100ms ease — button press" },
  { name: "--transition-fast",    label: "150ms ease — hover / color" },
  { name: "--transition-base",    label: "200ms ease — fade in/out" },
  { name: "--transition-sidebar", label: "250ms ease — sidebar" },
  { name: "--transition-slow",    label: "280ms cubic-bezier — drawer" },
];

const EASING_TOKENS = [
  { name: "--ease-standard", label: "standard (Material/Meta)" },
  { name: "--ease-enter",    label: "enter — element entering" },
  { name: "--ease-exit",     label: "exit — element leaving" },
];

function MotionSection() {
  return (
    <section className="ds-section">
      <h3 className="ds-section-title">Motion Tokens</h3>
      <p className="ds-section-desc">Hover each card to preview the transition</p>
      <div className="ds-motion-grid">
        {TRANSITION_TOKENS.map((tok) => (
          <div
            key={tok.name}
            className="ds-motion-demo"
            style={{ transition: `transform var(${tok.name}), box-shadow var(${tok.name})` }}
          >
            <span className="ds-token-name">{tok.name}</span>
            <span className="ds-token-label">{tok.label}</span>
          </div>
        ))}
      </div>
      <table className="ds-type-table" style={{ marginTop: "var(--space-5)" }}>
        <thead>
          <tr>
            <th>Easing Token</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {EASING_TOKENS.map((tok) => (
            <tr key={tok.name}>
              <td className="ds-token-name">{tok.name}</td>
              <td style={{ color: "var(--text-secondary)", fontSize: "var(--font-sm)" }}>{tok.label}</td>
            </tr>
          ))}
        </tbody>
      </table>
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
        <SpacingSection />
        <ShadowSection />
        <RadiusSection />
        <ZIndexSection />
        <MotionSection />
        <ComponentsSection />
      </div>
    </PageLayout>
  );
}
