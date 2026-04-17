import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import CustomersPage from "./pages/CustomersPage";
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
import ComingSoonPage from "./pages/ComingSoonPage";
import "./App.css";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
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
            <Route path="/staff" element={<TeamsPage />} />
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
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
