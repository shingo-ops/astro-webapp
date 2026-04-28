/**
 * APIクライアント。
 * Firebase IDトークンをAuthorizationヘッダーに自動付与する。
 *
 * 変更履歴:
 *   2026-04-17: デプロイ直後の一時的な 502/503/504 エラーで画面が崩れる問題対策として
 *     GET/HEAD リクエストの自動リトライ（指数バックオフ）を追加
 *   2026-04-28: ApiError クラスを追加し、4xx エラー時の構造化レスポンス
 *     （例: 409 の詳細 dict）を呼び出し側で参照できるようにした（Phase 1-C M-MVP Q9）
 */

export class ApiError extends Error {
  status: number;
  // FastAPI HTTPException が detail に dict を渡した場合の構造化情報
  // 例: 409 で {id, name_ja, blocking_references, detail} を返したいとき
  responseDetail: unknown;

  constructor(message: string, status: number, responseDetail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.responseDetail = responseDetail;
  }
}

import { auth } from "./firebase";

const API_BASE = "/api/v1";

// リトライ対象のHTTPステータス（一時的なインフラエラー）
const RETRYABLE_STATUS = new Set([502, 503, 504]);
// 最大リトライ回数（GET/HEAD の冪等なリクエストのみ）
const MAX_RETRIES = 3;
// 初回リトライまでの待機時間（ミリ秒）。指数バックオフで 500ms → 1000ms → 2000ms
const BASE_DELAY_MS = 500;

async function getAuthHeaders(): Promise<HeadersInit> {
  const user = auth.currentUser;
  if (!user) throw new Error("認証されていません");
  const token = await user.getIdToken();
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = await getAuthHeaders();
  const method = (options.method || "GET").toUpperCase();
  // POST/PATCH/PUT/DELETE は二重送信防止のためリトライしない
  const idempotent = method === "GET" || method === "HEAD";
  const maxRetries = idempotent ? MAX_RETRIES : 0;

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (attempt > 0) {
      // 指数バックオフ: 500ms, 1000ms, 2000ms
      await sleep(BASE_DELAY_MS * Math.pow(2, attempt - 1));
    }

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: { ...headers, ...options.headers },
      });

      // 5xx 系の一時エラーはリトライ
      if (RETRYABLE_STATUS.has(res.status) && attempt < maxRetries) {
        lastError = new Error(`HTTP ${res.status}`);
        continue;
      }

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail;
        // detail が文字列ならそのままメッセージ、dict なら detail フィールドを優先
        const message =
          typeof detail === "string"
            ? detail
            : detail?.detail || `HTTP ${res.status}`;
        throw new ApiError(message, res.status, detail);
      }
      if (res.status === 204) return undefined as T;
      return res.json();
    } catch (err) {
      // ネットワークエラー（fetch 自体の失敗）はリトライ
      // fetch は TypeError を投げる（例: net::ERR_CONNECTION_REFUSED）
      if (err instanceof TypeError && attempt < maxRetries) {
        lastError = err;
        continue;
      }
      throw err;
    }
  }

  throw lastError || new Error("リクエストに失敗しました");
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(data) }),
  put: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(data) }),
  patch: <T>(path: string, data: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (path: string) =>
    request<void>(path, { method: "DELETE" }),
};
