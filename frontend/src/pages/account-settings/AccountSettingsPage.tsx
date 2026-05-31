import { PageLayout } from "../../components/PageLayout";
import ProfileSection from "./ProfileSection";
import SecuritySection from "./SecuritySection";
import PreferencesSection from "./PreferencesSection";
import "./account-settings.css";

export default function AccountSettingsPage() {
  return (
    <PageLayout navKey="nav.accountSettings" subtitleKey="accountSettings.subtitle">
      <div className="account-settings-layout">
        <ProfileSection />
        <PreferencesSection />
        <SecuritySection />
      </div>
    </PageLayout>
  );
}
