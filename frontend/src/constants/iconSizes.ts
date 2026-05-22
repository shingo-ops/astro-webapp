/**
 * Icon size constants — mirrors tokens.css --icon-* values.
 * CSS variables cannot be used directly in Lucide `size` prop (expects number),
 * so these TypeScript constants keep JS and CSS in sync.
 *
 * Mirror: src/tokens.css (--icon-sm / --icon-md / --icon-base / --icon-lg / --icon-xl)
 * Keep values in sync when updating tokens.css.
 */
export const ICON = {
  sm:   14,  /* --icon-sm:   ステータスアイコン・テーブル内 */
  md:   16,  /* --icon-md:   コントロールアイコン（閉じる・テーマ切替） */
  base: 20,  /* --icon-base: 標準アイコン（サイドバーナビ・カード内） */
  lg:   24,  /* --icon-lg:   大アイコン */
  xl:   48,  /* --icon-xl:   空状態アイコン（empty state） */
} as const;

export type IconSize = (typeof ICON)[keyof typeof ICON];
