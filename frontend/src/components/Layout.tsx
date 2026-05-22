/**
 * アプリケーション共通レイアウト（ADR-022: Meta Business Suite 風サイドバー）
 *
 * 構成:
 *   app-shell (flex row)
 *   ├── sidebar-panel  細幅68px→ホバーで240pxに展開, アイコン+ラベル+アコーディオン
 *   └── app-body       topbar(検索+ユーザー) + app-content
 *
 * 変更履歴:
 *   2026-04-16: Phase 1対応
 *   2026-04-17: GAS版互換の2段ナビに刷新
 *   2026-05-11: ADR-022 — 左サイドバー + Meta Business Suite 配色に刷新
 *   2026-05-14: ADR-027 — i18n対応（useTranslation + useLocale）
 *   2026-05-14: ADR-033 — テーマ切り替えボタン追加（useTheme）
 */

import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { NAV_ICONS, THEME_ICONS, GlobeIcon, LeadChatIcon } from "../constants/icons";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import { useLocale } from "../contexts/LocaleContext";
import { useTheme } from "../contexts/ThemeContext";
import { useUiPrefs } from "../contexts/UiPrefsContext";
import { usePermissions } from "../hooks/usePermissions";
import { useSuperAdmin } from "../hooks/useSuperAdmin";
import ConfirmModal from "./ConfirmModal";

/* ------------------------------------------------------------------ */
/* SidebarAccordion                                                     */
/* ------------------------------------------------------------------ */

interface SubItem {
  to: string;
  label: string;
}

interface SidebarAccordionProps {
  label: string;
  icon: React.ReactNode;
  items: SubItem[];
  activePaths: string[];
  isExpanded: boolean;
  isOpen: boolean;
  onToggle: () => void;
}

