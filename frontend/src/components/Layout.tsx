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
  const { prefs } = useUiPrefs();
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
            placeholder="顧客名・リードIDで検索..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          <button type="submit" aria-label="検索">🔍</button>
        </form>
      </header>

      {/* === 下段: 白ナビゲーションバー ===
          show_sidebar=false の場合はリンク群を畳むが、ユーザー情報＋ログアウトは残す
          （詰みを防ぐため。「サイドバー」の語義は GAS 移行後の 2 段ナビ全体を指す） */}
      <nav className="mainnav">
        <div className="mainnav-links">
          {permsLoading ? (
            <span className="topnav-loading">権限読込中...</span>
          ) : prefs.show_sidebar ? (
            <>
              {hasPermission("dashboard.view") && (
                <NavLink to="/" end className="mainnav-link">ダッシュボード</NavLink>
              )}

              <NavDropdown
                label="リード"
                activePaths={["/lead-chat", "/leads", "/customers", "/companies", "/contacts", "/archive"]}
              >
                {prefs.show_chat_menu && <NavLink to="/lead-chat">リードチャット</NavLink>}
                {hasPermission("leads.view") && <NavLink to="/leads">新規顧客チャット</NavLink>}
                {hasPermission("customers.view") && <NavLink to="/customers">ルート顧客チャット</NavLink>}
                {/* Phase 1-B-2 Step 5c-1: 新 B2B モデル（会社 + 担当者）。Step 5d で customers と統合予定 */}
                {hasPermission("customers.view") && <NavLink to="/companies">会社管理（新）</NavLink>}
                {hasPermission("customers.view") && <NavLink to="/contacts">担当者管理（新）</NavLink>}
                <NavLink to="/archive">アーカイブ</NavLink>
              </NavDropdown>

              {hasPermission("products.view") && (
                <NavLink to="/inventory" className="mainnav-link">在庫</NavLink>
              )}

              {prefs.show_sales_menu && (
                <NavDropdown
                  label="見積・請求"
                  activePaths={["/quotes", "/invoices"]}
                >
                  {hasPermission("quotes.create") && <NavLink to="/quotes/new">見積もり作成</NavLink>}
                  {hasPermission("quotes.view") && <NavLink to="/quotes">見積もり履歴</NavLink>}
                  {hasPermission("invoices.view") && <NavLink to="/invoices">請求書管理</NavLink>}
                </NavDropdown>
              )}

              <NavLink to="/reports" className="mainnav-link">レポート</NavLink>
              <NavLink to="/faq" className="mainnav-link">FAQ</NavLink>

              {prefs.show_admin_menu && (
                <NavDropdown
                  label="管理"
                  activePaths={["/deals", "/staff", "/bots", "/teams", "/roles", "/data", "/suppliers", "/purchase-orders", "/shifts"]}
                >
                  {hasPermission("deals.view") && <NavLink to="/deals">商談管理</NavLink>}
                  {hasPermission("suppliers.view") && <NavLink to="/suppliers">仕入先管理</NavLink>}
                  {hasPermission("purchase_orders.view") && <NavLink to="/purchase-orders">仕入注文</NavLink>}
                  {hasPermission("staff.view") && <NavLink to="/staff">スタッフ管理</NavLink>}
                  {hasPermission("bots.view") && <NavLink to="/bots">Bot管理</NavLink>}
                  {hasPermission("teams.view") && <NavLink to="/teams">チーム管理</NavLink>}
                  {hasPermission("shifts.view") && <NavLink to="/shifts">シフト管理</NavLink>}
                  {hasAny("roles.view", "roles.create") && <NavLink to="/roles">権限管理</NavLink>}
                  {hasPermission("erp.view") && <NavLink to="/data">データ管理</NavLink>}
                </NavDropdown>
              )}

              {prefs.show_settings_menu && (
                <NavLink to="/settings" className="mainnav-link">設定</NavLink>
              )}

              <NavDropdown
                label="その他"
                activePaths={["/knowledge", "/prompts", "/templates"]}
              >
                {prefs.show_buddy_menu && hasPermission("buddy.view_own") && <NavLink to="/knowledge">Buddy</NavLink>}
                {hasPermission("badges.view") && <NavLink to="/prompts">バッジ</NavLink>}
                <NavLink to="/templates">テンプレート管理</NavLink>
              </NavDropdown>
            </>
          ) : (
            // show_sidebar=false: リンクは出さず空のまま（左寄せの空 div）
            null
          )}
        </div>
        <div className="mainnav-user">
          <span className="mainnav-email">{user?.email}</span>
          <button className="btn-logout" onClick={() => setShowLogoutConfirm(true)}>
            ログアウト
          </button>
        </div>
      </nav>

      <main className={`main-content-top ${!prefs.show_sidebar ? "main-content-top--full" : ""}`}>
        <Outlet />
      </main>

      <ConfirmModal
        open={showLogoutConfirm}
        title="ログアウト"
        message="ログアウトしますか？ 入力中のデータは失われます。"
        confirmLabel="ログアウト"
        onConfirm={() => { setShowLogoutConfirm(false); signOut(); }}
        onCancel={() => setShowLogoutConfirm(false)}
      />
    </div>
  );
}
