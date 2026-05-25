import { useTranslation } from "react-i18next";

interface PageLayoutProps {
  navKey: `nav.${string}`;
  subtitleKey?: string;
  headerAction?: React.ReactNode;
  noScroll?: boolean;
  children: React.ReactNode;
}

export function PageLayout({
  navKey,
  subtitleKey,
  headerAction,
  noScroll,
  children,
}: PageLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="page-layout">
      <header className="page-layout-header">
        <div className={`page-layout-title-row${subtitleKey ? " page-layout-title-row--has-subtitle" : ""}`}>
          <h2 className="text-page-title">{t(navKey)}</h2>
          {headerAction}
        </div>
        {subtitleKey && (
          <p className="page-subtitle">{t(subtitleKey)}</p>
        )}
      </header>
      <div className={noScroll ? "page-layout-content page-layout-content--no-scroll" : "page-layout-content"}>{children}</div>
    </div>
  );
}
