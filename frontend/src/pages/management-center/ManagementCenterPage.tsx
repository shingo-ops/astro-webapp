/**
 * 管理センター（Management Center）
 *
 * Google Admin / macOS System Settings 方式の管理ハブ。
 * 左サブナビ + 右コンテンツ（Outlet）のシェル構造。
 * ロール・権限に基づいてサブナビ項目を表示制御する。
 *
 * ルート: /management-center/*
 *
 * 変更履歴:
 *   2026-05-25: 初版作成（ADR-069 管理センター一元化）
 */

import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PageLayout } from "../../components/PageLayout";
import { usePermissions } from "../../hooks/usePermissions";
import { useSuperAdmin } from "../../hooks/useSuperAdmin";
import type { NavItem, NavSection } from "../../types/nav";
import "./ManagementCenterPage.css";

/** 権限フィルタリング前の生アイテム（このファイル内のみで使用） */
interface RawNavItem extends NavItem {
  visible: boolean;
}

export default function ManagementCenterPage() {
  const { t } = useTranslation();
  const { hasPermission, hasAny } = usePermissions();
  const { isSuperAdmin } = useSuperAdmin();

  const rawSections: { key: string; titleKey: string; items: RawNavItem[] }[] = [
    {
      key: "team",
      titleKey: "managementCenter.sectionTeam",
      items: [
        { to: "teams",  labelKey: "nav.teams",  visible: hasPermission("teams.view") },
        { to: "staff",  labelKey: "nav.staff",  visible: hasPermission("staff.view") },
        { to: "shifts", labelKey: "nav.shifts", visible: hasPermission("shifts.view") },
      ],
    },
    {
      key: "security",
      titleKey: "managementCenter.sectionSecurity",
      items: [
        {
          to: "roles",
          labelKey: "nav.rolesPermissions",
          visible: hasAny("roles.view", "roles.create"),
        },
        {
          to: "inventory-visibility",
          labelKey: "nav.inventoryVisibility",
          visible: hasPermission("tenant.inventory_visibility.edit"),
        },
      ],
    },
    {
      key: "business",
      titleKey: "managementCenter.sectionBusiness",
      items: [
        { to: "commission",    labelKey: "nav.commissionSettings", visible: hasPermission("orders.view") },
        { to: "tenant-profile", labelKey: "nav.tenantProfile",
          visible: hasAny("tenant.profile.edit", "tenant.profile.view") },
        { to: "channels",      labelKey: "nav.channels", visible: hasPermission("channels.view") },
        { to: "bots",          labelKey: "nav.bots",     visible: hasPermission("bots.view") },
      ],
    },
    {
      key: "data",
      titleKey: "managementCenter.sectionData",
      items: [
        { to: "companies",      labelKey: "nav.companies",      visible: hasPermission("customers.view") },
        { to: "deals",          labelKey: "nav.deals",          visible: hasPermission("deals.view") },
        { to: "suppliers",      labelKey: "nav.suppliers",      visible: hasPermission("suppliers.view") },
        { to: "purchase-orders", labelKey: "nav.purchaseOrders", visible: hasPermission("purchase_orders.view") },
        { to: "data",           labelKey: "nav.dataManagement", visible: hasPermission("erp.view") },
      ],
    },
    {
      key: "superAdmin",
      titleKey: "managementCenter.sectionSuperAdmin",
      items: [
        { to: "super-admin/masters", labelKey: "nav.superAdminMasters",    visible: isSuperAdmin },
        { to: "super-admin/inbound", labelKey: "nav.superAdminInbound",    visible: isSuperAdmin },
        { to: "super-admin/phase",   labelKey: "nav.superAdminPhaseSwitch", visible: isSuperAdmin },
      ],
    },
  ];

  // 権限フィルタリングして共有型 NavSection[] に変換
  const sections: NavSection[] = rawSections
    .map((s) => ({ key: s.key, titleKey: s.titleKey, items: s.items.filter((i) => i.visible) }))
    .filter((s) => s.items.length > 0);

  return (
    <PageLayout navKey="nav.managementCenter" noScroll>
      <div className="mc-shell">
        {/* 左サブナビ */}
        <nav className="mc-subnav" aria-label={t("nav.managementCenter")}>
          {sections.map((section) => (
            <div key={section.key} className="mc-subnav-section">
              <span className="mc-subnav-title">{t(section.titleKey)}</span>
              {section.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `mc-subnav-item${isActive ? " active" : ""}`
                    }
                  >
                    {t(item.labelKey)}
                  </NavLink>
              ))}
            </div>
          ))}
        </nav>

        {/* 右コンテンツ（子ルートが展開される） */}
        <div className="mc-content">
          <Outlet />
        </div>
      </div>
    </PageLayout>
  );
}
