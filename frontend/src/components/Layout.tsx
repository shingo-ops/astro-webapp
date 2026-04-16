/**
 * アプリケーション共通レイアウト。
 * サイドバーナビゲーション + メインコンテンツ領域。
 *
 * 変更履歴:
 *   2026-04-16: Phase 1対応（リード/チーム/ロール管理の権限連動ナビ追加）
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
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Jarvis CRM</h1>
        </div>
        <nav className="sidebar-nav">
          {permsLoading ? (
            <div className="sidebar-loading">権限読込中...</div>
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
        <div className="sidebar-footer">
          <div className="user-info">{user?.email}</div>
          <button className="btn-logout" onClick={() => setShowLogoutConfirm(true)}>ログアウト</button>
        </div>
      </aside>
      <main className="main-content">
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
