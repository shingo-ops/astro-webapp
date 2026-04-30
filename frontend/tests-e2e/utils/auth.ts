/**
 * Firebase Auth bypass helper for Playwright E2E (Phase 1-E F2-S3).
 *
 * frontend は AuthContext で `firebase/auth` の `onAuthStateChanged` を購読する。
 * Firebase は startup 時に IndexedDB の `firebaseLocalStorageDb` から
 * persisted user を復元する。E2E ではこれを利用して、ページ読み込み前に
 * IndexedDB へ dummy user を流し込み、`auth.currentUser.getIdToken()` も
 * fetch を patch して固定 token を返す。
 *
 * これにより:
 *   - LoginPage を経由せずに `/`, `/lead-chat`, `/channels` が描画される
 *   - api.ts の getIdToken() がネットワーク（identitytoolkit）に向かわない
 *   - 既存ソース（src/）を一切変更せず E2E が成立する
 *
 * 注意:
 *   - このスクリプトは `page.addInitScript` で各ページ load 前に注入する
 *   - apiKey は playwright.config.ts の VITE_FIREBASE_API_KEY と一致必須
 *   - identitytoolkit endpoint は念のため route で 400 にブロック（fail-open より fail-fast）
 */

import type { Page } from "@playwright/test";

export const E2E_API_KEY = "AIzaSyE2E-dummy-api-key";
export const E2E_PROJECT_ID = "e2e-fixture";
export const E2E_USER = {
  uid: "e2e-test-user-uid",
  email: "review@salesanchor.jp",
  displayName: "E2E Test User",
  idToken: "e2e-fake-id-token",
  // 1 時間後に expire する dummy（getIdToken 内で refresh 不要）
  expiresInSec: 3600,
};

/**
 * Playwright `page` に Firebase Auth bypass を注入する。
 *
 * ページ goto 前に必ず呼ぶこと。`page.addInitScript()` で:
 *   1. IndexedDB `firebaseLocalStorageDb` に user record を流し込み
 *   2. window.fetch を patch して identitytoolkit / securetoken を mock
 *
 * @param page Playwright page
 */
export async function installAuthBypass(page: Page): Promise<void> {
  await page.addInitScript(
    ({ apiKey, projectId, user }) => {
      // ----- (1) IndexedDB に Firebase Auth persistence record を仕込む -----
      // Firebase Auth v9+ は dbName "firebaseLocalStorageDb" / store "firebaseLocalStorage"
      // / key "firebase:authUser:<apiKey>:[DEFAULT]" で user を保存する。
      const dbName = "firebaseLocalStorageDb";
      const storeName = "firebaseLocalStorage";
      const key = `firebase:authUser:${apiKey}:[DEFAULT]`;
      const value = {
        uid: user.uid,
        email: user.email,
        emailVerified: true,
        displayName: user.displayName,
        isAnonymous: false,
        providerData: [
          {
            uid: user.email,
            displayName: user.displayName,
            email: user.email,
            providerId: "password",
          },
        ],
        stsTokenManager: {
          refreshToken: "e2e-fake-refresh-token",
          accessToken: user.idToken,
          expirationTime: Date.now() + user.expiresInSec * 1000,
        },
        createdAt: String(Date.now() - 86_400_000),
        lastLoginAt: String(Date.now()),
        apiKey,
        appName: "[DEFAULT]",
      };

      function openDb(): Promise<IDBDatabase> {
        return new Promise((resolve, reject) => {
          const req = indexedDB.open(dbName, 1);
          req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains(storeName)) {
              db.createObjectStore(storeName, { keyPath: "fbase_key" });
            }
          };
          req.onsuccess = () => resolve(req.result);
          req.onerror = () => reject(req.error);
        });
      }

      // 同期的に await できないので Promise を window に出して上書き完了を待つ
      (window as unknown as { __e2eAuthReady: Promise<void> }).__e2eAuthReady =
        (async () => {
          try {
            const db = await openDb();
            await new Promise<void>((resolve) => {
              const tx = db.transaction(storeName, "readwrite");
              const store = tx.objectStore(storeName);
              store.put({ fbase_key: key, value });
              tx.oncomplete = () => resolve();
              tx.onerror = () => resolve();
            });
            db.close();
          } catch {
            // IndexedDB が使えない環境では fallback として localStorage に書く
            try {
              localStorage.setItem(key, JSON.stringify(value));
            } catch {
              /* noop */
            }
          }
        })();

      // ----- (2) fetch を patch して identitytoolkit / securetoken をブロック -----
      // Firebase Auth v9 は initializeApp 後に getAccountInfo を呼んで refresh する
      // 場合がある。ここでは固定 user を返す。
      const origFetch = window.fetch.bind(window);
      window.fetch = async (
        input: RequestInfo | URL,
        init?: RequestInit,
      ): Promise<Response> => {
        const url =
          typeof input === "string"
            ? input
            : input instanceof URL
              ? input.toString()
              : input.url;

        // identitytoolkit getAccountInfo
        if (url.includes("identitytoolkit.googleapis.com") && url.includes(":lookup")) {
          return new Response(
            JSON.stringify({
              kind: "identitytoolkit#GetAccountInfoResponse",
              users: [
                {
                  localId: user.uid,
                  email: user.email,
                  emailVerified: true,
                  displayName: user.displayName,
                  providerUserInfo: [
                    {
                      providerId: "password",
                      federatedId: user.email,
                      email: user.email,
                      displayName: user.displayName,
                    },
                  ],
                  passwordHash: "e2e",
                  passwordUpdatedAt: Date.now(),
                  validSince: "0",
                  lastLoginAt: String(Date.now()),
                  createdAt: String(Date.now() - 86_400_000),
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        // securetoken token refresh
        if (url.includes("securetoken.googleapis.com")) {
          return new Response(
            JSON.stringify({
              access_token: user.idToken,
              expires_in: String(user.expiresInSec),
              token_type: "Bearer",
              refresh_token: "e2e-fake-refresh-token",
              id_token: user.idToken,
              user_id: user.uid,
              project_id: projectId,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        // identitytoolkit signInWithPassword（LoginPage 経由ログインのテスト用）
        if (
          url.includes("identitytoolkit.googleapis.com") &&
          url.includes(":signInWithPassword")
        ) {
          return new Response(
            JSON.stringify({
              kind: "identitytoolkit#VerifyPasswordResponse",
              localId: user.uid,
              email: user.email,
              displayName: user.displayName,
              idToken: user.idToken,
              registered: true,
              refreshToken: "e2e-fake-refresh-token",
              expiresIn: String(user.expiresInSec),
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        return origFetch(input, init);
      };
    },
    {
      apiKey: E2E_API_KEY,
      projectId: E2E_PROJECT_ID,
      user: E2E_USER,
    },
  );
}

/**
 * Vite dev server が落ちている / E2E スキップ環境用の guard。
 * テスト先頭で呼ぶことで、サーバ未起動を早期検知する。
 */
export async function ensureWebServerUp(page: Page, baseURL?: string): Promise<void> {
  const url = baseURL || page.context()["_options"]?.baseURL || "http://localhost:5173";
  try {
    const res = await page.request.get(url, { timeout: 5000 });
    if (!res.ok() && res.status() !== 304) {
      throw new Error(`web server returned ${res.status()}`);
    }
  } catch (e) {
    throw new Error(
      `Vite dev server is not reachable at ${url}: ${
        e instanceof Error ? e.message : String(e)
      }`,
    );
  }
}
