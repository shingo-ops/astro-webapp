/**
 * アプリケーション共通レイアウト（トップナビ型）。
 *
 * 旧GAS版のレイアウトに合わせて、上部に横並びのナビゲーションバーを配置。
 * 左: ブランド / 中央: ナビ項目（権限連動表示） / 右: ユーザー情報 + ログアウト
 *
 * 変更履歴:
 *   2026-04-16: Phase 1対応（リード/チーム/ロール・権限の権限連動ナビ追加）
 *   2026-04-16: GAS互換のため左サイドバー→上部トップナビに変更
 */

import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../hooks/usePermissions";
import ConfirmModal from "./ConfirmModal";

export default function Layout() {
  const { user, signOut } = useAuth();
  const { hasPermission, hasAny, loading: permsLoading } = usePermissions();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  return (
    <div className="layout-top">
      <header className="topnav">
        <div className="topnav-brand">
          <h1>Jarvis CRM</h1>
        </div>
        <nav className="topnav-links">
          {permsLoading ? (
            <span className="topnav-loading">権限読込中...</span>
          ) : (
            <>
              {hasPermission("dashboard.view") && <NavLink to="/" end>ダッシュボード</NavLink>}
              {hasPermission("customers.view") && <NavLink to="/customers">顧客管理</NavLink>}
              {hasPermission("leads.view") && <NavLink to="/leads">リード管理</NavLink>}
              {hasPermission("deals.view") && <NavLink to="/deals">案件管理</NavLink>}
              {hasPermission("orders.view") && <NavLink to="/orders">注文管理</NavLink>}
              {hasPermission("teams.view") && <NavLink to="/teams">チーム管理</NavLink>}
              {hasAny("roles.view", "roles.create") && <NavLink to="/roles">ロール・権限</NavLink>}
            </>
          )}
        </nav>
        <div className="topnav-user">
          <span className="topnav-email">{user?.email}</span>
          <button className="btn-logout" onClick={() => setShowLogoutConfirm(true)}>
            ログアウト
          </button>
        </div>
      </header>
      <main className="main-content-top">
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
