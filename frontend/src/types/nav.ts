/**
 * ナビゲーション共有型定義
 *
 * Layout.tsx のサイドバーアコーディオンと
 * ManagementCenterPage のサブナビで共通して使用する型。
 */

/** サイドバー・サブナビの個別リンク項目 */
export interface NavItem {
  /** React Router の NavLink に渡す to パス */
  to: string;
  /** i18n キー（t() に渡す） */
  labelKey: string;
}

/** 管理センター サブナビのセクション（グループ） */
export interface NavSection {
  /** セクションの一意キー */
  key: string;
  /** セクションタイトルの i18n キー */
  titleKey: string;
  /** セクション内のナビ項目（権限フィルタ後） */
  items: NavItem[];
}