function SidebarAccordion({
  label, icon, items, activePaths, isExpanded, isOpen, onToggle,
}: SidebarAccordionProps) {
  const { pathname } = useLocation();
  const isActive = activePaths.some((p) => pathname.startsWith(p));

  if (items.length === 0) return null;

  return (
    <div className="sidebar-accordion-wrap">
      <button
        className={`sidebar-item sidebar-accordion-btn${isActive ? " active" : ""}`}
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <span className="sidebar-icon">{icon}</span>
        <span className="sidebar-label">{label}</span>
        {isExpanded && (
          <span className={`sidebar-caret${isOpen ? " open" : ""}`}>
            <NAV_ICONS.chevronDown size={14} />
          </span>
        )}
      </button>

      {isExpanded && isOpen && (
        <div className="sidebar-accordion-menu">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive: a }) => `sidebar-sub-item${a ? " active" : ""}`}
            >
              {item.label}
            </NavLink>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Layout                                                               */
/* ------------------------------------------------------------------ */

export default function Layout() {
  const { t } = useTranslation();
  const { locale, changeLanguage } = useLocale();
  const { theme, changeTheme } = useTheme();
  const { user, signOut } = useAuth();
  const { hasPermission, hasAny, loading: permsLoading } = usePermissions();
  const { isSuperAdmin } = useSuperAdmin();
  const { prefs, loading: uiPrefsLoading } = useUiPrefs();
  const navLoading = permsLoading || uiPrefsLoading;

  const location = useLocation();
  const isInbox = location.pathname === "/lead-chat";
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [openAccordion, setOpenAccordion] = useState<string | null>(null);

  const toggleAccordion = (key: string) => {
    const next = openAccordion === key ? null : key;
    setOpenAccordion(next);
    if (next !== null) setSidebarExpanded(true); // アコーディオンを開く際はサイドバーも展開
  };

  const handleSidebarLeave = () => {
    setSidebarExpanded(false);
    setOpenAccordion(null);
  };

  /* ---- permission-filtered sub-item lists ---- */

  const showLeadsLink = hasPermission("leads.view") || hasPermission("customers.view");

  const salesItems: SubItem[] = [
    ...(hasPermission("quotes.create") ? [{ to: "/quotes/new", label: t("nav.newQuote") }] : []),
    ...(hasPermission("quotes.view") ? [{ to: "/quotes", label: t("nav.quoteHistory") }] : []),
    ...(hasPermission("invoices.view") ? [{ to: "/invoices", label: t("nav.invoices") }] : []),
  ];

  const adminItems: SubItem[] = [
    ...(hasPermission("customers.view") ? [
      { to: "/companies", label: t("nav.companies") },
    ] : []),
    ...(hasPermission("deals.view") ? [{ to: "/deals", label: t("nav.deals") }] : []),
    ...(hasPermission("suppliers.view") ? [{ to: "/suppliers", label: t("nav.suppliers") }] : []),
    ...(hasPermission("purchase_orders.view") ? [{ to: "/purchase-orders", label: t("nav.purchaseOrders") }] : []),
    ...(hasPermission("staff.view") ? [{ to: "/staff", label: t("nav.staff") }] : []),
    ...(hasPermission("bots.view") ? [{ to: "/bots", label: t("nav.bots") }] : []),
    ...(hasPermission("teams.view") ? [{ to: "/teams", label: t("nav.teams") }] : []),
    ...(hasPermission("shifts.view") ? [{ to: "/shifts", label: t("nav.shifts") }] : []),
    ...(hasAny("roles.view", "roles.create") ? [{ to: "/roles", label: t("nav.rolesPermissions") }] : []),
    ...(hasPermission("erp.view") ? [{ to: "/data", label: t("nav.dataManagement") }] : []),
    ...(hasPermission("orders.view") ? [{ to: "/commission-settings", label: t("nav.commissionSettings") }] : []),
    ...(hasPermission("channels.view") ? [{ to: "/channels", label: t("nav.channels") }] : []),
    // spec.md v1.1 F2 (Sprint 2): テナント admin 用「在庫表示権限」
    ...(hasPermission("tenant.inventory_visibility.edit")
      ? [{ to: "/admin/inventory-visibility", label: t("nav.inventoryVisibility") }]
      : []),
    // spec.md v1.1 F8 (Sprint 8): テナント admin 用「発行者情報」 (PO PDF / メール差出人)
    ...(hasPermission("tenant.profile.edit") || hasPermission("tenant.profile.view")
      ? [{ to: "/admin/tenant-profile", label: t("nav.tenantProfile") }]
      : []),
    // spec.md v1.1 F2 (Sprint 2): 中央 admin 専用「マスタ管理」リンク
    // is_super_admin=true のユーザーにだけ表示。
    // バックエンド側でも require_super_admin で二重ガード（AC2.1）。
    ...(isSuperAdmin
      ? [{ to: "/super-admin/masters", label: t("nav.superAdminMasters") }]
      : []),
    // spec.md v1.1 F5 (Sprint 5): 中央 admin 専用「Discord 受信一覧」リンク
    // is_super_admin=true のユーザーにだけ表示。
    // バックエンド側でも require_super_admin で二重ガード（AC5.5 / AC6.8 と同パターン）。
    ...(isSuperAdmin
      ? [{ to: "/super-admin/inbound", label: t("nav.superAdminInbound") }]
      : []),
    // spec.md v1.2 F9 (Sprint 9): 中央 admin 専用「スプレッドシート Phase」リンク
    // is_super_admin=true のユーザーにだけ表示。
    // バックエンド側でも require_super_admin で二重ガード。
    ...(isSuperAdmin
      ? [{ to: "/super-admin/phase-switch", label: t("nav.superAdminPhaseSwitch") }]
      : []),
  ];

  const moreItems: SubItem[] = [
    ...(prefs.show_buddy_menu && hasPermission("buddy.view_own") ? [{ to: "/knowledge", label: t("nav.buddy") }] : []),
    ...(hasPermission("badges.view") ? [{ to: "/prompts", label: t("nav.badges") }] : []),
    { to: "/templates", label: t("nav.templates") },
  ];

  return (
    <div className="app-shell">
      {/* ============ Sidebar ============ */}
      <aside
        className={`sidebar-panel${sidebarExpanded ? " sidebar-expanded" : ""}`}
        onMouseEnter={() => setSidebarExpanded(true)}
        onMouseLeave={handleSidebarLeave}
      >
        {/* Logo */}
        <div className="sidebar-logo-area">
          <img src="/favicon.png" alt="Sales Anchor" className="sidebar-logo-icon" />
          {sidebarExpanded && (
            <img src="/logo.png" alt="Sales Anchor" className="sidebar-logo-text-img" />
          )}
        </div>

        {/* Nav */}
        <nav className="sidebar-nav-items">
          {navLoading ? (
            <div className="sidebar-loading-dot">•••</div>
          ) : (
            <>
              {hasPermission("dashboard.view") && (
                <NavLink
                  to="/"
                  end
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.dashboard size={20} /></span>
                  <span className="sidebar-label">{t("nav.dashboard")}</span>
                </NavLink>
              )}

              {prefs.show_chat_menu && (
                <NavLink
                  to="/lead-chat"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon">
                    <LeadChatIcon size={20} />
                  </span>
                  <span className="sidebar-label">{t("nav.leadChat")}</span>
                </NavLink>
              )}

              {showLeadsLink && (
                <NavLink
                  to="/leads"
                  className={() => {
                    const onLeadsSection =
                      location.pathname.startsWith("/leads") ||
                      location.pathname.startsWith("/customers") ||
                      location.pathname.startsWith("/archive");
                    return `sidebar-item${onLeadsSection ? " active" : ""}`;
                  }}
                >
                  <span className="sidebar-icon"><NAV_ICONS.leads size={20} /></span>
                  <span className="sidebar-label">{t("nav.leads")}</span>
                </NavLink>
              )}

              {hasPermission("products.view") && (
                <NavLink
                  to="/inventory"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.inventory size={20} /></span>
                  <span className="sidebar-label">{t("nav.inventory")}</span>
                </NavLink>
              )}

              {prefs.show_sales_menu && (
                <SidebarAccordion
                  label={t("nav.quotesInvoices")}
                  icon={<NAV_ICONS.fileText size={20} />}
                  items={salesItems}
                  activePaths={["/quotes", "/invoices"]}
                  isExpanded={sidebarExpanded}
                  isOpen={openAccordion === "sales"}
                  onToggle={() => toggleAccordion("sales")}
                />
              )}

              <NavLink
                to="/reports"
                className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
              >
                <span className="sidebar-icon"><NAV_ICONS.report size={20} /></span>
                <span className="sidebar-label">{t("nav.reports")}</span>
              </NavLink>

              <NavLink
                to="/faq"
                className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
              >
                <span className="sidebar-icon"><NAV_ICONS.help size={20} /></span>
                <span className="sidebar-label">{t("nav.faq")}</span>
              </NavLink>

              {prefs.show_admin_menu && (
                <SidebarAccordion
                  label={t("nav.admin")}
                  icon={<NAV_ICONS.admin size={20} />}
                  items={adminItems}
                  activePaths={["/companies", "/deals", "/staff", "/bots", "/teams", "/roles", "/data", "/suppliers", "/purchase-orders", "/shifts", "/channels", "/commission-settings", "/admin/inventory-visibility", "/admin/tenant-profile", "/super-admin/masters", "/super-admin/inbound", "/super-admin/phase-switch"]}
                  isExpanded={sidebarExpanded}
                  isOpen={openAccordion === "admin"}
                  onToggle={() => toggleAccordion("admin")}
                />
              )}

              {prefs.show_settings_menu && (
                <NavLink
                  to="/settings"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><Settings size={20} /></span>
                  <span className="sidebar-label">{t("nav.settings")}</span>
                </NavLink>
              )}

              <SidebarAccordion
                label={t("nav.more")}
                icon={<MoreHorizontal size={20} />}
                items={moreItems}
                activePaths={["/knowledge", "/prompts", "/templates"]}
                isExpanded={sidebarExpanded}
                isOpen={openAccordion === "more"}
                onToggle={() => toggleAccordion("more")}
              />
            </>
          )}
        </nav>
      </aside>

      {/* ============ Main body ============ */}
      <div className="app-body">
        {/* Top bar — inbox ページでは非表示（Meta Business Suite 風の全幅レイアウト） */}
        {!isInbox && <header className="app-topbar">
          <div className="topbar-user">
            <span className="topbar-email">{user?.email}</span>
            <button
              onClick={() => changeTheme(theme === "light" ? "dark" : "light")}
              title={theme === "light" ? "ダークモードに切り替え" : "ライトモードに切り替え"}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1rem", color: "var(--text-secondary)" }}
            >
              {theme === "light" ? "🌙" : "☀️"}
            </button>
            <button
              onClick={() => changeLanguage(locale === "ja" ? "en" : "ja")}
              title={t("language.switchTo")}
              style={{ background: "none", border: "none", cursor: "pointer", fontSize: "0.85rem", color: "var(--text-secondary)" }}
            >
              🌐 {locale === "ja" ? t("language.en") : t("language.ja")}
            </button>
            <button
              className="btn-signout"
              onClick={() => setShowLogoutConfirm(true)}
            >
              <LogOut size={15} />
              <span>{t("nav.signOut")}</span>
            </button>
          </div>
        </header>}

        {/* Content */}
        <main className={`app-content${isInbox ? " app-content--inbox" : ""}`}>
          <Outlet />
        </main>
      </div>

      <ConfirmModal
        open={showLogoutConfirm}
        title={t("nav.signOutTitle")}
        message={t("nav.signOutMessage")}
        confirmLabel={t("nav.signOut")}
        onConfirm={() => { setShowLogoutConfirm(false); signOut(); }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </div>
  );
}
