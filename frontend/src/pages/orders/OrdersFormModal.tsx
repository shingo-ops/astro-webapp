/**
 * 受注管理 — 新規作成 / 編集モーダル。
 */

import { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import CompanyContactSelector from "../../components/CompanyContactSelector";
import type { CompanyMini } from "./orders.types";
import { STATUSES } from "./orders.types";

interface Props {
  showForm: boolean;
  setShowForm: (v: boolean) => void;
  editId: number | null;
  form: {
    deal_id: string;
    order_number: string;
    total_amount: string;
    status: string;
    notes: string;
  };
  setForm: (f: Props["form"]) => void;
  companyId: number | null;
  setCompanyId: (v: number | null) => void;
  contactId: number | null;
  setContactId: (v: number | null) => void;
  selectorError: string;
  companies: CompanyMini[];
  STATUS_LABELS: Record<string, string>;
  handleSubmit: (e: FormEvent) => void;
}

export function OrdersFormModal({
  showForm, setShowForm, editId,
  form, setForm,
  companyId, setCompanyId,
  contactId, setContactId,
  selectorError, companies,
  STATUS_LABELS, handleSubmit,
}: Props) {
  const { t } = useTranslation();

  if (!showForm) return null;

  return (
    <div className="modal-overlay" onClick={() => setShowForm(false)}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>{editId ? t("orders.editOrder") : t("orders.newOrder")}</h3>
        <form onSubmit={handleSubmit}>
          <CompanyContactSelector
            value={{ companyId, contactId }}
            onChange={({ companyId: c, contactId: ct }) => {
              setCompanyId(c);
              setContactId(ct);
            }}
            required={!editId}
            disabled={editId !== null}
            error={selectorError}
            companies={companies}
          />
          {editId && (
            <p style={{ fontSize: "var(--font-sm)", color: "var(--text-secondary)", marginTop: -8 }}>
              {t("common.irreversible")}
            </p>
          )}
          <div className="form-group">
            <label>{t("orders.orderNumber")} *</label>
            <input
              required
              value={form.order_number}
              onChange={(e) => setForm({ ...form, order_number: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>{t("common.amount")}</label>
            <input
              type="number" min="0" step="1"
              value={form.total_amount}
              onChange={(e) => setForm({ ...form, total_amount: e.target.value })}
            />
          </div>
          <div className="form-group">
            <label>{t("common.status")}</label>
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{STATUS_LABELS[s]}</option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label>{t("common.notes")}</label>
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </div>
          <div className="form-actions">
            <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
              {t("common.cancel")}
            </button>
            <button type="submit" className="btn-primary">
              {editId ? t("common.update") : t("common.register")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
