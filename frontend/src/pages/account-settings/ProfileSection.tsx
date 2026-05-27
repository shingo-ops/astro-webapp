import { useState, FormEvent, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../../lib/api";
import { patchMyProfile } from "../../lib/staffProfile";
import { useUiPrefs } from "../../contexts/UiPrefsContext";
import { ACCOUNT_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";

interface StaffMe {
  surname_jp: string;
  given_name_jp: string;
  surname_kana: string | null;
  given_name_kana: string | null;
  surname_en: string | null;
  given_name_en: string | null;
  primary_email: string;
  phone: string | null;
}

export default function ProfileSection() {
  const { t } = useTranslation();
  const { refresh } = useUiPrefs();
  const [form, setForm] = useState({
    surname_jp: "", given_name_jp: "",
    surname_kana: "", given_name_kana: "",
    surname_en: "", given_name_en: "",
    phone: "",
  });
  const [email, setEmail] = useState("");
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get<StaffMe>("/staff/me").then((me) => {
      setEmail(me.primary_email);
      setForm({
        surname_jp: me.surname_jp ?? "",
        given_name_jp: me.given_name_jp ?? "",
        surname_kana: me.surname_kana ?? "",
        given_name_kana: me.given_name_kana ?? "",
        surname_en: me.surname_en ?? "",
        given_name_en: me.given_name_en ?? "",
        phone: me.phone ?? "",
      });
    }).catch(() => {});
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true); setSuccess(false); setError("");
    try {
      await patchMyProfile({ ...form, phone: form.phone === "" ? null : form.phone });
      await refresh();
      setSuccess(true);
    } catch {
      setError(t("common.saveError"));
    } finally {
      setSaving(false);
    }
  };

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  return (
    <section className="account-settings-section">
      <div className="account-settings-section-title">
        <ACCOUNT_ICONS.profile size={ICON.md} aria-hidden="true" />
        {t("accountSettings.sectionProfile")}
      </div>

      <div className="account-settings-field">
        <span className="account-settings-label">{t("accountSettings.emailLabel")}</span>
        <span className="account-settings-readonly">{email}</span>
        <span className="account-settings-note">{t("accountSettings.emailReadOnlyNote")}</span>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="account-settings-field">
          <label htmlFor="phone" className="account-settings-label">{t("accountSettings.phoneLabel")}</label>
          <input id="phone" type="tel" value={form.phone} onChange={set("phone")} />
        </div>

        <div className="account-settings-row">
          <div className="form-group">
            <label htmlFor="surname_jp">{t("accountSettings.surnameJp")}</label>
            <input id="surname_jp" value={form.surname_jp} onChange={set("surname_jp")} />
          </div>
          <div className="form-group">
            <label htmlFor="given_name_jp">{t("accountSettings.givenNameJp")}</label>
            <input id="given_name_jp" value={form.given_name_jp} onChange={set("given_name_jp")} />
          </div>
        </div>

        <div className="account-settings-row">
          <div className="form-group">
            <label htmlFor="surname_en">{t("accountSettings.surnameEn")}</label>
            <input id="surname_en" value={form.surname_en ?? ""} onChange={set("surname_en")} />
          </div>
          <div className="form-group">
            <label htmlFor="given_name_en">{t("accountSettings.givenNameEn")}</label>
            <input id="given_name_en" value={form.given_name_en ?? ""} onChange={set("given_name_en")} />
          </div>
        </div>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="account-settings-success">{t("accountSettings.profileSaved")}</div>}

        <div className="account-settings-actions">
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? t("accountSettings.saving") : t("common.save")}
          </button>
        </div>
      </form>
    </section>
  );
}
