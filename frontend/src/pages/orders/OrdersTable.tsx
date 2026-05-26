/**
 * 受注管理 — 13 カラムデータテーブル。
 * fmt / fmtRate は useOrdersState からエクスポートされたモジュールレベルユーティリティを使用。
 */

import { useTranslation } from "react-i18next";
import type { OrderListItem } from "./orders.types";
import type { OrderFinancialDto } from "../../components/OrderFinancialPanel";
import type { ShippingDetailDto } from "../../components/ShippingDetailPanel";
import type { PurchaseDetailDto } from "../../components/PurchaseDetailPanel";
import { fmt, fmtRate } from "./useOrdersState";

interface PanelOpeners {
  setFinancialTarget: (o: OrderListItem) => void;
  setShippingTarget: (o: OrderListItem) => void;
  setPurchaseTarget: (o: OrderListItem) => void;
  setCommissionTarget: (o: OrderListItem) => void;
}

interface Props {
  orders: OrderListItem[];
  financials: Record<number, OrderFinancialDto | null>;
  shippings: Record<number, ShippingDetailDto | null>;
  purchases: Record<number, PurchaseDetailDto | null>;
  commissionTotals: Record<number, number>;
  panelOpeners: PanelOpeners;
  STATUS_LABELS: Record<string, string>;
  companyDisplay: (o: OrderListItem) => string;
  handleEdit: (o: OrderListItem) => void;
  setDeleteTarget: (o: OrderListItem) => void;
}

export function OrdersTable({
  orders, financials, shippings, purchases, commissionTotals,
  panelOpeners, STATUS_LABELS, companyDisplay, handleEdit, setDeleteTarget,
}: Props) {
  const { t } = useTranslation();
  const { setFinancialTarget, setShippingTarget, setPurchaseTarget, setCommissionTarget } = panelOpeners;

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>{t("orders.orderNumber")}</th>
          <th>{t("common.company")}</th>
          <th>{t("common.name")}</th>
          <th>{t("common.amount")}</th>
          <th>{t("orders.financial")}</th>
          <th>{t("financial.grossProfit")}</th>
          <th>{t("financial.grossProfitRate")}</th>
          <th>{t("shipping.trackingNumber")}</th>
          <th>{t("orders.purchase")}</th>
          <th>{t("orders.commission")}</th>
          <th>{t("common.status")}</th>
          <th>{t("common.createdAt")}</th>
          <th>{t("common.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => {
          const fin = financials[o.id] ?? null;
          const ship = shippings[o.id] ?? null;
          const pur = purchases[o.id] ?? null;
          return (
            <tr key={o.id}>
              <td>{o.order_number}</td>
              <td>{companyDisplay(o)}</td>
              <td>{o.contact_display_name ?? "-"}</td>
              <td>{o.total_amount ? fmt(o.total_amount) : "-"}</td>
              <td data-testid={`fin-cell-revenue-${o.id}`}>
                {fin && fin.revenue_amount > 0 ? fmt(fin.revenue_amount) : "-"}
              </td>
              <td data-testid={`fin-cell-gross-${o.id}`}>
                {fin ? fmt(fin.gross_profit) : "-"}
              </td>
              <td data-testid={`fin-cell-rate-${o.id}`}>
                {fin ? fmtRate(fin.gross_profit_rate) : "-"}
              </td>
              <td data-testid={`ship-cell-tracking-${o.id}`}>
                {ship && ship.tracking_number ? ship.tracking_number : "-"}
              </td>
              <td data-testid={`pur-cell-status-${o.id}`}>
                {(() => {
                  if (!pur) return <span className="badge">{t("common.notSet")}</span>;
                  if (pur.purchase_status === "confirmed") {
                    return <span className="badge badge-confirmed">{t("purchase.status_confirmed")}</span>;
                  }
                  return <span className="badge badge-pending">{t("purchase.status_pending")}</span>;
                })()}
              </td>
              <td data-testid={`com-cell-total-${o.id}`}>
                {commissionTotals[o.id] ? fmt(commissionTotals[o.id]) : "-"}
              </td>
              <td>
                <span className={`badge badge-${o.status}`}>
                  {STATUS_LABELS[o.status] || o.status}
                </span>
              </td>
              <td>{new Date(o.created_at).toLocaleDateString("ja-JP")}</td>
              <td className="actions">
                <button className="btn-sm" onClick={() => handleEdit(o)}>{t("common.edit")}</button>
                <button className="btn-sm" onClick={() => setFinancialTarget(o)} data-testid={`open-financial-${o.id}`}>
                  {t("orders.financial")}
                </button>
                <button className="btn-sm" onClick={() => setShippingTarget(o)} data-testid={`open-shipping-${o.id}`}>
                  {t("orders.shipping")}
                </button>
                <button className="btn-sm" onClick={() => setPurchaseTarget(o)} data-testid={`open-purchase-${o.id}`}>
                  {t("orders.purchase")}
                </button>
                <button className="btn-sm" onClick={() => setCommissionTarget(o)} data-testid={`open-commission-${o.id}`}>
                  {t("orders.commission")}
                </button>
                <button className="btn-sm btn-danger" onClick={() => setDeleteTarget(o)}>
                  {t("common.delete")}
                </button>
              </td>
            </tr>
          );
        })}
        {orders.length === 0 && (
          <tr>
            <td colSpan={13} className="empty">{t("orders.noOrders")}</td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
