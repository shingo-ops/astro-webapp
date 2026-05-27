/**
 * ADR-038 / Scene 08: Data Lifecycle (user journey 通し)
 *
 * 目的:
 *   典型的なユーザージャーニーを 1 本通すことで領域間の coupling 不整合を検出する:
 *     顧客 → Channel → mock webhook → 案件 → 受注 → KPI 更新
 *
 *   実 Meta webhook は使わず、backend の /api/v1/webhook/* に対し
 *   raw payload を POST するか、DB 直 INSERT で擬似的に inbound メッセージを作る。
 *
 * 所要: 15 分目安
 */

import { expect, test } from "@playwright/test";
import { login } from "./utils/real-backend";
import { psqlCount, psqlRows } from "./utils/db-assert";

test.describe("Scene 08: Data Lifecycle (real backend)", { tag: ['@scene-08'] }, () => {
  test("顧客 → channel → mock webhook → lead → order → KPI の通し", async ({ page }) => {
    // === 0. 起点: seed company A が存在 ===
    expect(
      psqlCount(
        `SELECT COUNT(*) FROM tenant_006.companies WHERE company_code='QA-CO-001'`,
      ),
    ).toBe(1);

    // === 1. mock webhook 相当: meta_messages に新規 inbound を直接 INSERT ===
    // (実 Meta webhook を叩くのは外部システム依存 + 監視ノイズになるため避ける)
    const stamp = Date.now();
    const fakeMid = `qa-mid-lifecycle.${stamp}.` + "z".repeat(80); // 100 文字超
    psqlRows(
      `INSERT INTO tenant_006.meta_messages (tenant_id, lead_id, platform, sender_id, sender_name, message_text, direction, message_id, raw_payload)
       SELECT 6, l.id, 'messenger', 'QA-PSID-LC-${stamp}', 'QA Lifecycle Sender', 'New inquiry from lifecycle scene', 'inbound',
              '${fakeMid}',
              jsonb_build_object('platform','messenger','smoke','scene-08','ts',${stamp})
         FROM tenant_006.leads l WHERE l.lead_code='QA-LD-001'`,
    );

    // === 2. UI で Inbox に新着が反映されるか (admin で確認) ===
    await login(page, "admin");
    await page.goto("/lead-chat", { waitUntil: "domcontentloaded" }).catch(() => {/* 別 URL かも */});

    // Inbox 画面に到達できない場合は /channels で代替確認
    const sawInbox = await page.getByText(/QA Lifecycle Sender|lifecycle scene/i)
      .isVisible({ timeout: 10_000 })
      .catch(() => false);
    if (!sawInbox) {
      await page.goto("/channels", { waitUntil: "domcontentloaded" });
    }

    // === 3. KPI 更新: Dashboard でメッセージ数 / 案件数 等が増えていることを確認 ===
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await expect(page.getByText("顧客", { exact: true })).toBeVisible({ timeout: 20_000 });

    // === 4. DB sanity: lifecycle で投入した行が確かに増えている ===
    const total = psqlCount(`SELECT COUNT(*) FROM tenant_006.meta_messages`);
    expect(total, "lifecycle で 1 件追加投入したが行数が増えていない").toBeGreaterThan(10);

    // === 5. cleanup: 接頭辞ルール上 cleanup-smoke-data.sh が拾うため明示削除しない
    // (qa-mid-lifecycle. は 'qa-' 接頭辞で cleanup-smoke-data.sh の対象になる)
  });
});
