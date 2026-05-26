/**
 * 会社詳細 — 住所タブ（請求先・配送先）。
 */

import { useTranslation } from "react-i18next";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { CompanyAddress } from "./company-detail.types";
import { addressDisplay, typeLabel } from "./company-detail.types";

interface Props {
  billingAddresses: CompanyAddress[];
  deliveryAddresses: CompanyAddress[];
  canEdit: boolean;
  openAddressNew: (type: "billing" | "delivery") => void;
  openAddressEdit: (a: CompanyAddress) => void;
  setAddrDeleteTarget: (a: CompanyAddress | null) => void;
}

function AddressTable({
  addresses, canEdit, openAddressEdit, setAddrDeleteTarget,
}: {
  addresses: CompanyAddress[];
  canEdit: boolean;
  openAddressEdit: (a: CompanyAddress) => void;
  setAddrDeleteTarget: (a: CompanyAddress | null) => void;
}) {
  const { t } = useTranslation();
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>{t("companies.branchName")}</th>
          <th>{t("companies.contactName")}</th>
          <th>{t("common.email")}</th>
          <th>{t("common.phone")}</th>
          <th>{t("companies.address")}</th>
          <th>{t("companies.isDefault")}</th>
          <th>{t("common.actions")}</th>
        </tr>
      </thead>
      <tbody>
        {addresses.map((a) => (
          <tr key={a.id}>
            <td>{a.branch_name || "-"}</td>
            <td>{a.name || "-"}</td>
            <td>{a.email || "-"}</td>
            <td>{a.telephone || "-"}</td>
            <td>{addressDisplay(a)}</td>
            <td>{a.is_default ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : ""}</td>
            <td>
              {canEdit && <button className="btn-sm" onClick={() => openAddressEdit(a)}>{t("common.edit")}</button>}
              {canEdit && <button className="btn-sm btn-danger" onClick={() => setAddrDeleteTarget(a)}>{t("common.delete")}</button>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CompanyAddressesTab({
  billingAddresses, deliveryAddresses, canEdit, openAddressNew, openAddressEdit, setAddrDeleteTarget,
}: Props) {
  const { t } = useTranslation();

  return (
    <div>
      {/* eslint-disable-next-line no-restricted-syntax */}
      <h2>
        {typeLabel(t, "billing")}{t("companies.address")} ({billingAddresses.length})
        {canEdit && (
          <button className="btn-sm" style={{ marginLeft: "var(--space-3)" }} onClick={() => openAddressNew("billing")}>
            + {t("common.add")}
          </button>
        )}
      </h2>
      {billingAddresses.length === 0
        ? <p>{t("companies.billing")}{t("companies.address")}{t("common.noData")}</p>
        : <AddressTable addresses={billingAddresses} canEdit={canEdit} openAddressEdit={openAddressEdit} setAddrDeleteTarget={setAddrDeleteTarget} />
      }

      {/* eslint-disable-next-line no-restricted-syntax */}
      <h2 style={{ marginTop: "var(--space-6)" }}>
        {typeLabel(t, "delivery")}{t("companies.address")} ({deliveryAddresses.length})
        {canEdit && (
          <button className="btn-sm" style={{ marginLeft: "var(--space-3)" }} onClick={() => openAddressNew("delivery")}>
            + {t("common.add")}
          </button>
        )}
      </h2>
      {deliveryAddresses.length === 0
        ? <p>{t("companies.delivery")}{t("companies.address")}{t("common.noData")}</p>
        : <AddressTable addresses={deliveryAddresses} canEdit={canEdit} openAddressEdit={openAddressEdit} setAddrDeleteTarget={setAddrDeleteTarget} />
      }
    </div>
  );
}
