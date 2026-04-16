/**
 * 準備中ページ（GAS版互換のメニュー項目のうち、未実装のものに使用する汎用プレースホルダー）。
 *
 * 使い方:
 *   <Route path="/inventory" element={<ComingSoonPage title="在庫管理" description="..." />} />
 *
 * 変更履歴:
 *   2026-04-17: 初版作成
 */

interface Props {
  title: string;
  description?: string;
}

export default function ComingSoonPage({ title, description }: Props) {
  return (
    <div className="page">
      <div className="coming-soon">
        <div className="coming-soon-icon">🚧</div>
        <h2>{title}</h2>
        <p className="coming-soon-label">準備中</p>
        {description && <p className="coming-soon-desc">{description}</p>}
        <p className="coming-soon-note">
          この機能は現在開発中です。Phase 2 以降のリリースで利用可能になります。
        </p>
      </div>
    </div>
  );
}
