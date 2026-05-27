/**
 * ADR-038 / Scene 04: Inbox & Channels (重要シナリオ)
 *
 * 目的 (ADR-038 §成功基準 #2):
 *   過去 2026-05-15 の 3 件のバグを意図的に再現したとき、本 scene が確実に
 *   FAIL することを Phase 1 終了時に検証する。具体的には:
 *
 *     a) meta_page_routing 未登録 → assertMetaPageRoutingInSync で検出
 *     b) meta_messages 9 カラム欠落 (migration 041 未適用) → information_schema で検出
 *     c) message_id VARCHAR(100) → assertMessageIdIsText で検出
 *
 * 副次目的:
 *   - Inbox 画面で接続済 2 件 (QA Test Page Alpha / Beta) が表示される
 *   - メッセージ受信 → 返信 → DB row 増加の最小往復
 *
 * 所要: 20 分目安
 */

import { expect, test } from "@playwright/test";
import { login } from "./utils/real-backend";
import {
  assertMessageIdIsText,
  assertMetaPageRoutingInSync,
  psqlCount,
  psqlRows,
} from "./utils/db-assert";

test.describe("Scene 04: Inbox & Channels (real backend)", { tag: ['@scene-04'] }, () => {
  test("ADR-026 regression guard: meta_messages.message_id 列が TEXT 型", () => {
    assertMessageIdIsText("tenant_006");
  });

  test("ADR-024 regression guard: tenant_meta_config と meta_page_routing が同期", () => {
    assertMetaPageRoutingInSync(6);
  });

  test("migration 041 regression guard: meta_messages の 9 カラム拡張が適用されている", () => {
    const expectedCols = [
      "recipient_id",
      "messaging_type",
      "message_tag",
      "sent_by_staff_id",
      "error_code",
      "error_message",
      "message_id",
      "seen_at",
      "seen_by_staff_id",
    ];
    const rows = psqlRows(
      `SELECT column_name FROM information_schema.columns
       WHERE table_schema='tenant_006' AND table_name='meta_messages'
         AND column_name = ANY(ARRAY['${expectedCols.join("','")}'])`,
    );
    const present = new Set(rows.map((r) => r[0]));
    const missing = expectedCols.filter((c) => !present.has(c));
    expect(missing, "meta_messages から拡張カラムが欠落 (migration 041 未適用?)").toEqual([]);
  });

  test("seed 済 meta_messages が 10 件 (messenger 6 + instagram 4) 入っている", () => {
    expect(psqlCount(`SELECT COUNT(*) FROM tenant_006.meta_messages`)).toBe(10);
    expect(psqlCount(`SELECT COUNT(*) FROM tenant_006.meta_messages WHERE platform='messenger'`)).toBe(6);
    expect(psqlCount(`SELECT COUNT(*) FROM tenant_006.meta_messages WHERE platform='instagram'`)).toBe(4);
    // 100 文字超え message_id が ADR-026 で扱えるようになっている根拠
    expect(
      psqlCount(`SELECT COUNT(*) FROM tenant_006.meta_messages WHERE length(message_id) > 100`),
    ).toBeGreaterThanOrEqual(1);
  });

  test("Inbox / Channels 画面に接続済 2 件 (Alpha / Beta) が表示される", async ({ page }) => {
    await login(page, "admin");
    // routing は admin-only ではないが、admin で確認するのが最大権限の動作確認になる
    await page.goto("/channels", { waitUntil: "domcontentloaded" });

    await expect(page.getByText(/QA Test Page Alpha/i)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/QA Test Page Beta/i)).toBeVisible();
  });
});
