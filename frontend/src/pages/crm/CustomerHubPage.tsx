/**
 * 顧客管理ハブ（Customer Hub）
 *
 * 管理センターと同パターンの左サブナビ + 右コンテンツ（Outlet）シェル。
 * CRM 関連ページ（リード・会社・担当者・顧客(旧)・アーカイブ）を一元管理する。
 *
 * ルート: /crm/*
 */

import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PageLayout } from "../../components/PageLayout";
import { usePermissions } from "../../hooks/usePermissions";


interface SubNavItem {
  to: string;
  labelKey: string;
  visible: boolean;
}

export default function CustomerHubPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();

  const items: SubNavItem[] = [
    {
      to: "leads",
      labelKey: "nav.leads",
      visible: hasPermission("leads.view"),
    },
    {
      to: "companies",
      labelKey: "nav.companies",
      visible: hasPermission("customers.view"),
    },
    {
      to: "contacts",
      labelKey: "nav.contacts",
      visible: hasPermission("customers.view"),
    },
    {
      to: "customers",
      labelKey: "nav.customers",
      visible: hasPermission("customers.view"),
    },
    {
      to: "archive",
      labelKey: "nav.archive",
      visible:
        hasPermission("leads.view") || hasPermission("customers.view"),
    },
  ];

  const visibleItems = items.filter((i) => i.visible);

  return (
    <PageLayout navKey="nav.leads" noScroll>
      <div className="hub-shell">
        {/* 左サブナビ */}
        <nav className="hub-subnav" aria-label={t("nav.leads")}>
          {visibleItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `hub-subnav-item${isActive ? " active" : ""}`
              }
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>

        {/* 右コンテンツ */}
        <div className="hub-content">
          <Outlet />
        </div>
      </div>
    </PageLayout>
  );
}
