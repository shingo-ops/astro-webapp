/**
 * 住所追加・編集モーダル。
 * addrPhoneError / addrModalError / addrSubmitting はモーダル内ローカル状態で管理。
 */

import { useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { AddressFormState, Company } from "./company-detail.types";
import { addressFromApi, typeLabel, PHONE_RE } from "./company-detail.types";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  addrForm: AddressFormState;
  setAddrForm: (form: AddressFormState) => void;
  submitAddresses: (next: AddressFormState[]) => Promise<void>;
  company: Company;
  canEdit: boolean;
  handleAddressTypeChange: (newType: "billing" | "delivery") => void;
}

export function CompanyAddressModal({
  isOpen, onClose, addrForm, setAddrForm,
  submitAddresses, company, canEdit, handleAddressTypeChange,
}: Props) {
  const { t } = useTranslation();
  const [addrSubmitting, setAddrSubmitting] = useState(false);
  const [addrPhoneError, setAddrPhoneError] = useState<string | null>(null);
  const [addrModalError, setAddrModalError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setAddrModalError(null);
    // クライアント電話番号バリデーション
    if (addrForm.telephone) {
      const cleaned = addrForm.telephone.replace(/[\s\-()]/g, "");
      if (!PHONE_RE.test(cleaned)) {
        setAddrPhoneError(t("companies.phoneError"));
        return;
      }
    }
    setAddrPhoneError(null);
    // F5: country_code は空 or 2 文字のみ許容
    if (addrForm.country_code && addrForm.country_code.length !== 2) {
      setAddrModalError(t("companies.countryCodeError"));
      return;
    }
    setAddrSubmitting(true);
    try {
      const currentForms = (company.addresses || []).map(addressFromApi);
      let next: AddressFormState[];
      if (addrForm.id === null) {
        next = [...currentForms, addrForm];
      } else {
        next = currentForms.map((a) => (a.id === addrForm.id ? addrForm : a));
      }
      await submitAddresses(next);
      onClose();
    } catch (err) {
      setAddrModalError(err instanceof Error ? err.message : t("common.saveError"));
    } finally {
      setAddrSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content-wide" onClick={(e) => e.stopPropagation()}>
        {/* eslint-disable-next-line no-restricted-syntax */}
        <h2>
          {addrForm.id === null
            ? `${typeLabel(t, addrForm.address_type)}${t("companies.address")}を${t("common.add")}`
            : `${typeLabel(t, addrForm.address_type)}${t("companies.address")}を${t("common.edit")}`}
        </h2>
        {/* F6: モーダル内エラー（page top の error-banner は overlay で隠れる） */}
        {addrModalError && <div className="error-banner">{addrModalError}</div>}
        <form onSubmit={handleSave} className="form-grid">
          <div className="form-row">
            <label>{t("common.type")}</label>
            <select disabled={!canEdit || addrSubmitting} value={addrForm.address_type}
              onChange={(e) => handleAddressTypeChange(e.target.value as "billing" | "delivery")}>
              <option value="billing">{t("companies.billing")}</option>
              <option value="delivery">{t("companies.delivery")}</option>
            </select>
          </div>
          <div className="form-row">
            <label>{t("companies.branchNameHint")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.branch_name}
              onChange={(e) => setAddrForm({ ...addrForm, branch_name: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("companies.contactName")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.name}
              onChange={(e) => setAddrForm({ ...addrForm, name: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("common.email")}</label>
            <input type="email" disabled={!canEdit || addrSubmitting} value={addrForm.email}
              onChange={(e) => setAddrForm({ ...addrForm, email: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("common.phone")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.telephone}
              onChange={(e) => setAddrForm({ ...addrForm, telephone: e.target.value })} />
            {addrPhoneError && <span className="field-error">{addrPhoneError}</span>}
          </div>
          <div className="form-row"><label>{t("companies.taxId")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.tax_id}
              onChange={(e) => setAddrForm({ ...addrForm, tax_id: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.address1")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_1}
              onChange={(e) => setAddrForm({ ...addrForm, address_line_1: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.address2")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_2}
              onChange={(e) => setAddrForm({ ...addrForm, address_line_2: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.address3")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.address_line_3}
              onChange={(e) => setAddrForm({ ...addrForm, address_line_3: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.city")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.city}
              onChange={(e) => setAddrForm({ ...addrForm, city: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.stateCode")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.state}
              onChange={(e) => setAddrForm({ ...addrForm, state: e.target.value })} />
          </div>
          <div className="form-row"><label>{t("shipping.zipCode")}</label>
            <input disabled={!canEdit || addrSubmitting} value={addrForm.zip}
              onChange={(e) => setAddrForm({ ...addrForm, zip: e.target.value })} />
          </div>
          <div className="form-row">
            <label>{t("shipping.countryCode")}{t("companies.countryCodeHint")}</label>
            <input maxLength={2} disabled={!canEdit || addrSubmitting} value={addrForm.country_code}
              onChange={(e) => setAddrForm({ ...addrForm, country_code: e.target.value.toUpperCase() })} />
          </div>
          <div className="form-row">
            <label>
              <input type="checkbox" disabled={!canEdit || addrSubmitting} checked={addrForm.is_default}
                onChange={(e) => setAddrForm({ ...addrForm, is_default: e.target.checked })} />
              {" "}{t("companies.setAsDefault")}
            </label>
          </div>
          <div className="form-actions">
            <button type="button" onClick={onClose} disabled={addrSubmitting}>{t("common.cancel")}</button>
            <button type="submit" className="btn-primary" disabled={!canEdit || addrSubmitting}>
              {addrSubmitting ? t("common.saving") : t("common.save")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
