/**
 * ThemeContext（ADR-033: アプリ内テーマ切り替え）
 *
 * 役割:
 *   - ログイン後に DB の users.theme を取得して <html> クラスに反映
 *   - テーマ切り替え UI から changeTheme() を呼ぶ窓口
 *   - cookie に theme を保存（ページリロード後も維持）
 *   - OS の prefers-color-scheme は無視し、アプリ設定を優先
 *
 * 依存関係:
 *   - AuthContext (user)
 *   - /staff/me API（theme を取得）
 *
 * CSS:
 *   - theme='dark'  → <html class="force-dark">
 *   - theme='light' → <html> に force-dark なし（:root デフォルトがライト）
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
import { api } from "../lib/api";
import { useAuth } from "./AuthContext";

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  changeTheme: (theme: Theme) => Promise<void>;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  changeTheme: async () => {},
});

function saveThemeCookie(theme: Theme): void {
  const expires = new Date();
  expires.setFullYear(expires.getFullYear() + 1);
  document.cookie = `theme=${theme}; expires=${expires.toUTCString()}; path=/; SameSite=Lax`;
}

function readThemeCookie(): Theme | null {
  const match = document.cookie.match(/(?:^|;\s*)theme=(light|dark)/);
  return match ? (match[1] as Theme) : null;
}

function applyThemeClass(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("force-dark");
  } else {
    root.classList.remove("force-dark");
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [theme, setTheme] = useState<Theme>(() => readThemeCookie() ?? "light");

  // 初期化時に cookie の値をすぐ反映（リロード後のチラつき防止）
  useEffect(() => {
    applyThemeClass(theme);
  }, [theme]);

  /** DB から theme を取得して state・cookie・<html> クラスに反映 */
  const syncThemeFromServer = useCallback(async () => {
    if (!user) return;
    try {
      const me = await api.get<{ theme?: string }>("/staff/me");
      const serverTheme = (me.theme === "dark" ? "dark" : "light") as Theme;
      if (serverTheme !== theme) {
        saveThemeCookie(serverTheme);
        setTheme(serverTheme);
        applyThemeClass(serverTheme);
      }
    } catch {
      // 取得失敗は無視（cookie の値で継続）
    }
  }, [user, theme]);

  useEffect(() => {
    if (authLoading) return;
    syncThemeFromServer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, user]);

  /** UI からテーマを切り替える（即時反映 + DB 永続化 + cookie 保存） */
  const changeTheme = useCallback(async (next: Theme) => {
    saveThemeCookie(next);
    setTheme(next);
    applyThemeClass(next);
    try {
      await api.patch("/staff/me/theme", { theme: next });
    } catch {
      // 永続化失敗は無視（cookie で保持）
    }
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, changeTheme }),
    [theme, changeTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
