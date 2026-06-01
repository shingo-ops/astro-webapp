/**
 * 会社詳細 — 担当者タブ。
 * 担当者の追加・編集・削除をインラインモーダルで行う。
 */

import { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { Company, Contact, ContactFormState } from "./company-detail.types";

interface Props {
  company: Company;
  contacts: Contact[];
  canEdit: boolean;
  contactModalOpen: boolean;
  contactForm: ContactFormState;
  setContactForm: (f: ContactFormState) => void;
  contactSubmitting: boolean;
  setContactDeleteTarget: (c: Contact | null) => void;
  openContactNew: () => void;
  openContactEdit: (c: Contact) => void;
  handleContactSubmit: (e: FormEvent) => void;
  onCloseModal: () => void;
}

export function CompanyContactsTab({
  contacts, canEdit,
  contactModalOpen, contactForm, setContactForm, contactSubmitting,
  setContactDeleteTarget,
  openContactNew, openContactEdit,
  handleContactSubmit, onCloseModal,
}: Props) {
  const { t } = useTranslation();

  const contactName = (c: Contact) =>
    c.display_name || `${c.surname || ""} ${c.given_name || ""}`.trim() || "-";

  return (
    <div>
      {canEdit && (
        <div style={{ marginBottom: "var(--space-3)" }}>
          <button className="btn-sm" onClick={openContactNew}>
            + {t("contacts.newContact")}
          </button>
        </div>
      )}

      {contacts.length === 0 ? (
        <p>{t("contacts.noContacts")}</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("common.name")}</th>
              <th>{t("contacts.position")}</th>
              <th>{t("contacts.isPrimary")}</th>
              <th>{t("common.email")}</th>
              <th>{t("common.phone")}</th>
              <th>{t("common.status")}</th>
              {canEdit && <th>{t("common.actions")}</th>}
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id}>
                <td>{contactName(c)}</td>
                <td>{c.job_title || "-"}</td>
                <td>{c.is_primary_contact ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : ""}</td>
                <td>{c.primary_email || "-"}</td>
                <td>{c.primary_phone || "-"}</td>
                <td><span className={`status-badge status-${c.status}`}>{c.status}</span></td>
                {canEdit && (
                  <td>
                    <button className="btn-sm" onClick={() => openContactEdit(c)}>
                      {t("common.edit")}
                    </button>
                    <button className="btn-sm btn-danger" onClick={() => setContactDeleteTarget(c)}>
                      {t("common.delete")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* 追加・編集モーダル */}
      {contactModalOpen && (
        <div className="modal-overlay" onClick={onCloseModal}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>{contactForm.id === null ? t("contacts.newContact") : t("contacts.editContact")}</h3>
            <form onSubmit={handleContactSubmit}>
              <div className="form-grid">
                <div className="form-row">
                  <label>{t("contacts.displayName")}</label>
                  <input
                    value={contactForm.display_name}
                    onChange={(e) => setContactForm({ ...contactForm, display_name: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("contacts.surname")}</label>
                  <input
                    value={contactForm.surname}
                    onChange={(e) => setContactForm({ ...contactForm, surname: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("contacts.givenName")}</label>
                  <input
                    value={contactForm.given_name}
                    onChange={(e) => setContactForm({ ...contactForm, given_name: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("contacts.position")}</label>
                  <input
                    value={contactForm.job_title}
                    onChange={(e) => setContactForm({ ...contactForm, job_title: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("contacts.department")}</label>
                  <input
                    value={contactForm.department}
                    onChange={(e) => setContactForm({ ...contactForm, department: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("common.email")}</label>
                  <input
                    type="email"
                    value={contactForm.primary_email}
                    onChange={(e) => setContactForm({ ...contactForm, primary_email: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("common.phone")}</label>
                  <input
                    value={contactForm.primary_phone}
                    onChange={(e) => setContactForm({ ...contactForm, primary_phone: e.target.value })}
                  />
                </div>
                <div className="form-row">
                  <label>{t("common.status")}</label>
                  <select
                    value={contactForm.status}
                    onChange={(e) => setContactForm({ ...contactForm, status: e.target.value })}
                  >
                    <option value="active">active</option>
                    <option value="inactive">inactive</option>
                    <option value="archived">archived</option>
                  </select>
                </div>
                <div className="form-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={contactForm.is_primary_contact}
                      onChange={(e) => setContactForm({ ...contactForm, is_primary_contact: e.target.checked })}
                    />
                    {" "}{t("contacts.isPrimary")}
                  </label>
                </div>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn-sm" onClick={onCloseModal}>
                  {t("common.cancel")}
                </button>
                <button type="submit" className="btn-sm btn-primary" disabled={contactSubmitting}>
                  {contactSubmitting ? t("common.saving") : t("common.save")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
