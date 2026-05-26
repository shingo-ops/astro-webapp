import { useTranslation } from "react-i18next";
import type { StatusTabKey } from "./inbox.types";

interface InboxSettings {
  showRightPanel: boolean;
  defaultTab: StatusTabKey;
  defaultUnreadOnly: boolean;
  browserNotifications: boolean;
  soundEnabled: boolean;
}

interface Props {
  inboxSettings: InboxSettings;
  updateInboxSetting: <K extends keyof InboxSettings>(key: K, value: InboxSettings[K]) => void;
  onClose: () => void;
}

export function InboxSettingsModal({ inboxSettings, updateInboxSetting, onClose }: Props) {
  const { t } = useTranslation();

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="inbox-settings-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="inbox-settings-modal-title">{t("inbox.settings.title")}</h3>

        <div className="inbox-settings-section-title">{t("inbox.settings.display")}</div>

        <div className="inbox-settings-row">
          <span className="inbox-settings-label">{t("inbox.settings.showRightPanel")}</span>
          <label className="toggle-switch">
            <input type="checkbox" checked={inboxSettings.showRightPanel}
              onChange={(e) => updateInboxSetting("showRightPanel", e.target.checked)} />
            <span className="toggle-switch-slider" />
          </label>
        </div>

        <div className="inbox-settings-row">
          <span className="inbox-settings-label">{t("inbox.settings.defaultTab")}</span>
          <select className="inbox-settings-select"
            value={inboxSettings.defaultTab}
            onChange={(e) => updateInboxSetting("defaultTab", e.target.value as StatusTabKey)}>
            <option value="all">{t("inbox.settings.defaultTabAll")}</option>
            <option value="lead">{t("inbox.settings.defaultTabLead")}</option>
            <option value="deal">{t("inbox.settings.defaultTabDeal")}</option>
            <option value="existing">{t("inbox.settings.defaultTabExisting")}</option>
            <option value="followup">{t("inbox.settings.defaultTabFollowUp")}</option>
            <option value="archive">{t("inbox.settings.defaultTabArchive")}</option>
          </select>
        </div>

        <div className="inbox-settings-row">
          <span className="inbox-settings-label">{t("inbox.settings.defaultUnreadOnly")}</span>
          <label className="toggle-switch">
            <input type="checkbox" checked={inboxSettings.defaultUnreadOnly}
              onChange={(e) => updateInboxSetting("defaultUnreadOnly", e.target.checked)} />
            <span className="toggle-switch-slider" />
          </label>
        </div>

        <div className="inbox-settings-section-title" style={{ marginTop: "var(--space-4)" }}>
          {t("inbox.settings.notifications")}
        </div>

        <div className="inbox-settings-row">
          <span className="inbox-settings-label">{t("inbox.settings.browserNotifications")}</span>
          <label className="toggle-switch">
            <input type="checkbox" checked={inboxSettings.browserNotifications}
              onChange={async (e) => {
                if (e.target.checked) {
                  const perm = await Notification.requestPermission();
                  if (perm === "denied") {
                    alert(t("inbox.settings.browserNotificationsDenied"));
                    return;
                  }
                }
                updateInboxSetting("browserNotifications", e.target.checked);
              }} />
            <span className="toggle-switch-slider" />
          </label>
        </div>

        <div className="inbox-settings-row">
          <span className="inbox-settings-label">{t("inbox.settings.soundEnabled")}</span>
          <label className="toggle-switch">
            <input type="checkbox" checked={inboxSettings.soundEnabled}
              onChange={(e) => updateInboxSetting("soundEnabled", e.target.checked)} />
            <span className="toggle-switch-slider" />
          </label>
        </div>

        <button type="button" className="inbox-settings-close-btn" onClick={onClose}>
          {t("common.close")}
        </button>
      </div>
    </div>
  );
}
