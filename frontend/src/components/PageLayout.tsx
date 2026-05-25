import { useTranslation } from "react-i18next";

interface PageLayoutProps {
  navKey: `nav.${string}`;
  subtitleKey?: string;
  /** タイトルのすぐ右に並べるコンテンツ（ナビゲーション等）*/
  headerLeft?: React.ReactNode;
  headerAction?: React.ReactNode;
  noScroll?: boolean;
  children: React.ReactNode;
}

export function PageLayout({
  navKey,
  subtitleKey,
  headerLeft,
  headerAction,
  noScroll,
  children,
}: PageLayoutProps) {
  const { t } = useTranslation();
  return (
    <div className="page-layout">
      <header className="page-layout-header">
        <div className="page-layout-title-row">
          <h2 className="text-page-title">{t(navKey)}</h2>
          {headerLeft}
          {headerAction && (
            <div className="page-layout-header-right">{headerAction}</div>
          )}
        </div>
        {subtitleKey && (
          <p className="page-subtitle">{t(subtitleKey)}</p>
        )}
      </header>
      <div className={noScroll ? "page-layout-content page-layout-content--no-scroll" : "page-layout-content"}>{children}</div>
    </div>
  );
}
