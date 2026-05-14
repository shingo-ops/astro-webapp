/**
 * 準備中ページ（GAS版互換のメニュー項目のうち、未実装のものに使用する汎用プレースホルダー）。
 *
 * 使い方:
 *   <Route path="/inventory" element={<ComingSoonPage title="在庫管理" description="..." />} />
 *
 * 変更履歴:
 *   2026-04-17: 初版作成
 */

import { useTranslation } from "react-i18next";

interface Props {
  title: string;
  description?: string;
}

export default function ComingSoonPage({ title, description }: Props) {
  const { t } = useTranslation();
  return (
    <div className="page">
      <div className="coming-soon">
        <div className="coming-soon-icon">🚧</div>
        <h2>{title}</h2>
        <p className="coming-soon-label">{t("comingSoon.label")}</p>
        {description && <p className="coming-soon-desc">{description}</p>}
        <p className="coming-soon-note">
          {t("comingSoon.note")}
        </p>
      </div>
    </div>
  );
}
