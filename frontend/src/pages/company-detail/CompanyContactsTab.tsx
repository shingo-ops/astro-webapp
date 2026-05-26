/**
 * 会社詳細 — 担当者タブ。
 * 編集は ContactsPage で行うため、一覧表示と遷移リンクのみ。
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { STATUS_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";
import type { Company, Contact } from "./company-detail.types";

interface Props {
  company: Company;
  contacts: Contact[];
}

export function CompanyContactsTab({ company, contacts }: Props) {
  const { t } = useTranslation();

  return (
    <div>
      <div style={{ marginBottom: "var(--space-3)" }}>
        <Link to={`/contacts?company_id=${company.id}`} className="btn-sm">
          {t("contacts.title")}{t("common.edit")}
        </Link>
      </div>
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
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => {
              const name = c.display_name || `${c.surname || ""} ${c.given_name || ""}`.trim() || "-";
              return (
                <tr key={c.id}>
                  <td>{name}</td>
                  <td>{c.job_title || "-"}</td>
                  <td>{c.is_primary_contact ? <STATUS_ICONS.check size={ICON.sm} aria-hidden="true" /> : ""}</td>
                  <td>{c.primary_email || "-"}</td>
                  <td>{c.primary_phone || "-"}</td>
                  <td><span className={`status-badge status-${c.status}`}>{c.status}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
