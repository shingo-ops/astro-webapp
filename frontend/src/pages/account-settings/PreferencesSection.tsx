import { useTranslation } from "react-i18next";
import { useTheme } from "../../contexts/ThemeContext";
import { useLocale } from "../../contexts/LocaleContext";
import { ACCOUNT_ICONS } from "../../constants/icons";
import { ICON } from "../../constants/iconSizes";

export default function PreferencesSection() {
  const { t } = useTranslation();
  const { theme, changeTheme } = useTheme();
  const { locale, changeLanguage } = useLocale();

  return (
    <section className="account-settings-section">
      <div className="account-settings-section-title">
        <ACCOUNT_ICONS.preferences size={ICON.md} aria-hidden="true" />
        {t("accountSettings.sectionPreferences")}
      </div>

      <div className="account-settings-pref-row">
        <label htmlFor="dark-mode-toggle" className="account-settings-pref-label">
          {t("accountSettings.darkModeLabel")}
        </label>
        <label className="toggle-switch">
          <input
            id="dark-mode-toggle"
            type="checkbox"
            checked={theme === "dark"}
            onChange={(e) => changeTheme(e.target.checked ? "dark" : "light")}
          />
          <span className="toggle-slider" aria-hidden="true" />
        </label>
      </div>

      <div className="account-settings-pref-row">
        <label htmlFor="language-select" className="account-settings-pref-label">
          {t("accountSettings.languageLabel")}
        </label>
        <select
          id="language-select"
          value={locale}
          onChange={(e) => changeLanguage(e.target.value)}
          className="account-settings-lang-select"
        >
          <option value="ja">{t("language.ja")}</option>
          <option value="en">{t("language.en")}</option>
        </select>
      </div>
    </section>
  );
}
