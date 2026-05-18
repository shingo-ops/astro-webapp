/**
 * ADR-038 / QA Smoke Suite — DB 直叩き assert ヘルパー
 *
 * scene-04 (Inbox & Channels) で「UI 上は OK でも DB 側で OAuth 状態が不整合」
 * という ADR-024 系のバグを検出するため、Playwright テストから psql を直接
 * 起動して結果を取得する。
 *
 * 設計理由:
 *   - npm 依存を増やさない (`pg` を入れない) — self-hosted runner 上には
 *     psql が既に在る前提で OK
 *   - 出力 parse 用に `psql -At` (タブ区切り、no-header) を使う
 *
 * 必須環境変数:
 *   DATABASE_URL  postgresql:// または postgresql+asyncpg:// (asyncpg は剥がす)
 *
 * 関連:
 *   docs/adr/ADR-038-qa-smoke-suite.md §成功基準 #2
 *   docs/adr/ADR-024_meta_subscription_drift.md
 *   docs/adr/ADR-026_meta_message_id_text.md
 *   docs/adr/ADR-036-tenant-schema-integrity.md
 */

import { spawnSync } from "node:child_process";

function psqlUrl(): string {
  const raw = process.env.DATABASE_URL;
  if (!raw) {
    throw new Error(
      "QA smoke abort: DATABASE_URL is not set. db-assert は実 backend に接続できません",
    );
  }
  return raw.replace(/^postgresql\+asyncpg:/, "postgresql:");
}

/**
 * PostgreSQL 文字列リテラル用の安全な quote。
 * シングルクォートをエスケープしてバインド代替として使う。
 * scene-06 等で email / 任意文字列を SQL に埋め込む場合の最低限の防御。
 */
export function pgQuote(s: string): string {
  return `'${s.replace(/'/g, "''")}'`;
}

/**
 * psql に SQL 1 文を投げて結果を 2 次元配列 (行 × 列) で返す。
 * 失敗時は throw。
 */
export function psqlRows(sql: string): string[][] {
  const r = spawnSync("psql", [psqlUrl(), "-At", "-F", "\t", "-c", sql], {
    encoding: "utf-8",
    timeout: 15_000,
  });
  if (r.status !== 0) {
    throw new Error(
      `psql failed (status=${r.status}): ${r.stderr || r.stdout || "<no output>"}`,
    );
  }
  return r.stdout
    .split("\n")
    .filter((l) => l.length > 0)
    .map((l) => l.split("\t"));
}

/**
 * SELECT COUNT(*) のショートカット。
 */
export function psqlCount(sql: string): number {
  const rows = psqlRows(sql);
  if (rows.length === 0) return 0;
  return Number(rows[0][0] ?? "0");
}

/**
 * ADR-026 検証: meta_messages.message_id が VARCHAR(100) ではなく TEXT 型である
 * ことを information_schema から確認する。VARCHAR(100) のままだと 100 文字超え
 * の Meta mid を保存できず、Sprint 7 で発覚した本番バグが再発する。
 */
export function assertMessageIdIsText(schema: string = "tenant_006"): void {
  const rows = psqlRows(
    `SELECT data_type, character_maximum_length
     FROM information_schema.columns
     WHERE table_schema='${schema}' AND table_name='meta_messages' AND column_name='message_id'`,
  );
  if (rows.length === 0) {
    throw new Error(
      `ADR-038 scene-04 assert FAIL: ${schema}.meta_messages.message_id 列が存在しない`,
    );
  }
  const [dataType, maxLen] = rows[0];
  if (dataType !== "text") {
    throw new Error(
      `ADR-026 regression: ${schema}.meta_messages.message_id is '${dataType}' (max=${maxLen}), expected 'text'`,
    );
  }
}

/**
 * ADR-024 検証: tenant_meta_config に接続済 (is_active=TRUE) 行があるとき、
 * public.meta_page_routing に同じ tenant_id / config_id の routing 行が必ず
 * 存在することを assert する。片側だけだと webhook が受信できないバグになる。
 */
export function assertMetaPageRoutingInSync(tenantId: number = 6): void {
  const mismatchCount = psqlCount(
    `SELECT COUNT(*) FROM tenant_${String(tenantId).padStart(3, "0")}.tenant_meta_config c
     WHERE c.is_active = TRUE
       AND NOT EXISTS (
         SELECT 1 FROM public.meta_page_routing r
         WHERE r.tenant_id = c.tenant_id AND r.config_id = c.id AND r.is_active = TRUE
       )`,
  );
  if (mismatchCount > 0) {
    throw new Error(
      `ADR-024 regression: tenant_${tenantId} で tenant_meta_config に対応する meta_page_routing が ${mismatchCount} 件欠落`,
    );
  }
}

/**
 * ADR-038 seed 行数の sanity check。reset-tenant.sh 後に行数が seed 表と
 * 揃っているか確認する。シナリオ先頭で呼び出すと「seed 漏れ」を早期検知できる。
 */
export function assertSeedRowCounts(tenantId: number = 6): void {
  const schema = `tenant_${String(tenantId).padStart(3, "0")}`;
  const checks: Array<[string, string, number]> = [
    ["companies", `SELECT COUNT(*) FROM ${schema}.companies WHERE company_code LIKE 'QA-CO-%'`, 5],
    ["contacts",  `SELECT COUNT(*) FROM ${schema}.contacts  WHERE contact_code  LIKE 'QA-CT-%'`, 5],
    ["leads",     `SELECT COUNT(*) FROM ${schema}.leads     WHERE lead_code     LIKE 'QA-LD-%'`, 5],
    ["orders",    `SELECT COUNT(*) FROM ${schema}.orders    WHERE order_number  LIKE 'QA-OR-%'`, 3],
    ["products",  `SELECT COUNT(*) FROM ${schema}.products  WHERE product_code  LIKE 'QA-PR-%'`, 5],
    ["meta_messages", `SELECT COUNT(*) FROM ${schema}.meta_messages`, 10],
    ["tenant_meta_config",
      `SELECT COUNT(*) FROM ${schema}.tenant_meta_config WHERE tenant_id=${tenantId} AND is_active=TRUE`, 2],
    ["meta_page_routing",
      `SELECT COUNT(*) FROM public.meta_page_routing WHERE tenant_id=${tenantId} AND is_active=TRUE`, 2],
  ];
  const failures: string[] = [];
  for (const [name, sql, expected] of checks) {
    const got = psqlCount(sql);
    if (got !== expected) {
      failures.push(`${name}: expected=${expected}, got=${got}`);
    }
  }
  if (failures.length > 0) {
    throw new Error(
      `ADR-038 seed sanity FAIL — reset-tenant.sh を再実行してください\n  ${failures.join("\n  ")}`,
    );
  }
}
