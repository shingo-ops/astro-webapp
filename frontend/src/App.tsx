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
            <Route path="/lead-chat" element={
              <ComingSoonPage title="リードチャット"
                description="Meta (WhatsApp/Instagram) 統合メッセージ受信トレイ（Phase 4 予定）" />
            } />
            <Route path="/archive" element={
              <ComingSoonPage title="アーカイブ"
                description="過去の会話ログ・取引履歴のアーカイブ閲覧（Phase 4 予定）" />
            } />

            {/* 在庫 */}
            <Route path="/inventory" element={
              <ComingSoonPage title="在庫管理"
                description="商品在庫の閲覧・在庫同期機能（Phase 2 予定）" />
            } />

            {/* 見積・請求 */}
            <Route path="/quotes/new" element={
              <ComingSoonPage title="見積もり作成"
                description="案件から見積書を作成、PDF 出力（Phase 2 予定）" />
            } />
            <Route path="/quotes" element={
              <ComingSoonPage title="見積もり履歴"
                description="過去に発行した見積もり一覧（Phase 2 予定）" />
            } />
            <Route path="/invoices/new" element={
              <ComingSoonPage title="請求書作成"
                description="承認済み見積もりから請求書を発行、多通貨対応（Phase 2 予定）" />
            } />

            {/* レポート */}
            <Route path="/reports" element={
              <ComingSoonPage title="レポート"
                description="コンバージョン分析、担当者別成績、売上レポート（Phase 3 予定）" />
            } />

            {/* FAQ */}
            <Route path="/faq" element={
              <ComingSoonPage title="FAQ"
                description="ヘルプ・よくある質問（Phase 4 予定）" />
            } />

            {/* 管理 */}
            <Route path="/deals" element={<DealsPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/staff" element={<TeamsPage />} />
            <Route path="/roles" element={<RolesPage />} />
            <Route path="/data" element={
              <ComingSoonPage title="データ管理"
                description="マスターデータのインポート/エクスポート、ERP同期（Phase 5 予定）" />
            } />

            {/* 設定 */}
            <Route path="/settings" element={
              <ComingSoonPage title="設定"
                description="テナント設定、通知、外部連携の管理（Phase 4 予定）" />
            } />

            {/* その他 */}
            <Route path="/knowledge" element={
              <ComingSoonPage title="商材ナレッジ"
                description="商品情報・知識ベース管理（Phase 5 予定）" />
            } />
            <Route path="/prompts" element={
              <ComingSoonPage title="翻訳プロンプト"
                description="AI翻訳プロンプトの管理（Phase 5 予定）" />
            } />
            <Route path="/templates" element={
              <ComingSoonPage title="テンプレート管理"
                description="メール・メッセージテンプレート管理（Phase 4 予定）" />
            } />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
