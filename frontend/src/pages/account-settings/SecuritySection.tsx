import { useState, FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { EmailAuthProvider, reauthenticateWithCredential, updatePassword } from "firebase/auth";
import { auth } from "../../lib/firebase";
import { firebaseErrorMessage } from "../../lib/firebaseErrorMessage";
import { ACCOUNT_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";

export default function SecuritySection() {
  const { t } = useTranslation();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [changing, setChanging] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(""); setSuccess(false);

    if (form.next !== form.confirm) {
      setError(t("accountSettings.passwordMismatch"));
      return;
    }
    if (form.next.length < 8) {
      setError(t("accountSettings.passwordTooShort"));
      return;
    }

    const user = auth.currentUser;
    if (!user || !user.email) {
      setError(t("firebaseError.default"));
      return;
    }

    setChanging(true);
    try {
      const cred = EmailAuthProvider.credential(user.email, form.current);
      await reauthenticateWithCredential(user, cred);
      await updatePassword(user, form.next);
      setSuccess(true);
      setForm({ current: "", next: "", confirm: "" });
    } catch (err) {
      setError(firebaseErrorMessage(err, t));
    } finally {
      setChanging(false);
    }
  };

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.value }));

  return (
    <section className="account-settings-section">
      <div className="account-settings-section-title">
        <ACCOUNT_ICONS.security size={ICON.md} aria-hidden="true" />
        {t("accountSettings.sectionSecurity")}
      </div>

      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="current_password">{t("accountSettings.currentPassword")}</label>
          <input
            id="current_password"
            type="password"
            value={form.current}
            onChange={set("current")}
            autoComplete="current-password"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="new_password">{t("accountSettings.newPassword")}</label>
          <input
            id="new_password"
            type="password"
            value={form.next}
            onChange={set("next")}
            autoComplete="new-password"
            required
          />
        </div>

        <div className="form-group">
          <label htmlFor="confirm_password">{t("accountSettings.confirmPassword")}</label>
          <input
            id="confirm_password"
            type="password"
            value={form.confirm}
            onChange={set("confirm")}
            autoComplete="new-password"
            required
          />
        </div>

        {error && <div className="error-message">{error}</div>}
        {success && <div className="account-settings-success">{t("accountSettings.passwordChanged")}</div>}

        <div className="account-settings-actions">
          <button type="submit" className="btn-primary" disabled={changing}>
            {changing ? t("accountSettings.changing") : t("accountSettings.changePassword")}
          </button>
        </div>
      </form>
    </section>
  );
}
