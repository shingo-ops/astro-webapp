/**
 * JSON fixture loader（Phase 1-E F2-S3）。
 *
 * Playwright の TS loader は ESM 互換で、`import x from "./x.json"` が
 * `import attribute "type: json"` を要求するため Node 22 系 + tsx で素直に通らない。
 * ここでは fs.readFileSync で読み込む helper を提供する。
 *
 * 使い方:
 *   import { loadFixture } from "../utils/fixtures";
 *   const dashboard = loadFixture<typeof import("../fixtures/mock-dashboard.json")>("mock-dashboard.json");
 *
 * もしくは：
 *   const dashboard = loadFixture("mock-dashboard.json") as DashboardFixture;
 */

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = resolve(__dirname, "..", "fixtures");

const cache = new Map<string, unknown>();

export function loadFixture<T = unknown>(filename: string): T {
  if (cache.has(filename)) {
    return cache.get(filename) as T;
  }
  const content = readFileSync(join(FIXTURES_DIR, filename), "utf-8");
  const parsed = JSON.parse(content) as T;
  cache.set(filename, parsed);
  return parsed;
}
