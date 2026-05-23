/**
 * レスポンシブブレークポイント定数
 *
 * tokens.css の --breakpoint-* 変数と同期して管理する。
 * CSS変数は @media 条件式では使用不可のため、JS側はこのファイルを参照すること。
 *
 * ── 3段階レスポンシブ設計 ──────────────────────────────────────
 * モバイル     : ≤ MOBILE_MAX   スマートフォン（画面幅 ≤ 767px）
 * タブレット   : TABLET_MIN〜TABLET_MAX  タブレット縦/横（768〜1023px）
 * デスクトップ : ≥ DESKTOP_MIN  ノートPC以上（1024px〜）
 *
 * 根拠: Tailwind / Intercom / Zendesk が採用する lg=1024px / md=768px ラインと一致。
 *       iPad mini 横向き(1024px)をデスクトップ扱いにするため 1024px を境界とした。
 * ──────────────────────────────────────────────────────────────
 */
export const BREAKPOINTS = {
  /** モバイル上限 px — スマートフォン（≤ 767px） */
  MOBILE_MAX:   767,
  /** タブレット下限 px — iPad縦向き以上 */
  TABLET_MIN:   768,
  /** タブレット上限 px — デスクトップ境界の 1px 手前 */
  TABLET_MAX:  1023,
  /** デスクトップ下限 px — 受信箱カルテドロワー切替点 */
  DESKTOP_MIN: 1024,
} as const;

/**
 * window.matchMedia / CSS-in-JS 用クエリ文字列
 * 将来 JS側でレスポンシブ判定が必要になったときに使う。
 */
export const MEDIA_QUERIES = {
  mobile:  `(max-width: ${BREAKPOINTS.MOBILE_MAX}px)`,
  tablet:  `(min-width: ${BREAKPOINTS.TABLET_MIN}px) and (max-width: ${BREAKPOINTS.TABLET_MAX}px)`,
  desktop: `(min-width: ${BREAKPOINTS.DESKTOP_MIN}px)`,
} as const;
