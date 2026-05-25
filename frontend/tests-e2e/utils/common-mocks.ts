/**
 * 共通 API mock セット（Phase 1-E F2-S3）。
 *
 * Layout / AuthContext / UiPrefsContext / usePermissions が初期描画で叩く endpoint:
 *   - GET /api/v1/me/permissions   → メニュー表示権限
 *   - GET /api/v1/staff/me         → UI prefs（dark_mode / show_admin_menu 等）
 *
 * これらは scene 1-7 共通で必要。各 spec で個別 endpoint と一緒に渡す。
 */

import type { MockMap } from "./api-mock";

export const ALL_PERMISSIONS = [
  "dashboard.view",
  "leads.view",
  "customers.view",
  "products.view",
  "quotes.view",
  "quotes.create",
  "invoices.view",
  "deals.view",
  "suppliers.view",
  "purchase_orders.view",
  "staff.view",
  "bots.view",
  "teams.view",
  "shifts.view",
  "roles.view",
  "roles.create",
  "erp.view",
  "channels.view",
  "channels.manage",
  "messages.send",
  "messages.read",
  // Sprint 8 / F8: PO PDF / メール / テナント発行者情報
  "purchase_orders.update",
  "purchase_orders.receive",
  "tenant.profile.view",
  "tenant.profile.edit",
];

export function commonMocks(): MockMap {
  return {
    "GET /me/permissions": {
      permissions: ALL_PERMISSIONS,
    },
    "GET /staff/me": {
      id: 1,
      primary_email: "review@salesanchor.jp",
      ui_preferences: {
        dark_mode: false,
        show_chat_menu: true,
        show_sales_menu: true,
        show_settings_menu: true,
        show_admin_menu: true,
        show_sidebar: true,
      },
    },
  };
}
