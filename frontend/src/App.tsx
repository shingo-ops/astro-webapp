import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IconContext } from "@phosphor-icons/react";
import { AuthProvider } from "./contexts/AuthContext";
import { UiPrefsProvider } from "./contexts/UiPrefsContext";
import { LocaleProvider } from "./contexts/LocaleContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import LoginPage from "./pages/login/LoginPage";
import DashboardPage from "./pages/dashboard/DashboardPage";
import GoalSettingPage from "./pages/goal-setting/GoalSettingPage";
import CustomersPage from "./pages/customers/CustomersPage";
import CompaniesPage from "./pages/companies/CompaniesPage";
import CompanyDetailPage from "./pages/company-detail/CompanyDetailPage";
import ContactsPage from "./pages/contacts/ContactsPage";
import DealsPage from "./pages/deals/DealsPage";
import OrdersPage from "./pages/orders/OrdersPage";
import LeadsPage from "./pages/leads/LeadsPage";
import TeamsPage from "./pages/teams/TeamsPage";
import RolesPage from "./pages/roles/RolesPage";
import ProductsPage from "./pages/products/ProductsPage";
import QuotesPage from "./pages/quotes/QuotesPage";
import QuoteCreatePage from "./pages/quote-create/QuoteCreatePage";
import QuoteDetailPage from "./pages/quote-detail/QuoteDetailPage";
import InvoicesPage from "./pages/invoices/InvoicesPage";
import InvoiceDetailPage from "./pages/invoice-detail/InvoiceDetailPage";
import SuppliersPage from "./pages/suppliers/SuppliersPage";
import PurchaseOrdersPage from "./pages/purchase-orders/PurchaseOrdersPage";
import NotificationsPage from "./pages/notifications/NotificationsPage";
import StaffReportsPage from "./pages/staff-reports/StaffReportsPage";
import ArchivesPage from "./pages/archives/ArchivesPage";
import ShiftsPage from "./pages/shifts/ShiftsPage";
import SchedulePage from "./pages/schedule/SchedulePage";
import ERPPage from "./pages/erp/ERPPage";
import StaffPage from "./pages/staff/StaffPage";
import BotsPage from "./pages/bots/BotsPage";
import ChannelsPage from "./pages/channels/ChannelsPage";
import OAuthCallbackPage from "./pages/oauth-callback/OAuthCallbackPage";
import InboxPage from "./pages/inbox/InboxPage";
import ComingSoonPage from "./pages/coming-soon/ComingSoonPage";
// ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
import CommissionSettingsPage from "./pages/commission-settings/CommissionSettingsPage";
// spec.md v1.1 F2 (Sprint 2): マスタ編集 UI（中央 admin + テナント admin の二層）
import SuperAdminMastersPage from "./pages/super-admin/MastersPage";
import InventoryVisibilityPage from "./pages/admin/InventoryVisibilityPage";
// spec.md v1.1 F8 (Sprint 8): テナント発行者情報 (PO PDF / メール差出人) admin UI
import TenantProfilePage from "./pages/admin/TenantProfilePage";
// spec.md v1.1 F5 (Sprint 5): Discord Inbound 受信メッセージ一覧（中央 admin）
import DiscordInboundPage from "./pages/super-admin/DiscordInboundPage";
import ParseReviewPage from "./pages/super-admin/ParseReviewPage";
// spec.md v1.2 F9 (Sprint 9): スプレッドシート並走 Phase 切替 admin UI
import PhaseSwitchPage from "./pages/super-admin/PhaseSwitchPage";
import ManagementCenterPage from "./pages/management-center/ManagementCenterPage";
import AccountSettingsPage from "./pages/account-settings/AccountSettingsPage";
import CustomerHubPage from "./pages/crm/CustomerHubPage";
// ADR-069: デザインシステム パーツ保管庫（開発環境専用）
import DesignSystemPage from "./pages/design-system/DesignSystemPage";
import "./sidebar.css";
import "./topbar.css";
import "./components.css";
import "./pages-layout.css";
import "./company-forms.css";
import "./responsive.css";

