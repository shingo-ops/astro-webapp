/**
 * usePageTitle — 現在のルートに対応するページ見出しを返す hook。
 *
 * ROUTE_TITLE_KEYS (src/config/routeTitles.ts) を Single Source of Truth として参照し、
 * サイドバーラベルと完全に同一の nav.* i18n キーで見出しを生成する。
 *
 * 注意:
 *   - 詳細ページ (/companies/:id など) では空文字を返す。
 *     詳細ページはデータ名をそのまま h2 に使うため、このフックは使わないこと。
 */
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ROUTE_TITLE_KEYS } from "../config/routeTitles";

export function usePageTitle(): string {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const key = ROUTE_TITLE_KEYS[pathname] ?? "";
  return key ? t(key) : "";
}
