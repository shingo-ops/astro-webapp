/**
 * Firebase Authentication のエラーをエンドユーザー向け日本語メッセージに変換する。
 *
 * Phase 1-E UI スモークテスト M-DYN-1 (2026-05-02) の対応:
 *   従来は `err.message` をそのまま表示していたため、UI に
 *   `Firebase: Error (auth/invalid-credential).` という生エラー文字列が出ていた。
 *
 * 設計方針:
 *   - 既知の error code は対応する日本語メッセージにマップ
 *   - 未知の code は汎用メッセージにフォールバック
 *   - "Firebase" / "auth/" 等の内部実装名はユーザーに見せない
 *   - ログイン以外のフロー（password reset 等）でも使えるよう汎用化
 */

interface FirebaseLikeError {
  code?: unknown;
  message?: unknown;
}

/**
 * Firebase の error code → 日本語メッセージ対応表
 * code 一覧: https://firebase.google.com/docs/auth/admin/errors
 */
const ERROR_MESSAGES: Record<string, string> = {
  // ログイン系（最近の Firebase は auth/invalid-credential に統合）
  "auth/invalid-credential": "Incorrect email address or password.",
  "auth/wrong-password": "Incorrect email address or password.",
  "auth/user-not-found": "Incorrect email address or password.",
  "auth/invalid-email": "Email address format is invalid.",
  "auth/user-disabled": "This account has been disabled. Please contact your administrator.",
  // レート制限
  "auth/too-many-requests":
    "Too many sign-in attempts. Please wait a moment and try again.",
  // ネットワーク
  "auth/network-request-failed":
    "Network error. Please check your connection and try again.",
  // 設定不整合
  "auth/operation-not-allowed":
    "This sign-in method is not currently available. Please contact support.",
  // パスワードリセット系（将来用）
  "auth/expired-action-code":
    "This link has expired. Please start over.",
  "auth/invalid-action-code":
    "This link is invalid. Please use the latest email.",
};

const DEFAULT_MESSAGE =
  "Sign-in failed. Please try again later. Contact support if the problem persists.";

/**
 * unknown 型のエラーから Firebase の error code を取り出して日本語メッセージに変換。
 *
 * @param err catch 節の unknown / Error / FirebaseError 等
 * @returns ユーザー向け日本語メッセージ
 */
export function firebaseErrorMessage(err: unknown): string {
  if (err && typeof err === "object") {
    const fe = err as FirebaseLikeError;
    if (typeof fe.code === "string" && ERROR_MESSAGES[fe.code]) {
      return ERROR_MESSAGES[fe.code];
    }
  }
  return DEFAULT_MESSAGE;
}
