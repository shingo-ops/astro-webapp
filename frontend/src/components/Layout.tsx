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
 */

import { useState } from "react";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Users, Package, FileText, BarChart2,
  HelpCircle, Settings, MoreHorizontal, ChevronDown,
  Search, LogOut, ShieldCheck,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import { useLocale } from "../contexts/LocaleContext";
import { useUiPrefs } from "../contexts/UiPrefsContext";
import { usePermissions } from "../hooks/usePermissions";
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
            <ChevronDown size={14} />
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
  const { user, signOut } = useAuth();
  const { hasPermission, hasAny, loading: permsLoading } = usePermissions();
  const { prefs, loading: uiPrefsLoading } = useUiPrefs();
  const navLoading = permsLoading || uiPrefsLoading;

  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [openAccordion, setOpenAccordion] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim() && hasPermission("leads.view")) {
      navigate(`/leads?search=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const toggleAccordion = (key: string) => {
    setOpenAccordion((prev) => (prev === key ? null : key));
  };

  const handleSidebarLeave = () => {
    setSidebarExpanded(false);
    setOpenAccordion(null);
  };

  /* ---- permission-filtered sub-item lists ---- */

  const leadsItems: SubItem[] = [
    ...(prefs.show_chat_menu ? [{ to: "/lead-chat", label: t("nav.leadChat") }] : []),
    ...(hasPermission("leads.view") ? [{ to: "/leads", label: t("nav.newLeads") }] : []),
    ...(hasPermission("customers.view") ? [
      { to: "/customers", label: t("nav.routeCustomers") },
      { to: "/companies", label: t("nav.companies") },
      { to: "/contacts", label: t("nav.contacts") },
    ] : []),
    { to: "/archive", label: t("nav.archive") },
  ];

  const salesItems: SubItem[] = [
    ...(hasPermission("quotes.create") ? [{ to: "/quotes/new", label: t("nav.newQuote") }] : []),
    ...(hasPermission("quotes.view") ? [{ to: "/quotes", label: t("nav.quoteHistory") }] : []),
    ...(hasPermission("invoices.view") ? [{ to: "/invoices", label: t("nav.invoices") }] : []),
  ];

  const adminItems: SubItem[] = [
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
                  <span className="sidebar-icon"><LayoutDashboard size={20} /></span>
                  <span className="sidebar-label">{t("nav.dashboard")}</span>
                </NavLink>
              )}

              <SidebarAccordion
                label={t("nav.leads")}
                icon={<Users size={20} />}
                items={leadsItems}
                activePaths={["/lead-chat", "/leads", "/customers", "/companies", "/contacts", "/archive"]}
                isExpanded={sidebarExpanded}
                isOpen={openAccordion === "leads"}
                onToggle={() => toggleAccordion("leads")}
              />

              {hasPermission("products.view") && (
                <NavLink
                  to="/inventory"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><Package size={20} /></span>
                  <span className="sidebar-label">{t("nav.inventory")}</span>
                </NavLink>
              )}

              {prefs.show_sales_menu && (
                <SidebarAccordion
                  label={t("nav.quotesInvoices")}
                  icon={<FileText size={20} />}
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
                <span className="sidebar-icon"><BarChart2 size={20} /></span>
                <span className="sidebar-label">{t("nav.reports")}</span>
              </NavLink>

              <NavLink
                to="/faq"
                className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
              >
                <span className="sidebar-icon"><HelpCircle size={20} /></span>
                <span className="sidebar-label">{t("nav.faq")}</span>
              </NavLink>

              {prefs.show_admin_menu && (
                <SidebarAccordion
                  label={t("nav.admin")}
                  icon={<ShieldCheck size={20} />}
                  items={adminItems}
                  activePaths={["/deals", "/staff", "/bots", "/teams", "/roles", "/data", "/suppliers", "/purchase-orders", "/shifts", "/channels", "/commission-settings"]}
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
        {/* Top bar */}
        <header className="app-topbar">
          <form className="topbar-search" onSubmit={handleSearch}>
            <Search size={16} className="topbar-search-icon" />
            <input
              type="search"
              placeholder={t("nav.searchPlaceholder")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </form>
          <div className="topbar-user">
            <span className="topbar-email">{user?.email}</span>
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
        </header>

        {/* Content */}
        <main className="app-content">
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
