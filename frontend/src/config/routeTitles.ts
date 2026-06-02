/**
 * routeTitles.ts — ページ見出し Single Source of Truth
 *
 * route path → nav i18n key のマッピング。
 * サイドバーラベルとページ見出しを同一キーで管理することでズレを防ぐ。
 *
 * 使い方:
 *   - ページ見出し(h1/h2)は usePageTitle() hook 経由で取得する
 *   - 新規ページ追加時はここに 1 行追加すれば完結
 *   - 詳細ページ (/companies/:id など) はデータ名をそのまま表示するため
 *     このマップには登録しない（各ページで個別に対応）
 */
export const ROUTE_TITLE_KEYS: Record<string, string> = {
  "/":                           "nav.dashboard",
  "/lead-chat":                  "nav.leadChat",
  "/crm/leads":                  "nav.leads",
  "/crm/companies":              "nav.companies",
  "/crm/contacts":               "nav.contacts",
  "/crm/archive":                "nav.archive",
  "/inventory":                  "nav.inventory",
  "/quotes":                     "nav.quotesInvoices",
  "/invoices":                   "nav.quotesInvoices",
  "/reports":                    "nav.reports",
  "/deals":                      "nav.deals",
  "/suppliers":                  "nav.suppliers",
  "/purchase-orders":            "nav.purchaseOrders",
  "/staff":                      "nav.staff",
  "/bots":                       "nav.bots",
  "/teams":                      "nav.teams",
  "/shifts":                     "nav.shifts",
  "/roles":                      "nav.rolesPermissions",
  "/data":                       "nav.dataManagement",
  "/channels":                   "nav.channels",
  "/settings":                   "nav.settings",
  "/commission-settings":        "nav.commissionSettings",
  "/admin/inventory-visibility": "nav.inventoryVisibility",
  "/admin/tenant-profile":       "nav.tenantProfile",
  "/admin/discord-config":       "nav.discordConfig",
  "/admin/discord-announce":     "nav.discordAnnounce",
  "/super-admin/masters":        "nav.superAdminMasters",
  "/super-admin/inbound":        "nav.superAdminInbound",
  "/super-admin/phase-switch":   "nav.superAdminPhaseSwitch",
};
