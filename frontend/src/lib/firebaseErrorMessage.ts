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
  "auth/invalid-credential": "メールアドレスまたはパスワードが正しくありません。",
  "auth/wrong-password": "メールアドレスまたはパスワードが正しくありません。",
  "auth/user-not-found": "メールアドレスまたはパスワードが正しくありません。",
  "auth/invalid-email": "メールアドレスの形式が正しくありません。",
  "auth/user-disabled": "このアカウントは無効化されています。管理者にお問い合わせください。",
  // レート制限
  "auth/too-many-requests":
    "ログイン試行回数の上限を超えました。しばらく時間をおいてから再度お試しください。",
  // ネットワーク
  "auth/network-request-failed":
    "ネットワークエラーが発生しました。接続状態を確認して再度お試しください。",
  // 設定不整合
  "auth/operation-not-allowed":
    "現在この認証方法はご利用いただけません。サポートにお問い合わせください。",
  // パスワードリセット系（将来用）
  "auth/expired-action-code":
    "リンクの有効期限が切れています。再度操作をやり直してください。",
  "auth/invalid-action-code":
    "リンクが無効です。最新のメールから操作してください。",
};

const DEFAULT_MESSAGE =
  "ログインに失敗しました。時間をおいて再度お試しください。問題が続く場合はサポートにご連絡ください。";

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
