/**
 * Firebase Authentication のエラーをエンドユーザー向けメッセージに変換する。
 *
 * Phase 1-E UI スモークテスト M-DYN-1 (2026-05-02) の対応:
 *   従来は `err.message` をそのまま表示していたため、UI に
 *   `Firebase: Error (auth/invalid-credential).` という生エラー文字列が出ていた。
 *
 * ADR-027: 全メッセージを i18n キー経由に統一。
 *   呼び出し側から `t` 関数を受け取り、`firebaseError.*` キーを参照する。
 *   キー一覧: src/locales/ja.json / en.json の "firebaseError" セクション。
 *
 * 設計方針:
 *   - 既知の error code は対応する翻訳キーにマップ
 *   - 未知の code は汎用キーにフォールバック
 *   - "Firebase" / "auth/" 等の内部実装名はユーザーに見せない
 *   - ログイン以外のフロー（password reset 等）でも使えるよう汎用化
 */

interface FirebaseLikeError {
  code?: unknown;
  message?: unknown;
}

/** Firebase error code → i18n キー対応表 */
const ERROR_KEY_MAP: Record<string, string> = {
  // ログイン系（最近の Firebase は auth/invalid-credential に統合）
  "auth/invalid-credential":    "firebaseError.invalidCredential",
  "auth/wrong-password":        "firebaseError.invalidCredential",
  "auth/user-not-found":        "firebaseError.invalidCredential",
  "auth/invalid-email":         "firebaseError.invalidEmail",
  "auth/user-disabled":         "firebaseError.userDisabled",
  // レート制限
  "auth/too-many-requests":     "firebaseError.tooManyRequests",
  // ネットワーク
  "auth/network-request-failed":"firebaseError.networkRequestFailed",
  // 設定不整合
  "auth/operation-not-allowed": "firebaseError.operationNotAllowed",
  // パスワードリセット系（将来用）
  "auth/expired-action-code":   "firebaseError.expiredActionCode",
  "auth/invalid-action-code":   "firebaseError.invalidActionCode",
};

/**
 * unknown 型のエラーから Firebase の error code を取り出して翻訳済みメッセージに変換。
 *
 * @param err catch 節の unknown / Error / FirebaseError 等
 * @param t   useTranslation() から取得した t 関数
 * @returns   ユーザー向け翻訳済みメッセージ
 */
export function firebaseErrorMessage(err: unknown, t: (key: string) => string): string {
  if (err && typeof err === "object") {
    const fe = err as FirebaseLikeError;
    if (typeof fe.code === "string" && ERROR_KEY_MAP[fe.code]) {
      return t(ERROR_KEY_MAP[fe.code]);
    }
  }
  return t("firebaseError.default");
}
