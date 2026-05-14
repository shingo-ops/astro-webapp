/**
 * LocaleContext（ADR-027: UI 国際化対応）
 *
 * 役割:
 *   - ログイン後に DB の users.locale を取得して i18next に反映
 *   - 言語切り替え UI から changeLanguage() を呼ぶ窓口
 *   - cookie に locale を保存（ページリロード後も維持）
 *
 * 依存関係:
 *   - AuthContext (user)
 *   - UiPrefsContext (/staff/me から locale を取得)
 *   - i18n.ts (i18next インスタンス)
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";
import i18n, { saveLocaleCookie } from "../i18n";
import { api } from "../lib/api";
import { useAuth } from "./AuthContext";

interface LocaleContextValue {
  locale: string;
  changeLanguage: (lang: string) => Promise<void>;
}

const LocaleContext = createContext<LocaleContextValue>({
  locale: "ja",
  changeLanguage: async () => {},
});

export function LocaleProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [locale, setLocale] = useState<string>(i18n.language || "ja");

  /** DB から locale を取得して i18next と cookie に反映 */
  const syncLocaleFromServer = useCallback(async () => {
    if (!user) return;
    try {
      const me = await api.get<{ locale?: string }>("/staff/me");
      const serverLocale = me.locale ?? "ja";
      if (serverLocale !== i18n.language) {
        await i18n.changeLanguage(serverLocale);
        saveLocaleCookie(serverLocale);
        setLocale(serverLocale);
      }
    } catch {
      // 取得失敗は無視（cookie の値で継続）
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return;
    syncLocaleFromServer();
  }, [authLoading, syncLocaleFromServer]);

  /** UI から言語を切り替える（即時反映 + DB 永続化 + cookie 保存） */
  const changeLanguage = useCallback(async (lang: string) => {
    await i18n.changeLanguage(lang);
    saveLocaleCookie(lang);
    setLocale(lang);
    try {
      await api.patch("/staff/me/locale", { locale: lang });
    } catch {
      // 永続化失敗は無視（cookie で保持）
    }
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({ locale, changeLanguage }),
    [locale, changeLanguage],
  );

  return (
    <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
  );
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}
