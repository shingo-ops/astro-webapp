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
import "./ManagementCenterPage.css";

interface SubNavItem {
  to: string;
  labelKey: string;
  visible: boolean;
}

interface SubNavSection {
  key: string;
  titleKey: string;
  items: SubNavItem[];
}

export default function ManagementCenterPage() {
  const { t } = useTranslation();
  const { hasPermission, hasAny } = usePermissions();
  const { isSuperAdmin } = useSuperAdmin();

  const sections: SubNavSection[] = [
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

  const visibleSections = sections.filter((s) =>
    s.items.some((i) => i.visible),
  );

  return (
    <PageLayout navKey="nav.managementCenter" noScroll>
      <div className="mc-shell">
        {/* 左サブナビ */}
        <nav className="mc-subnav" aria-label={t("nav.managementCenter")}>
          {visibleSections.map((section) => (
            <div key={section.key} className="mc-subnav-section">
              <span className="mc-subnav-title">{t(section.titleKey)}</span>
              {section.items
                .filter((i) => i.visible)
                .map((item) => (
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
