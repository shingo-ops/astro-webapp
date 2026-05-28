/**
 * Vitest グローバルセットアップ（unit テスト専用）
 *
 * Firebase は VITE_FIREBASE_API_KEY 等の環境変数がない状態では
 * 初期化エラーを投げる。unit テストでは Firebase 本体は不要なため、
 * firebase.ts モジュールをスタブに差し替えて初期化をバイパスする。
 */

import { vi } from "vitest";

vi.mock("./lib/firebase", () => ({
  auth: {
    currentUser: null,
    onAuthStateChanged: vi.fn(),
    signInWithEmailAndPassword: vi.fn(),
    signOut: vi.fn(),
  },
  default: {},
}));
