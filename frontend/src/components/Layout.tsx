/**
 * アプリケーション共通レイアウト。
 * サイドバーナビゲーション + メインコンテンツ領域。
 */

import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import ConfirmModal from "./ConfirmModal";

export default function Layout() {
  const { user, signOut } = useAuth();
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1>Jarvis CRM</h1>
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/" end>ダッシュボード</NavLink>
          <NavLink to="/customers">顧客管理</NavLink>
          <NavLink to="/deals">案件管理</NavLink>
          <NavLink to="/orders">注文管理</NavLink>
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
