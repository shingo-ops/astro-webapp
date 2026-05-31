/**
 * 受注管理ページ（ADR-021）。
 *
 * このファイルはオーケストレーターのみ。ロジックは useOrdersState、
 * UI は OrdersFilterBar / OrdersFormModal / OrdersTable に分割済み。
 */

import { useTranslation } from "react-i18next";
import { PageLayout } from "../../components/PageLayout";
import { usePermissions } from "../../hooks/usePermissions";
import ConfirmModal from "../../components/ConfirmModal";
import OrderFinancialPanel from "../../components/OrderFinancialPanel";
import ShippingDetailPanel from "../../components/ShippingDetailPanel";
import PurchaseDetailPanel from "../../components/PurchaseDetailPanel";
import CommissionPanel from "../../components/CommissionPanel";
import { useOrdersState } from "./useOrdersState";
import { OrdersFilterBar } from "./OrdersFilterBar";
import { OrdersFormModal } from "./OrdersFormModal";
import { OrdersTable } from "./OrdersTable";
import { emptyForm } from "./orders.types";

export default function OrdersPage() {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const state = useOrdersState();
  const {
    orders, groupCounts, companies,
    statusFilter, setStatusFilter,
    searchInput, setSearchInput,
    sortBy, setSortBy,
    sortOrder, toggleSortOrder,
    showForm, setShowForm,
    editId, setEditId,
    form, setForm,
    companyId, setCompanyId,
    contactId, setContactId,
    selectorError, error, loading,
    deleteTarget, setDeleteTarget,
    financialTarget, setFinancialTarget,
    financials, setFinancials,
    shippingTarget, setShippingTarget,
    shippings, setShippings,
    purchaseTarget, setPurchaseTarget,
    purchases, setPurchases,
    commissionTarget, setCommissionTarget,
    commissionTotals, setCommissionTotals,
    STATUS_LABELS, SORT_OPTIONS,
    loadOrders, loadGroupCounts,
    handleSubmit, handleEdit, performDelete,
    companyDisplay, resetSelector,
  } = state;

  const newOrderButton = hasPermission("orders.create") ? (
    <div className="page-header-actions">
      <button
        className="btn-primary"
        onClick={() => {
          setShowForm(true);
          setEditId(null);
          setForm(emptyForm);
          resetSelector();
        }}
      >
        {t("orders.newOrder")}
      </button>
    </div>
  ) : null;

  return (
    <PageLayout navKey="nav.orders" subtitleKey="orders.subtitle" headerAction={newOrderButton}>
      <OrdersFilterBar
        statusFilter={statusFilter}
        setStatusFilter={setStatusFilter}
        searchInput={searchInput}
        setSearchInput={setSearchInput}
        sortBy={sortBy}
        setSortBy={setSortBy}
        sortOrder={sortOrder}
        toggleSortOrder={toggleSortOrder}
        groupCounts={groupCounts}
        STATUS_LABELS={STATUS_LABELS}
        SORT_OPTIONS={SORT_OPTIONS}
      />

      {error && <div className="error-message">{error}</div>}

      <OrdersFormModal
        showForm={showForm}
        setShowForm={setShowForm}
        editId={editId}
        form={form}
        setForm={setForm}
        companyId={companyId}
        setCompanyId={setCompanyId}
        contactId={contactId}
        setContactId={setContactId}
        selectorError={selectorError}
        companies={companies}
        STATUS_LABELS={STATUS_LABELS}
        handleSubmit={handleSubmit}
      />

      {loading ? (
        <div className="loading">{t("common.loading")}</div>
      ) : (
        <OrdersTable
          orders={orders}
          financials={financials}
          shippings={shippings}
          purchases={purchases}
          commissionTotals={commissionTotals}
          panelOpeners={{ setFinancialTarget, setShippingTarget, setPurchaseTarget, setCommissionTarget }}
          STATUS_LABELS={STATUS_LABELS}
          companyDisplay={companyDisplay}
          handleEdit={handleEdit}
          setDeleteTarget={setDeleteTarget}
        />
      )}

      {financialTarget && (
        <OrderFinancialPanel
          orderId={financialTarget.id}
          orderNumber={financialTarget.order_number}
          onClose={() => setFinancialTarget(null)}
          onSaved={(saved) => {
            setFinancials((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {shippingTarget && (
        <ShippingDetailPanel
          orderId={shippingTarget.id}
          orderNumber={shippingTarget.order_number}
          onClose={() => setShippingTarget(null)}
          onSaved={(saved) => {
            setShippings((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {purchaseTarget && (
        <PurchaseDetailPanel
          orderId={purchaseTarget.id}
          orderNumber={purchaseTarget.order_number}
          onClose={() => setPurchaseTarget(null)}
          onSaved={(saved) => {
            setPurchases((prev) => ({ ...prev, [saved.order_id]: saved }));
          }}
        />
      )}

      {commissionTarget && (
        <CommissionPanel
          orderId={commissionTarget.id}
          orderNumber={commissionTarget.order_number}
          onClose={() => setCommissionTarget(null)}
          onSaved={(bundle) => {
            const total = Object.values(bundle.commissions).reduce(
              (acc, c) => acc + (c ? Number(c.calculated_amount) || 0 : 0),
              0,
            );
            setCommissionTotals((prev) => ({ ...prev, [bundle.order_id]: total }));
          }}
        />
      )}

      <ConfirmModal
        open={!!deleteTarget}
        title={t("orders.deleteOrder")}
        message={
          <>
            {t("orders.orderNumber")}: <strong>{deleteTarget?.order_number}</strong>
            <br />
            {t("common.irreversible")}
          </>
        }
        confirmLabel={t("common.delete")}
        danger
        onConfirm={performDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </PageLayout>
  );
}
