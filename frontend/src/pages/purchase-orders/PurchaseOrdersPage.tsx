import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { auth } from "../../lib/firebase";
import { usePermissions } from "../../hooks/usePermissions";
import { PageLayout } from "../../components/PageLayout";
import PurchaseOrdersFormModal, { POLineItem } from "./PurchaseOrdersFormModal";

// 在庫表（InventoryPage）の複数選択から渡される商品（ADR-093 Phase 2b）。
interface SelectedProduct {
  product_id: number;
  product_name: string;
  unit_price: number | null;
  condition?: string;
  unit?: string | null;
  supplier_id?: number;
  supplier_name?: string | null;
}

interface PO {
  id: number;
  po_number: string | null;
  supplier_id: number;
  status: string;
  total_amount: number | null;
  ordered_at: string | null;
  received_at: string | null;
  created_at: string;
}

export default function PurchaseOrdersPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [pos, setPos] = useState<PO[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(true);
  const [showNewModal, setShowNewModal] = useState(false);
  // 在庫表からの前埋め（仕入元 + 明細）。null = 新規発注ボタン経由（空フォーム）。
  const [poInitial, setPoInitial] = useState<{ supplierId: number | ""; items: POLineItem[] } | null>(null);
  const location = useLocation();
  const navigate = useNavigate();

  // 在庫表の複数選択 → 発注書作成（ADR-093 Phase 2b）。
  // 発注書は仕入元単位のため、先頭仕入元分のみで前埋めし、他仕入元があれば注意表示。
  useEffect(() => {
    const sel = (location.state as { selectedProducts?: SelectedProduct[] } | null)?.selectedProducts;
    if (!sel || sel.length === 0) return;
    const firstSupplier = sel.find((s) => s.supplier_id != null)?.supplier_id ?? "";
    const sameSupplier = sel.filter((s) => (s.supplier_id ?? "") === firstSupplier);
    const otherSupplierNames = Array.from(
      new Set(
        sel
          .filter((s) => (s.supplier_id ?? "") !== firstSupplier)
          .map((s) => s.supplier_name ?? `#${s.supplier_id}`),
      ),
    );
    const items: POLineItem[] = sameSupplier.map((s) => ({
      product_id: s.product_id,
      product_name: s.product_name,
      quantity: 1,
      unit_cost: s.unit_price ?? 0,
    }));
    setPoInitial({ supplierId: firstSupplier === "" ? "" : Number(firstSupplier), items });
    setShowNewModal(true);
    if (otherSupplierNames.length > 0) {
      setInfo(t("purchaseOrders.fromInventoryMultiSupplier", { count: otherSupplierNames.length }));
    }
    // 二重発火防止: 消費した state をクリア
    navigate(location.pathname, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const STATUS_LABELS: Record<string, string> = {
    draft: t("purchaseOrders.status_draft"),
    ordered: t("purchaseOrders.status_ordered"),
    received: t("purchaseOrders.status_received"),
    cancelled: t("purchaseOrders.status_cancelled"),
    // Sprint 8: メール送信失敗時の状態 (AC8.5)
    error: t("purchaseOrders.status_error"),
  };

  const load = async () => {
    try {
      setPos(await api.get<PO[]>(`/purchase-orders${statusFilter ? `?status=${statusFilter}` : ""}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.fetchError"));
    } finally {
      setLoading(false);
    }
  };
  // load の依存は statusFilter のみ。load は state setter とブラウザ API のみで
  // 純粋な API fetch のため、再構築せず statusFilter 変化時に再読込する。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [statusFilter]);

  const doAction = async (id: number, action: string) => {
    setError("");
    setInfo("");
    try {
      await api.post(`/purchase-orders/${id}/${action}`, {});
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  /** Sprint 8 / AC8.1: PDF ダウンロード。Firebase ID token を取得して fetch で blob を受信。 */
  const downloadPdf = async (id: number, poNumber: string | null) => {
    setError("");
    try {
      const user = auth.currentUser;
      const token = user ? await user.getIdToken() : null;
      const resp = await fetch(`/api/v1/purchase-orders/${id}/pdf`, {
        method: "GET",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!resp.ok) {
        throw new Error(t("purchaseOrders.pdfDownloadFailed", { status: resp.status }));
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${poNumber || `PO-${id}`}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("common.operationError"));
    }
  };

  /** Sprint 8 / AC8.2: メール送信。 */
  const sendEmail = async (id: number) => {
    setError("");
    setInfo("");
    try {
      await api.post(`/purchase-orders/${id}/send-email`, {});
      setInfo(t("purchaseOrders.emailSent"));
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("purchaseOrders.emailSendFailed"));
      load();
    }
  };

  /** Sprint 8 / AC8.5: 再送 (error 状態のみ)。 */
  const resendEmail = async (id: number) => {
    setError("");
    setInfo("");
    try {
      await api.post(`/purchase-orders/${id}/resend-email`, {});
      setInfo(t("purchaseOrders.emailResent"));
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("purchaseOrders.emailSendFailed"));
      load();
    }
  };

  const statusBadgeClass = (status: string): string => {
    switch (status) {
      case "received":
        return "badge-won";
      case "cancelled":
        return "badge-lost";
      case "ordered":
        return "badge-negotiating";
      case "error":
        return "badge-lost"; // 失敗は赤系で目立たせる
      default:
        return "badge-pending";
    }
  };

  return (
    <PageLayout
      navKey="nav.purchaseOrders"
      subtitleKey="purchaseOrders.subtitle"
      headerAction={hasPermission("purchase_orders.create") ? (
        <div className="page-header-actions">
          <button className="btn-primary" data-testid="po-new-btn" onClick={() => { setPoInitial(null); setShowNewModal(true); }}>
            {t("purchaseOrders.newPO")}
          </button>
        </div>
      ) : undefined}
    >
      <PurchaseOrdersFormModal
        open={showNewModal}
        onClose={() => setShowNewModal(false)}
        onCreated={() => { setInfo(t("purchaseOrders.createdInfo")); load(); }}
        initialSupplierId={poInitial?.supplierId}
        initialItems={poInitial?.items}
      />
      <div className="filter-bar">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
          <option value="">{t("purchaseOrders.allStatuses")}</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      {error && <div className="error-message">{error}</div>}
      {info && <div className="info-message" data-testid="po-info">{info}</div>}
      {loading ? <div className="loading">{t("common.loading")}</div> : (
        <table className="data-table" data-testid="purchase-orders-table">
          <thead>
            <tr>
              <th>{t("purchaseOrders.poNumber")}</th>
              <th>{t("common.amount")}</th>
              <th>{t("common.status")}</th>
              <th>{t("purchaseOrders.orderedAt")}</th>
              <th>{t("purchaseOrders.receivedAt")}</th>
              <th>{t("common.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {pos.map(p => (
              <tr key={p.id} data-testid={`po-row-${p.id}`}>
                <td className="mono">{p.po_number || "-"}</td>
                <td>{p.total_amount != null ? `¥${Number(p.total_amount).toLocaleString()}` : "-"}</td>
                <td>
                  <span className={`badge ${statusBadgeClass(p.status)}`} data-testid={`po-status-${p.id}`}>
                    {STATUS_LABELS[p.status] || p.status}
                  </span>
                </td>
                <td>{p.ordered_at ? new Date(p.ordered_at).toLocaleDateString() : "-"}</td>
                <td>{p.received_at ? new Date(p.received_at).toLocaleDateString() : "-"}</td>
                <td className="actions">
                  {p.status === "draft" && hasPermission("purchase_orders.update") && (
                    <button className="btn-sm btn-primary" onClick={() => doAction(p.id, "order")}>{t("purchaseOrders.actionOrder")}</button>
                  )}
                  {p.status === "ordered" && hasPermission("purchase_orders.receive") && (
                    <button className="btn-sm btn-primary" onClick={() => doAction(p.id, "receive")}>{t("purchaseOrders.actionReceive")}</button>
                  )}
                  {(p.status === "draft" || p.status === "ordered") && (
                    <button className="btn-sm btn-danger" onClick={() => doAction(p.id, "cancel")}>{t("purchaseOrders.actionCancel")}</button>
                  )}
                  {/* Sprint 8: PDF / メール / 再送 (ordered 以降で有効) */}
                  {(p.status === "ordered" || p.status === "received" || p.status === "error") && hasPermission("purchase_orders.view") && (
                    <button
                      className="btn-sm btn-secondary"
                      data-testid={`po-pdf-${p.id}`}
                      onClick={() => downloadPdf(p.id, p.po_number)}
                    >
                      {t("purchaseOrders.actionDownloadPdf")}
                    </button>
                  )}
                  {(p.status === "ordered" || p.status === "received") && hasPermission("purchase_orders.update") && (
                    <button
                      className="btn-sm btn-secondary"
                      data-testid={`po-send-email-${p.id}`}
                      onClick={() => sendEmail(p.id)}
                    >
                      {t("purchaseOrders.actionSendEmail")}
                    </button>
                  )}
                  {p.status === "error" && hasPermission("purchase_orders.update") && (
                    <button
                      className="btn-sm btn-primary"
                      data-testid={`po-resend-email-${p.id}`}
                      onClick={() => resendEmail(p.id)}
                    >
                      {t("purchaseOrders.actionResendEmail")}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {pos.length === 0 && <tr><td colSpan={6} className="empty">{t("purchaseOrders.noPos")}</td></tr>}
          </tbody>
        </table>
      )}
    </PageLayout>
  );
}
