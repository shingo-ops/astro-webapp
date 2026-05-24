/**
 * レスポンシブブレークポイント定数
 *
 * tokens.css の --breakpoint-* 変数と同期して管理する。
 * CSS変数は @media 条件式では使用不可のため、JS側はこのファイルを参照すること。
 *
 * ── 3段階レスポンシブ設計 ──────────────────────────────────────
 * モバイル         : ≤ MOBILE_MAX   スマートフォン（≤ 767px）
 * 中間〜タブレット : TABLET_MIN〜TABLET_MAX  タブレット〜小型ノートPC（768〜1279px）
 * デスクトップ     : ≥ DESKTOP_MIN  MBP 13in以上（≥ 1280px）
 *
 * 根拠: 左443px+右300px+サイドバー60px=803px。中央445px確保のため
 *       1248px以上必要。MacBook Air 13in(1280px)を境界とした。
 *       Salesforce SLDS / GitHub Primer の実質3段階設計と一致。
 * ──────────────────────────────────────────────────────────────
 */
export const BREAKPOINTS = {
  /** モバイル上限 px — スマートフォン（≤ 767px） */
  MOBILE_MAX:   767,
  /** タブレット下限 px — iPad縦向き以上 */
  TABLET_MIN:   768,
  /** タブレット上限 px — デスクトップ境界の 1px 手前 */
  TABLET_MAX:  1279,
  /** デスクトップ下限 px — 受信箱カルテ常時表示ライン（MBP 13in） */
  DESKTOP_MIN: 1280,
  /** ワイド下限 px — FHD大画面（将来用） */
  XL_MIN:      1440,
} as const;

/**
 * window.matchMedia / CSS-in-JS 用クエリ文字列
 * 将来 JS側でレスポンシブ判定が必要になったときに使う。
 */
export const MEDIA_QUERIES = {
  mobile:  `(max-width: ${BREAKPOINTS.MOBILE_MAX}px)`,
  tablet:  `(min-width: ${BREAKPOINTS.TABLET_MIN}px) and (max-width: ${BREAKPOINTS.TABLET_MAX}px)`,
  desktop: `(min-width: ${BREAKPOINTS.DESKTOP_MIN}px)`,
  wide:    `(min-width: ${BREAKPOINTS.XL_MIN}px)`,
} as const;
