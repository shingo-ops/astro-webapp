/**
 * Firebase Authentication 設定
 *
 * Google Identity Platform（Firebase Auth互換）を使用してユーザー認証を行う。
 * 環境変数はビルド時にViteが埋め込む（VITE_ プレフィックス必須）。
 *
 * フロー:
 *   1. ユーザーがログインページでメール/パスワードを入力
 *   2. Firebase がMFA（認証アプリのコード）を要求
 *   3. 認証成功 → Firebase が IDトークン（JWT）を発行
 *   4. 全APIリクエストに IDトークンを Authorization ヘッダーで付与
 *   5. バックエンド（FastAPI）がトークンを検証し、ユーザーを特定
 */

import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_GCP_PROJECT_ID,
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
export default app;