function CompanyIdRedirect() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/crm/companies/${id}`} replace />;
}

function App() {
  const { t } = useTranslation();
  // PR #166 F5: UiPrefsProvider は BrowserRouter の内側に配置する。
  //   - useNavigate などの react-router フックを将来 prefs フックから使えるようにする
  //   - インデント階層が PR diff として読みやすくなる
  return (
    <IconContext.Provider value={{ weight: "light" }}>
    <AuthProvider>
      <BrowserRouter>
        <UiPrefsProvider>
          <LocaleProvider>
            <ThemeProvider>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route
                  element={
                    <ProtectedRoute>
                      <Layout />
                    </ProtectedRoute>
                  }
                >
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/goals/settings" element={<GoalSettingPage />} />

                  {/* 旧ルート後方互換リダイレクト（/crm/* ハブへ転送） */}
                  <Route path="/leads"         element={<Navigate to="/crm/leads"     replace />} />
                  <Route path="/customers"     element={<Navigate to="/crm/customers"  replace />} />
                  <Route path="/companies"     element={<Navigate to="/crm/companies"  replace />} />
                  <Route path="/companies/:id" element={<CompanyIdRedirect />} />
                  <Route path="/contacts"      element={<Navigate to="/crm/contacts"   replace />} />
                  <Route path="/archive"       element={<Navigate to="/crm/archive"    replace />} />

                  {/* Phase 1-D Sprint 4: Meta Inbox UI（左ペイン会話 + 右ペインメッセージ） */}
                  <Route path="/lead-chat" element={<InboxPage />} />

                  {/* 顧客管理ハブ: 左サブナビ + 右コンテンツのシェル。権限に基づいて項目を制御 */}
                  <Route path="/crm" element={<CustomerHubPage />}>
                    <Route index element={<Navigate to="/crm/leads" replace />} />
                    {/* Phase 1-B-2 Step 5c-1: 新 B2B モデル（会社 + 担当者） */}
                    <Route path="leads"           element={<LeadsPage />} />
                    <Route path="companies"       element={<CompaniesPage />} />
                    {/* Step 5c-2: 会社詳細ページ（multi_branch 住所編集 + 担当者タブ） */}
                    <Route path="companies/:id"   element={<CompanyDetailPage />} />
                    <Route path="contacts"        element={<ContactsPage />} />
                    <Route path="customers"       element={<CustomersPage />} />
                    <Route path="archive"         element={<ArchivesPage />} />
                  </Route>

                  {/* 在庫 */}
                  <Route path="/inventory" element={<ProductsPage />} />

                  {/* 見積・請求 */}
                  <Route path="/quotes/new" element={<QuoteCreatePage />} />
                  <Route path="/quotes/:id" element={<QuoteDetailPage />} />
                  <Route path="/quotes" element={<QuotesPage />} />
                  <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
                  <Route path="/invoices" element={<InvoicesPage />} />

                  {/* レポート */}
                  <Route path="/reports" element={<StaffReportsPage />} />

                  {/* FAQ */}
                  <Route
                    path="/faq"
                    element={
                      <ComingSoonPage
                        title={t("faq.title")}
                        description={t("faq.description")}
                      />
                    }
                  />

                  {/* 管理 */}
                  <Route path="/deals" element={<DealsPage />} />
                  <Route path="/orders" element={<OrdersPage />} />
                  {/* ADR-021 Phase 5 / Sprint 5: 報酬設定（テナント別 rate 編集） */}
                  <Route
                    path="/commission-settings"
                    element={<CommissionSettingsPage />}
                  />
                  <Route path="/staff" element={<StaffPage />} />
                  <Route path="/bots" element={<BotsPage />} />
                  <Route path="/teams" element={<TeamsPage />} />
                  <Route path="/roles" element={<RolesPage />} />
                  <Route path="/data" element={<ERPPage />} />
                  <Route path="/suppliers" element={<SuppliersPage />} />
                  <Route
                    path="/purchase-orders"
                    element={<PurchaseOrdersPage />}
                  />
                  <Route path="/shifts" element={<ShiftsPage />} />
                  <Route path="/schedule" element={<SchedulePage />} />

                  {/* Phase 1-D Sprint 3: Meta Inbox 接続管理 */}
                  <Route path="/channels" element={<ChannelsPage />} />
                  {/* Facebook OAuth dialog からの redirect_uri。code/state を backend へ送信し /channels に戻す */}
                  <Route
                    path="/channels/oauth/callback"
                    element={<OAuthCallbackPage />}
                  />

                  {/* 設定 */}
                  <Route path="/settings" element={<NotificationsPage />} />
                  {/* 個人アカウント設定 */}
                  <Route path="/account/settings" element={<AccountSettingsPage />} />

                  {/* その他 */}
                  <Route
                    path="/templates"
                    element={
                      <ComingSoonPage
                        title={t("templates.title")}
                        description={t("templates.description")}
                      />
                    }
                  />

                  {/* spec.md v1.1 F2 (Sprint 2): マスタ編集 UI */}
                  {/* 中央 admin（is_super_admin=true のみ。SuperAdminMastersPage 内で 403 ガード） */}
                  <Route
                    path="/super-admin/masters"
                    element={<SuperAdminMastersPage />}
                  />
                  {/* spec.md v1.1 F5 (Sprint 5): Discord Inbound 受信一覧（is_super_admin 限定、Page 内で 403 ガード） */}
                  <Route
                    path="/super-admin/inbound"
                    element={<DiscordInboundPage />}
                  />
                  {/* spec.md v1.1 F6 (Sprint 6): 解析結果レビュー画面（is_super_admin 限定、Page 内で 403 ガード） */}
                  <Route
                    path="/super-admin/inbound/:id/review"
                    element={<ParseReviewPage />}
                  />
                  {/* spec.md v1.2 F9 (Sprint 9): スプレッドシート並走 Phase 切替 (is_super_admin 限定、Page 内で 403 ガード) */}
                  <Route
                    path="/super-admin/phase-switch"
                    element={<PhaseSwitchPage />}
                  />
                  {/* テナント admin（tenant.inventory_visibility.edit 権限が必要、Page 内で 403 ガード） */}
                  <Route
                    path="/admin/inventory-visibility"
                    element={<InventoryVisibilityPage />}
                  />
                  {/* Sprint 8 / F8: テナント admin (tenant.profile.edit / view) */}
                  <Route
                    path="/admin/tenant-profile"
                    element={<TenantProfilePage />}
                  />

                  {/* ADR-069: デザインシステム パーツ保管庫（開発環境専用） */}
                  {import.meta.env.DEV && (
                    <Route path="/design-system" element={<DesignSystemPage />} />
                  )}

                  {/* 管理センター: 左サブナビ + 右コンテンツのシェル。権限に基づいて項目を制御 */}
                  <Route path="/management-center" element={<ManagementCenterPage />}>
                    <Route index element={<Navigate to="staff" replace />} />
                    <Route path="teams"               element={<TeamsPage />} />
                    <Route path="staff"               element={<StaffPage />} />
                    <Route path="shifts"              element={<ShiftsPage />} />
                    <Route path="roles"               element={<RolesPage />} />
                    <Route path="inventory-visibility" element={<InventoryVisibilityPage />} />
                    <Route path="commission"          element={<CommissionSettingsPage />} />
                    <Route path="tenant-profile"      element={<TenantProfilePage />} />
                    <Route path="channels"            element={<ChannelsPage />} />
                    <Route path="bots"                element={<BotsPage />} />
                    <Route path="deals"               element={<DealsPage />} />
                    <Route path="suppliers"           element={<SuppliersPage />} />
                    <Route path="purchase-orders"     element={<PurchaseOrdersPage />} />
                    <Route path="data"                element={<ERPPage />} />
                    <Route path="notifications"       element={<NotificationsPage />} />
                    <Route path="reports"             element={<StaffReportsPage />} />
                    <Route path="super-admin/masters" element={<SuperAdminMastersPage />} />
                    <Route path="super-admin/inbound" element={<DiscordInboundPage />} />
                    <Route path="super-admin/phase"   element={<PhaseSwitchPage />} />
                  </Route>
                </Route>
              </Routes>
            </ThemeProvider>
          </LocaleProvider>
        </UiPrefsProvider>
      </BrowserRouter>
    </AuthProvider>
    </IconContext.Provider>
  );
}

export default App;
