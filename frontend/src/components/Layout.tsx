/**
 * アプリケーション共通レイアウト（GAS版互換・2段ナビゲーション）。
 *
 * 上段（ダークネイビー）: CRMロゴ + 顧客名・リードID検索バー
 * 下段（白）: メニュー項目（ドロップダウン付き）+ ユーザー情報 + ログアウト
 *
 * 変更履歴:
 *   2026-04-16: Phase 1対応（リード/チーム/ロール・権限追加）
 *   2026-04-16: 左サイドバー→上部トップナビに変更
 *   2026-04-17: GAS版互換の2段ナビに刷新（ドロップダウン付き、検索バーUI追加）
 */

import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { useUiPrefs } from "../contexts/UiPrefsContext";
import { usePermissions } from "../hooks/usePermissions";
import ConfirmModal from "./ConfirmModal";
import NavDropdown from "./NavDropdown";

export default function Layout() {
  const { user, signOut } = useAuth();
  const { hasPermission, hasAny, loading: permsLoading } = usePermissions();
  const { prefs, loading: uiPrefsLoading } = useUiPrefs();
  // PR #166 F3: 権限・UI prefs どちらかが未確定の間は menu を出さない。
  // 特に show_admin_menu はデフォルト true（コンテキストで「未紐づけ admin 救済」のため）
  // のため、fetch 完了前にクリックされると空のドロップダウンが見えるリスクがあった。
  const navLoading = permsLoading || uiPrefsLoading;
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const navigate = useNavigate();

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    // TODO: Phase 2 で検索APIを実装。現状はリード一覧ページに検索語を引き継ぐ仮実装
    if (searchQuery.trim() && hasPermission("leads.view")) {
      navigate(`/leads?search=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  return (
    <div className="layout-top">
      {/* === 上段: ダークネイビーブランドバー === */}
      <header className="brandbar">
        <div className="brandbar-logo">
          <span className="brandbar-icon">🔗</span>
          <span>CRM</span>
        </div>
        <form className="brandbar-search" onSubmit={handleSearch}>
          <input
            type="search"
            placeholder="Search by customer name or lead ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <button type="submit" aria-label="Search">🔍</button>
        </form>
      </header>

      {/* === 下段: 白ナビゲーションバー ===
          2026-05-02 hotfix:
            旧実装は `show_sidebar=false` でメニューリンク群を完全に空にしていたため、
            「サイドバー表示」を OFF にしたユーザーが /staff へ自力で戻れず詰む UX trap が
            発生していた（Shingo さんが highlife-jpn 本番で踏んだ）。
            本修正でゲートを撤廃し、permission ベースで常時メニューを表示する。
            `show_sidebar` toggle は将来的に削除予定（後続 PR で deprecate）。 */}
      <nav className="mainnav">
        <div className="mainnav-links">
          {navLoading ? (
            <span className="topnav-loading">Loading...</span>
          ) : (
            <>
              {hasPermission("dashboard.view") && (
                <NavLink to="/" end className="mainnav-link">Dashboard</NavLink>
              )}

              <NavDropdown
                label="Leads"
                activePaths={["/lead-chat", "/leads", "/customers", "/companies", "/contacts", "/archive"]}
              >
                {prefs.show_chat_menu && <NavLink to="/lead-chat">Lead chat</NavLink>}
                {hasPermission("leads.view") && <NavLink to="/leads">New customer chat</NavLink>}
                {hasPermission("customers.view") && <NavLink to="/customers">Recurring customer chat</NavLink>}
                {/* Phase 1-B-2 Step 5c-1: 新 B2B モデル（会社 + 担当者）。Step 5d で customers と統合予定 */}
                {hasPermission("customers.view") && <NavLink to="/companies">Companies (new)</NavLink>}
                {hasPermission("customers.view") && <NavLink to="/contacts">Contacts (new)</NavLink>}
                <NavLink to="/archive">Archive</NavLink>
              </NavDropdown>

              {hasPermission("products.view") && (
                <NavLink to="/inventory" className="mainnav-link">Inventory</NavLink>
              )}

              {prefs.show_sales_menu && (
                <NavDropdown
                  label="Quotes & Invoices"
                  activePaths={["/quotes", "/invoices"]}
                >
                  {hasPermission("quotes.create") && <NavLink to="/quotes/new">Create quote</NavLink>}
                  {hasPermission("quotes.view") && <NavLink to="/quotes">Quote history</NavLink>}
                  {hasPermission("invoices.view") && <NavLink to="/invoices">Invoices</NavLink>}
                </NavDropdown>
              )}

              <NavLink to="/reports" className="mainnav-link">Reports</NavLink>
              <NavLink to="/faq" className="mainnav-link">FAQ</NavLink>

              {prefs.show_admin_menu && (
                <NavDropdown
                  label="Admin"
                  activePaths={["/deals", "/staff", "/bots", "/teams", "/roles", "/data", "/suppliers", "/purchase-orders", "/shifts", "/channels"]}
                >
                  {hasPermission("deals.view") && <NavLink to="/deals">Deals</NavLink>}
                  {hasPermission("suppliers.view") && <NavLink to="/suppliers">Suppliers</NavLink>}
                  {hasPermission("purchase_orders.view") && <NavLink to="/purchase-orders">Purchase orders</NavLink>}
                  {hasPermission("staff.view") && <NavLink to="/staff">Staff</NavLink>}
                  {hasPermission("bots.view") && <NavLink to="/bots">Bots</NavLink>}
                  {hasPermission("teams.view") && <NavLink to="/teams">Teams</NavLink>}
                  {hasPermission("shifts.view") && <NavLink to="/shifts">Shifts</NavLink>}
                  {hasAny("roles.view", "roles.create") && <NavLink to="/roles">Roles & permissions</NavLink>}
                  {hasPermission("erp.view") && <NavLink to="/data">Data management</NavLink>}
                  {/* Phase 1-D Sprint 3: Meta Inbox 接続管理 */}
                  {hasPermission("channels.view") && <NavLink to="/channels">Channels (Meta)</NavLink>}
                </NavDropdown>
              )}

              {prefs.show_settings_menu && (
                <NavLink to="/settings" className="mainnav-link">Settings</NavLink>
              )}

              <NavDropdown
                label="More"
                activePaths={["/knowledge", "/prompts", "/templates"]}
              >
                {prefs.show_buddy_menu && hasPermission("buddy.view_own") && <NavLink to="/knowledge">Buddy</NavLink>}
                {hasPermission("badges.view") && <NavLink to="/prompts">Badges</NavLink>}
                <NavLink to="/templates">Templates</NavLink>
              </NavDropdown>
            </>
          )}
        </div>
        <div className="mainnav-user">
          <span className="mainnav-email">{user?.email}</span>
          <button className="btn-logout" onClick={() => setShowLogoutConfirm(true)}>
            Sign out
          </button>
        </div>
      </nav>

      <main className={`main-content-top ${!prefs.show_sidebar ? "main-content-top--full" : ""}`}>
        <Outlet />
      </main>

      <ConfirmModal
        open={showLogoutConfirm}
        title="Sign out"
        message="Sign out now? Any unsaved input will be lost."
        confirmLabel="Sign out"
        onConfirm={() => { setShowLogoutConfirm(false); signOut(); }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </div>
  );
}
