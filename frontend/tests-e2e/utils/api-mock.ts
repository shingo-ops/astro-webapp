/**
 * API mock helper for Playwright E2E (Phase 1-E F2-S3).
 *
 * frontend は `/api/v1/...` を叩く（vite dev server で proxy 想定だが、
 * E2E では proxy せず Playwright `page.route` で fixture を返す）。
 *
 * 各 spec で以下のように使う:
 *
 *   import { mockApi } from "../utils/api-mock";
 *   await mockApi(page, {
 *     "GET /conversations": conversations,
 *     "GET /leads/5001/messages": messages,
 *     "POST /leads/5001/messages/mark-read": { marked_count: 1 },
 *   });
 *
 * Key 形式: "<METHOD> <PATH>"（PATH は /api/v1 prefix 抜き）。
 * 値は object（自動で JSON 化）か `{ status, body }` の詳細形式。
 */

import type { Page, Route } from "@playwright/test";

export interface MockResponseDetail {
  status?: number;
  body?: unknown;
  headers?: Record<string, string>;
  contentType?: string;
}

export type MockEntry = unknown | MockResponseDetail | ((route: Route) => Promise<void> | void);

export type MockMap = Record<string, MockEntry>;

const API_PREFIX = "/api/v1";

function isResponseDetail(v: unknown): v is MockResponseDetail {
  return (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    ("status" in v || "body" in v || "headers" in v || "contentType" in v)
  );
}

/**
 * /api/v1/<path> へのリクエストを fixture map で mock する。
 *
 * - 同じ key は最後に定義された値で上書きされる
 * - 一致しない場合は 404 を返す（テストの想定外を炙り出す）
 *
 * @returns 解除関数（不要時は無視可能）
 */
export async function mockApi(page: Page, mocks: MockMap): Promise<() => Promise<void>> {
  const compiledKeys = Object.keys(mocks);

  const handler = async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (!url.pathname.startsWith(API_PREFIX)) {
      await route.continue();
      return;
    }
    const method = req.method().toUpperCase();
    const pathOnly = url.pathname.substring(API_PREFIX.length);

    // 完全一致を優先
    const exactKey = `${method} ${pathOnly}`;
    let matched: { key: string; entry: MockEntry } | null = null;
    if (exactKey in mocks) {
      matched = { key: exactKey, entry: mocks[exactKey] };
    } else {
      // path のみの一致（method ANY）
      for (const key of compiledKeys) {
        const [m, p] = key.split(" ", 2);
        if (m === method && p === pathOnly) {
          matched = { key, entry: mocks[key] };
          break;
        }
      }
    }

    if (!matched) {
      // 未定義の path は 404 で fail-fast
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({
          detail: `[E2E] no mock for ${method} ${pathOnly}`,
        }),
      });
      return;
    }

    const entry = matched.entry;
    if (typeof entry === "function") {
      await (entry as (r: Route) => Promise<void> | void)(route);
      return;
    }

    if (isResponseDetail(entry)) {
      await route.fulfill({
        status: entry.status ?? 200,
        contentType: entry.contentType ?? "application/json",
        headers: entry.headers,
        body:
          typeof entry.body === "string"
            ? entry.body
            : JSON.stringify(entry.body ?? {}),
      });
      return;
    }

    // 素の object → そのまま JSON 化して 200 で返す
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(entry),
    });
  };

  await page.route(/\/api\/v1\/.*/, handler);

  return async () => {
    await page.unroute(/\/api\/v1\/.*/, handler);
  };
}
