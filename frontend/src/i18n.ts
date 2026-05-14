/**
 * i18next 設定（ADR-027: UI 国際化対応）
 *
 * 初期言語の決定順序:
 *   1. cookie `locale=` （ログイン前 / ページリロード時の保持）
 *   2. デフォルト `ja`
 *
 * ログイン後は UiPrefsContext が DB の users.locale を読み込み、
 * changeLanguage() を呼んで i18n を同期させる。
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import ja from "./locales/ja.json";

/** cookie から locale を読む（ブラウザ標準 API のみ、外部依存なし）。 */
function readLocaleCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)locale=([^;]+)/);
  return match ? match[1] : null;
}

/** locale を cookie に保存（1 年間）。 */
export function saveLocaleCookie(lang: string): void {
  document.cookie = `locale=${lang};path=/;max-age=31536000;SameSite=Lax`;
}

const initialLang = readLocaleCookie() ?? "ja";

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ja: { translation: ja },
  },
  lng: initialLang,
  fallbackLng: "ja",
  interpolation: {
    escapeValue: false, // React は XSS エスケープを行うため不要
  },
  // 翻訳キー欠落時: 開発環境で警告、本番ではキー名そのまま表示
  missingKeyHandler: (lngs, ns, key) => {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`[i18n] Missing key: "${key}" (lng: ${lngs.join(",")})`);
    }
  },
  saveMissing: import.meta.env.DEV,
});

export default i18n;
