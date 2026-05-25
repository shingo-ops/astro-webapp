/**
 * UI設定コンテキスト（Phase 1-B-1: B-1 wiring）。
 *
 * staff_ui_preferences テーブルに保存された値を `/api/v1/staff/me` から取得し、
 * アプリ全体（Layout/メニュー/ダークモード/サイドバー表示）に反映する。
 *
 * 取得失敗時はデフォルト値（全メニュー表示・ライトモード・サイドバー表示）で動作する。
 * 失敗を握りつぶすのは「未紐づけスタッフでもアプリ自体は使える」ようにするため。
 *
 * 変更履歴:
 *   2026-04-27: 初版（Phase 1-B-1 軽量スコープ）
 *   2026-04-27: PR #166 round 1 fix
 *     - F2: prefs fetch 完了前は <html> にクラスを付けず OS prefers-color-scheme に従わせる
 *           （未設定ユーザの強制ライト化 / FOUC 回避）
 *     - F3: loading state を expose（Layout の menu フリッカー対策）
 *     - F4: selfStaffId を expose（StaffPage で「自分の編集時のみ refresh」用）
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

export interface UiPrefs {
  dark_mode: boolean;
  show_chat_menu: boolean;
  show_sales_menu: boolean;
  show_settings_menu: boolean;
  show_admin_menu: boolean;
  show_sidebar: boolean;
}

export const DEFAULT_UI_PREFS: UiPrefs = {
  dark_mode: false,
  show_chat_menu: true,
  show_sales_menu: true,
  show_settings_menu: true,
  // show_admin_menu のデフォルトは false だが、未紐づけ・取得失敗時は安全側で
  // staff レコードが存在しないユーザ＝Firebase Auth 経由 admin の可能性が高いので
  // 取得失敗時はあえて true にして詰みを防ぐ。明示的に false に設定したい場合は
  // /staff/me で正しく取得すれば override される。
  show_admin_menu: true,
  show_sidebar: true,
};

interface UiPrefsContextValue {
  prefs: UiPrefs;
  /** 初期 fetch 中（または認証確定前）かどうか。Layout 側の menu フリッカー抑制に使う。 */
  loading: boolean;
  /** /staff/me の fetch が一度でも完了したか（成功/失敗いずれも true）。
   *  完了するまで `<html>` に force-light/force-dark クラスを付けず、OS の
   *  prefers-color-scheme に従わせるためのガード（PR #166 F2）。 */
  prefsFetched: boolean;
  /** /staff/me から得た自分の staff.id（取得失敗時は null）。
   *  StaffPage で「編集対象が自分かどうか」判定し、自分の編集時だけ refresh するために使う。 */
  selfStaffId: number | null;
  /** /staff/me から再取得（StaffPage で自分のレコードを保存した直後などに呼ぶ） */
  refresh: () => Promise<void>;
  /** ローカル即時反映（refresh より前に prefs を上書きしてチラつきを防ぐ） */
  setPrefs: (next: UiPrefs) => void;
}

const UiPrefsContext = createContext<UiPrefsContextValue | null>(null);

interface StaffMeResponse {
  id: number;
  primary_email: string;
  ui_preferences: UiPrefs | null;
  // 他フィールドもあるが UI prefs 反映には不要
}

export function UiPrefsProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const [prefs, setPrefsState] = useState<UiPrefs>(DEFAULT_UI_PREFS);
  const [loading, setLoading] = useState(true);
  const [prefsFetched, setPrefsFetched] = useState(false);
  const [selfStaffId, setSelfStaffId] = useState<number | null>(null);

  const fetchPrefs = useCallback(async () => {
    if (!user) {
      // 未ログイン時はデフォルトのまま、loading=false
      setPrefsState(DEFAULT_UI_PREFS);
      setSelfStaffId(null);
      setPrefsFetched(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const me = await api.get<StaffMeResponse>("/staff/me");
      // ui_preferences が null（テーブル未投入）でもデフォルト値で動作させる
      setPrefsState(me.ui_preferences ?? DEFAULT_UI_PREFS);
      setSelfStaffId(me.id);
    } catch (e) {
      // 404（staff 未紐づけ）や 5xx の場合はデフォルト値で動作。
      // ログには残すが UI は止めない。
      // eslint-disable-next-line no-console
      console.warn("[UiPrefs] /staff/me 取得失敗、デフォルト値で動作:", e);
      setPrefsState(DEFAULT_UI_PREFS);
      setSelfStaffId(null);
    } finally {
      setPrefsFetched(true);
      setLoading(false);
    }
  }, [user]);

  // ログイン状態が確定したタイミングで一度取得
  useEffect(() => {
    if (authLoading) return;
    fetchPrefs();
  }, [authLoading, fetchPrefs]);

  // ADR-033: <html> への force-dark / force-light クラス管理は ThemeContext に委譲。
  // UiPrefsContext は staff_ui_preferences.dark_mode の値を保持するが、
  // CSS クラスの適用は行わない（ThemeContext が users.theme に基づいて管理する）。

  const setPrefs = useCallback((next: UiPrefs) => {
    setPrefsState(next);
  }, []);

  const value = useMemo<UiPrefsContextValue>(
    () => ({
      prefs,
      loading,
      prefsFetched,
      selfStaffId,
      refresh: fetchPrefs,
      setPrefs,
    }),
    [prefs, loading, prefsFetched, selfStaffId, fetchPrefs, setPrefs],
  );

  return (
    <UiPrefsContext.Provider value={value}>{children}</UiPrefsContext.Provider>
  );
}

export function useUiPrefs(): UiPrefsContextValue {
  const ctx = useContext(UiPrefsContext);
  if (!ctx) {
    // Provider 外から呼ばれた場合はデフォルト値で no-op
    // （テスト/ストーリーブック等で楽に使えるようにする）
    return {
      prefs: DEFAULT_UI_PREFS,
      loading: false,
      prefsFetched: false,
      selfStaffId: null,
      refresh: async () => {},
      setPrefs: () => {},
    };
  }
  return ctx;
}
