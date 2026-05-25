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

import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { NAV_ICONS, THEME_ICONS, GlobeIcon, LeadChatIcon } from "../constants/icons";
import { useTranslation } from "react-i18next";
import { useAuth } from "../contexts/AuthContext";
import { useLocale } from "../contexts/LocaleContext";
import { useTheme } from "../contexts/ThemeContext";
import { useUiPrefs } from "../contexts/UiPrefsContext";
import { usePermissions } from "../hooks/usePermissions";
import { useSuperAdmin } from "../hooks/useSuperAdmin";
import { useSSE } from "../hooks/useSSE";
import { listConversations } from "../lib/messages";
import ConfirmModal from "./ConfirmModal";
import { ICON } from "../constants/iconSizes";
import type { NavItem } from "../types/nav";

/* ------------------------------------------------------------------ */
/* SidebarAccordion                                                     */
/* ------------------------------------------------------------------ */

interface SidebarAccordionProps {
  label: string;
  icon: React.ReactNode;
  items: NavItem[];
  activePaths: string[];
  isExpanded: boolean;
  isOpen: boolean;
  onToggle: () => void;
}

function SidebarAccordion({
  label, icon, items, activePaths, isExpanded, isOpen, onToggle,
}: SidebarAccordionProps) {
  const { t } = useTranslation();
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
            <NAV_ICONS.chevronDown size={ICON.sm} />
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
              {t(item.labelKey)}
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
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const [openAccordion, setOpenAccordion] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Phase 3: 未読バッジ（ナビ全体に表示）
  // ---------------------------------------------------------------------------
  const [unreadCount, setUnreadCount] = useState(0);
  const loadUnreadCount = useCallback(async () => {
    try {
      const data = await listConversations({ unread_only: true });
      setUnreadCount((data.conversations || []).length);
    } catch {
      // パーミッションなし・未認証等はバッジ非表示のまま維持
    }
  }, []);
  useEffect(() => { loadUnreadCount(); }, [loadUnreadCount]);
  useSSE({ endpoint: "/api/v1/conversations/stream", onUpdate: loadUnreadCount });

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

  const showCrmLink = hasPermission("leads.view") || hasPermission("customers.view");

  const showSalesLink =
    prefs.show_sales_menu &&
    (hasPermission("quotes.view") || hasPermission("invoices.view"));
  const salesLinkTo = hasPermission("quotes.view") ? "/quotes" : "/invoices";

  // 管理センターリンクを表示する権限チェック（いずれか1つでも持っていれば表示）
  const showManagementCenter =
    isSuperAdmin ||
    hasAny(
      "staff.view", "teams.view", "roles.view", "bots.view",
      "shifts.view", "channels.view", "erp.view", "orders.view",
      "customers.view", "deals.view", "suppliers.view", "purchase_orders.view",
      "tenant.profile.view",
    );

  const moreItems: NavItem[] = [
    { to: "/templates", labelKey: "nav.templates" },
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
            <div className="sidebar-loading-dot">...</div>
          ) : (
            <>
              {hasPermission("dashboard.view") && (
                <NavLink
                  to="/"
                  end
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.dashboard size={ICON.base} /></span>
                  <span className="sidebar-label">{t("nav.dashboard")}</span>
                </NavLink>
              )}

              {prefs.show_chat_menu && (
                <NavLink
                  to="/lead-chat"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon">
                    <LeadChatIcon size={ICON.base} />
                  </span>
                  <span className="sidebar-label">{t("nav.leadChat")}</span>
                  {unreadCount > 0 && (
                    <span
                      className="nav-unread-badge"
                      aria-label={t("inbox.unreadBadge", { count: unreadCount })}
                    >
                      {unreadCount > 99 ? "99+" : unreadCount}
                    </span>
                  )}
                </NavLink>
              )}

              <NavLink
                to="/schedule"
                className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
              >
                <span className="sidebar-icon"><NAV_ICONS.schedule size={ICON.base} /></span>
                <span className="sidebar-label">{t("nav.schedule")}</span>
              </NavLink>

              {hasPermission("products.view") && (
                <NavLink
                  to="/inventory"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.inventory size={ICON.base} /></span>
                  <span className="sidebar-label">{t("nav.inventory")}</span>
                </NavLink>
              )}

              {showSalesLink && (
                <NavLink
                  to={salesLinkTo}
                  className={() => {
                    const on =
                      location.pathname.startsWith("/quotes") ||
                      location.pathname.startsWith("/invoices");
                    return `sidebar-item${on ? " active" : ""}`;
                  }}
                >
                  <span className="sidebar-icon"><NAV_ICONS.fileText size={ICON.base} /></span>
                  <span className="sidebar-label">{t("nav.quotesInvoices")}</span>
                </NavLink>
              )}

              {showCrmLink && (
                <NavLink
                  to="/crm"
                  className={() => {
                    const onCrm =
                      location.pathname === "/crm" ||
                      location.pathname.startsWith("/crm/");
                    return `sidebar-item${onCrm ? " active" : ""}`;
                  }}
                >
                  <span className="sidebar-icon"><NAV_ICONS.leads size={ICON.base} /></span>
                  <span className="sidebar-label">{t("nav.leads")}</span>
                </NavLink>
              )}

              {hasPermission("orders.view") && (
                <NavLink
                  to="/orders"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.orders size={ICON.base} aria-hidden="true" /></span>
                  <span className="sidebar-label">{t("nav.orders")}</span>
                </NavLink>
              )}

              {showManagementCenter && (
                <NavLink
                  to="/management-center"
                  className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
                >
                  <span className="sidebar-icon"><NAV_ICONS.admin size={ICON.base} /></span>
                  <span className="sidebar-label">{t("nav.managementCenter")}</span>
                </NavLink>
              )}

              {/* 通知設定は管理センター（/management-center/notifications）に統合済み */}

              <SidebarAccordion
                label={t("nav.more")}
                icon={<NAV_ICONS.more size={ICON.base} />}
                items={moreItems}
                activePaths={["/templates"]}
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
        {/* Content */}
        <main className={`app-content${isInbox ? " app-content--inbox" : ""}`}>
          <Outlet />
        </main>
      </div>

      {/* ============ Fixed avatar button (Chrome / Meta style) ============ */}
      <button
        className="avatar-btn"
        onClick={() => setDrawerOpen(true)}
        aria-label={t("nav.openUserMenu")}
        data-tooltip={t("nav.openUserMenu")}
      >
        {user?.email ? user.email[0].toUpperCase() : <NAV_ICONS.logout size={18} />}
      </button>

      {/* ============ User drawer backdrop ============ */}
      {drawerOpen && (
        <div
          className="user-drawer-backdrop"
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ============ User drawer panel ============ */}
      <div
        className={`user-drawer${drawerOpen ? " user-drawer--open" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={t("nav.account")}
      >
        <div className="user-drawer-header">
          <span className="user-drawer-title">{t("nav.account")}</span>
          <button
            className="user-drawer-close"
            onClick={() => setDrawerOpen(false)}
            aria-label={t("common.close")}
            data-tooltip={t("common.close")}
          >
            <NAV_ICONS.close size={ICON.md} aria-hidden="true" />
          </button>
        </div>
        <div className="user-drawer-body">
          <div className="user-drawer-email">{user?.email}</div>

          <button
            className="user-drawer-action"
            onClick={() => changeTheme(theme === "light" ? "dark" : "light")}
          >
            {theme === "light"
              ? <THEME_ICONS.light size={ICON.md} aria-hidden="true" />
              : <THEME_ICONS.dark size={ICON.md} aria-hidden="true" />}
            <span>{theme === "light" ? t("nav.switchToDark") : t("nav.switchToLight")}</span>
          </button>

          <button
            className="user-drawer-action"
            onClick={() => changeLanguage(locale === "ja" ? "en" : "ja")}
          >
            <GlobeIcon size={ICON.md} aria-hidden="true" />
            <span>{locale === "ja" ? t("language.en") : t("language.ja")}</span>
          </button>

          <button
            className="user-drawer-action user-drawer-action--danger"
            onClick={() => { setDrawerOpen(false); setShowLogoutConfirm(true); }}
          >
            <NAV_ICONS.logout size={ICON.md} aria-hidden="true" />
            <span>{t("nav.signOut")}</span>
          </button>
        </div>
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
