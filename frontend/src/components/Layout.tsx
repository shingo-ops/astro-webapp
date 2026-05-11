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
 */

import { useState } from "react";
import { NavLink, Outlet, useNavigate, useLocation } from "react-router-dom";
import {
  LayoutDashboard, Users, Package, FileText, BarChart2,
  HelpCircle, Settings, MoreHorizontal, ChevronDown,
  Search, LogOut, ShieldCheck,
} from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
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
    ...(prefs.show_chat_menu ? [{ to: "/lead-chat", label: "Lead Chat" }] : []),
    ...(hasPermission("leads.view") ? [{ to: "/leads", label: "New Leads" }] : []),
    ...(hasPermission("customers.view") ? [
      { to: "/customers", label: "Route Customers" },
      { to: "/companies", label: "Companies" },
      { to: "/contacts", label: "Contacts" },
    ] : []),
    { to: "/archive", label: "Archive" },
  ];

  const salesItems: SubItem[] = [
    ...(hasPermission("quotes.create") ? [{ to: "/quotes/new", label: "New Quote" }] : []),
    ...(hasPermission("quotes.view") ? [{ to: "/quotes", label: "Quote History" }] : []),
    ...(hasPermission("invoices.view") ? [{ to: "/invoices", label: "Invoices" }] : []),
  ];

  const adminItems: SubItem[] = [
    ...(hasPermission("deals.view") ? [{ to: "/deals", label: "Deals" }] : []),
    ...(hasPermission("suppliers.view") ? [{ to: "/suppliers", label: "Suppliers" }] : []),
    ...(hasPermission("purchase_orders.view") ? [{ to: "/purchase-orders", label: "Purchase Orders" }] : []),
    ...(hasPermission("staff.view") ? [{ to: "/staff", label: "Staff" }] : []),
    ...(hasPermission("bots.view") ? [{ to: "/bots", label: "Bots" }] : []),
    ...(hasPermission("teams.view") ? [{ to: "/teams", label: "Teams" }] : []),
    ...(hasPermission("shifts.view") ? [{ to: "/shifts", label: "Shifts" }] : []),
    ...(hasAny("roles.view", "roles.create") ? [{ to: "/roles", label: "Roles & Permissions" }] : []),
    ...(hasPermission("erp.view") ? [{ to: "/data", label: "Data Management" }] : []),
    ...(hasPermission("orders.view") ? [{ to: "/commission-settings", label: "Commission Settings" }] : []),
    ...(hasPermission("channels.view") ? [{ to: "/channels", label: "Channels (Meta)" }] : []),
  ];

  const moreItems: SubItem[] = [
    ...(prefs.show_buddy_menu && hasPermission("buddy.view_own") ? [{ to: "/knowledge", label: "Buddy" }] : []),
    ...(hasPermission("badges.view") ? [{ to: "/prompts", label: "Badges" }] : []),
    { to: "/templates", label: "Templates" },
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
          {sidebarExpanded ? (
            <img src="/logo.png" alt="Sales Anchor" className="sidebar-logo-full" />
          ) : (
            <img src="/favicon.png" alt="SA" className="sidebar-logo-icon" />
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
                  <span className="sidebar-label">Dashboard</span>
                </NavLink>
              )}

              <SidebarAccordion
                label="Leads"
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
                  <span className="sidebar-label">Inventory</span>
                </NavLink>
              )}

              {prefs.show_sales_menu && (
                <SidebarAccordion
                  label="Quotes & Invoices"
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
                <span className="sidebar-label">Reports</span>
              </NavLink>

              <NavLink
                to="/faq"
                className={({ isActive }) => `sidebar-item${isActive ? " active" : ""}`}
              >
                <span className="sidebar-icon"><HelpCircle size={20} /></span>
                <span className="sidebar-label">FAQ</span>
              </NavLink>

              {prefs.show_admin_menu && (
                <SidebarAccordion
                  label="Admin"
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
                  <span className="sidebar-label">Settings</span>
                </NavLink>
              )}

              <SidebarAccordion
                label="More"
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
              placeholder="Search by customer name or lead ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </form>
          <div className="topbar-user">
            <span className="topbar-email">{user?.email}</span>
            <button
              className="btn-signout"
              onClick={() => setShowLogoutConfirm(true)}
            >
              <LogOut size={15} />
              <span>Sign out</span>
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
        title="Sign Out"
        message="Are you sure you want to sign out? Any unsaved data will be lost."
        confirmLabel="Sign out"
        onConfirm={() => { setShowLogoutConfirm(false); signOut(); }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </div>
  );
}
