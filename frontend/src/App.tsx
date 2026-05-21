import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AuthProvider } from "./contexts/AuthContext";
import { UiPrefsProvider } from "./contexts/UiPrefsContext";
import { LocaleProvider } from "./contexts/LocaleContext";
import { ThemeProvider } from "./contexts/ThemeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import CustomersPage from "./pages/CustomersPage";
import CompaniesPage from "./pages/CompaniesPage";
import CompanyDetailPage from "./pages/CompanyDetailPage";
import ContactsPage from "./pages/ContactsPage";
import DealsPage from "./pages/DealsPage";
import OrdersPage from "./pages/OrdersPage";
import LeadsPage from "./pages/LeadsPage";
import TeamsPage from "./pages/TeamsPage";
import RolesPage from "./pages/RolesPage";
import ProductsPage from "./pages/ProductsPage";
import QuotesPage from "./pages/QuotesPage";
import QuoteCreatePage from "./pages/QuoteCreatePage";
import QuoteDetailPage from "./pages/QuoteDetailPage";
import InvoicesPage from "./pages/InvoicesPage";
import InvoiceDetailPage from "./pages/InvoiceDetailPage";
import SuppliersPage from "./pages/SuppliersPage";
import PurchaseOrdersPage from "./pages/PurchaseOrdersPage";
import NotificationsPage from "./pages/NotificationsPage";
import StaffReportsPage from "./pages/StaffReportsPage";
import ArchivesPage from "./pages/ArchivesPage";
import ShiftsPage from "./pages/ShiftsPage";
import BuddyPage from "./pages/BuddyPage";
import BadgesPage from "./pages/BadgesPage";
import ERPPage from "./pages/ERPPage";
import StaffPage from "./pages/StaffPage";
import BotsPage from "./pages/BotsPage";
import ChannelsPage from "./pages/ChannelsPage";
import OAuthCallbackPage from "./pages/OAuthCallbackPage";
import InboxPage from "./pages/InboxPage";
import ComingSoonPage from "./pages/ComingSoonPage";
// ADR-021 Phase 5 / Sprint 5: 担当者報酬計算 MVP
import CommissionSettingsPage from "./pages/CommissionSettingsPage";
// spec.md v1.1 F2 (Sprint 2): マスタ編集 UI（中央 admin + テナント admin の二層）
import SuperAdminMastersPage from "./pages/super-admin/MastersPage";
import InventoryVisibilityPage from "./pages/admin/InventoryVisibilityPage";
// spec.md v1.1 F8 (Sprint 8): テナント発行者情報 (PO PDF / メール差出人) admin UI
import TenantProfilePage from "./pages/admin/TenantProfilePage";
// spec.md v1.1 F5 (Sprint 5): Discord Inbound 受信メッセージ一覧（中央 admin）
import DiscordInboundPage from "./pages/super-admin/DiscordInboundPage";
import ParseReviewPage from "./pages/super-admin/ParseReviewPage";
import "./App.css";

function App() {
  const { t } = useTranslation();
  // PR #166 F5: UiPrefsProvider は BrowserRouter の内側に配置する。
  //   - useNavigate などの react-router フックを将来 prefs フックから使えるようにする
  //   - インデント階層が PR diff として読みやすくなる
  return (
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

                  {/* リード系 */}
                  <Route path="/leads" element={<LeadsPage />} />
                  <Route path="/customers" element={<CustomersPage />} />
                  {/* Phase 1-B-2 Step 5c-1: 新 B2B モデル（会社 + 担当者） */}
                  <Route path="/companies" element={<CompaniesPage />} />
                  {/* Step 5c-2: 会社詳細ページ（multi_branch 住所編集 + 担当者タブ） */}
                  <Route
                    path="/companies/:id"
                    element={<CompanyDetailPage />}
                  />
                  <Route path="/contacts" element={<ContactsPage />} />
                  {/* Phase 1-D Sprint 4: Meta Inbox UI（左ペイン会話 + 右ペインメッセージ） */}
                  <Route path="/lead-chat" element={<InboxPage />} />
                  <Route path="/archive" element={<ArchivesPage />} />

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

                  {/* Phase 1-D Sprint 3: Meta Inbox 接続管理 */}
                  <Route path="/channels" element={<ChannelsPage />} />
                  {/* Facebook OAuth dialog からの redirect_uri。code/state を backend へ送信し /channels に戻す */}
                  <Route
                    path="/channels/oauth/callback"
                    element={<OAuthCallbackPage />}
                  />

                  {/* 設定 */}
                  <Route path="/settings" element={<NotificationsPage />} />

                  {/* その他 */}
                  <Route path="/knowledge" element={<BuddyPage />} />
                  <Route path="/prompts" element={<BadgesPage />} />
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
                </Route>
              </Routes>
            </ThemeProvider>
          </LocaleProvider>
        </UiPrefsProvider>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
