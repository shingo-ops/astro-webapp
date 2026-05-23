import { useTranslation } from "react-i18next";

interface PageLayoutProps {
  navKey: `nav.${string}`;
  subtitleKey?: string;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
}

export function PageLayout({
  navKey,
  subtitleKey,
  headerAction,
  children,
}: PageLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="page-layout">
      <header className="page-layout-header">
        <div className="page-layout-title-row">
          <h2 className="text-page-title">{t(navKey)}</h2>
          {headerAction}
        </div>
        {subtitleKey && (
          <p className="page-subtitle">{t(subtitleKey)}</p>
        )}
      </header>
      <div className="page-layout-content">{children}</div>
    </div>
  );
}
