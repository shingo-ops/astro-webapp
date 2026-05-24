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
// fetchタイムアウト（ミリ秒）。重いSQLが最適化されたら 10_000 に短縮予定
const FETCH_TIMEOUT_MS = 25_000;
// Blob取得（CSVエクスポート等）のタイムアウト（ミリ秒）
const BLOB_FETCH_TIMEOUT_MS = 120_000;

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

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    try {
      const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: { ...headers, ...options.headers },
        signal: controller.signal,
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
      // タイムアウト（AbortError）はリトライせず即座に伝播
      if (err instanceof Error && err.name === "AbortError") throw err;
      // ネットワークエラー（fetch 自体の失敗）はリトライ
      // fetch は TypeError を投げる（例: net::ERR_CONNECTION_REFUSED）
      if (err instanceof TypeError && attempt < maxRetries) {
        lastError = err;
        continue;
      }
      throw err;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  throw lastError || new Error("リクエストに失敗しました");
}

/**
 * Blob 取得用（CSV エクスポート等）。Authorization ヘッダー付きで Blob を返す。
 * spec.md v1.1 F2 (Sprint 2) で導入。リトライは GET と同じ扱い。
 */
async function requestBlob(path: string): Promise<Blob> {
  const headers = await getAuthHeaders();
  // Blob 取得は Content-Type を勝手に上書きしない（サーバー側の text/csv を尊重）
  const { "Content-Type": _ct, ...authOnly } = headers as Record<string, string>;
  let lastError: Error | null = null;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      await sleep(BASE_DELAY_MS * Math.pow(2, attempt - 1));
    }
    const blobController = new AbortController();
    const blobTimeoutId = setTimeout(() => blobController.abort(), BLOB_FETCH_TIMEOUT_MS);

    try {
      const res = await fetch(`${API_BASE}${path}`, { method: "GET", headers: authOnly, signal: blobController.signal });
      if (RETRYABLE_STATUS.has(res.status) && attempt < MAX_RETRIES) {
        lastError = new Error(`HTTP ${res.status}`);
        continue;
      }
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new ApiError(body || `HTTP ${res.status}`, res.status, body);
      }
      return await res.blob();
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") throw err;
      if (err instanceof TypeError && attempt < MAX_RETRIES) {
        lastError = err;
        continue;
      }
      throw err;
    } finally {
      clearTimeout(blobTimeoutId);
    }
  }
  throw lastError || new Error("Blob 取得に失敗しました");
}

/**
 * multipart/form-data POST（CSV import 等）。
 * fetch に FormData を渡すと boundary 付き Content-Type を自動付与してくれるため、
 * 既存の application/json ヘッダーは上書きする必要がある。
 */
async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const headers = await getAuthHeaders();
  const { "Content-Type": _ct, ...authOnly } = headers as Record<string, string>;
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: authOnly,
    body,
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    const detail = (errBody as { detail?: unknown }).detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail as { detail?: string })?.detail || `HTTP ${res.status}`;
    throw new ApiError(message, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
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
  // spec.md v1.1 F2 (Sprint 2)
  getBlob: (path: string) => requestBlob(path),
  postForm: <T>(path: string, body: FormData) => requestForm<T>(path, body),
};
