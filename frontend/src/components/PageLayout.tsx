import { useTranslation } from "react-i18next";

interface PageLayoutProps {
  navKey: `nav.${string}`;
  subtitleKey?: string;
  headerAction?: React.ReactNode;
  /** フルハイト3カラム等、コンテンツ側でスクロール管理するページ用。
   *  overflow:hidden + padding:0 に切り替え、各カラムが自前でスクロール管理する。
   *  例外ページ一覧は frontend/CLAUDE.md を参照。 */
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
        <div className="page-layout-title-row">
          <h2 className="text-page-title">{t(navKey)}</h2>
          {headerAction}
        </div>
        {subtitleKey && (
          <p className="page-subtitle">{t(subtitleKey)}</p>
        )}
      </header>
      <div className={`page-layout-content${noScroll ? " no-scroll" : ""}`}>{children}</div>
    </div>
  );
}
