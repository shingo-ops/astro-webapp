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
            <Route path="/customers" element={<CustomersPage />} />
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/deals" element={<DealsPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/teams" element={<TeamsPage />} />
            <Route path="/roles" element={<RolesPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
