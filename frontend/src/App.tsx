import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import { UiPrefsProvider } from "./contexts/UiPrefsContext";
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
import ComingSoonPage from "./pages/ComingSoonPage";
import "./App.css";

function App() {
  // PR #166 F5: UiPrefsProvider は BrowserRouter の内側に配置する。
  //   - useNavigate などの react-router フックを将来 prefs フックから使えるようにする
  //   - インデント階層が PR diff として読みやすくなる
  return (
    <AuthProvider>
      <BrowserRouter>
        <UiPrefsProvider>
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
              <Route path="/companies/:id" element={<CompanyDetailPage />} />
              <Route path="/contacts" element={<ContactsPage />} />
              <Route path="/lead-chat" element={<ComingSoonPage title="リードチャット" description="Meta統合メッセージ受信トレイ（Webhook基盤実装済み、UI開発中）" />} />
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
              <Route path="/faq" element={<ComingSoonPage title="FAQ" description="ヘルプ・よくある質問" />} />

              {/* 管理 */}
              <Route path="/deals" element={<DealsPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/staff" element={<StaffPage />} />
              <Route path="/bots" element={<BotsPage />} />
              <Route path="/teams" element={<TeamsPage />} />
              <Route path="/roles" element={<RolesPage />} />
              <Route path="/data" element={<ERPPage />} />
              <Route path="/suppliers" element={<SuppliersPage />} />
              <Route path="/purchase-orders" element={<PurchaseOrdersPage />} />
              <Route path="/shifts" element={<ShiftsPage />} />

              {/* 設定 */}
              <Route path="/settings" element={<NotificationsPage />} />

              {/* その他 */}
              <Route path="/knowledge" element={<BuddyPage />} />
              <Route path="/prompts" element={<BadgesPage />} />
              <Route path="/templates" element={<ComingSoonPage title="テンプレート管理" description="メール・メッセージテンプレート管理" />} />
            </Route>
          </Routes>
        </UiPrefsProvider>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
