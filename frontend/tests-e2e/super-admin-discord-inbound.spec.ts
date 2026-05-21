/**
 * spec.md v1.1 F5 (Sprint 5) — /super-admin/inbound の E2E。
 *
 * AC5.5: 中央 admin で /super-admin/inbound を開く → tenant_006 に予め INSERT
 *        した 3 件が時系列降順で表示される。
 *
 * 既存 super-admin-llm-budget.spec.ts と同パターン: Playwright の page.route で
 * /api/v1/* を mock する。実 backend での AC 確認は backend pytest 側で別途
 * (test_super_admin_inbound_api.py + test_discord_bot_receiver.py)。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks = (isSuperAdmin: boolean): MockMap => ({
  "GET /me/permissions": {
    permissions: ["dashboard.view"],
    is_super_admin: isSuperAdmin,
  },
  "GET /staff/me": {
    id: 1,
    primary_email: "review@salesanchor.jp",
    ui_preferences: {
      dark_mode: false,
      show_chat_menu: true,
      show_sales_menu: true,
      show_settings_menu: true,
      show_admin_menu: true,
      show_buddy_menu: true,
      show_sidebar: true,
    },
  },
});

const sampleInbound = [
  {
    id: 301,
    discord_message_id: "1234567890123456789",
    discord_channel_id: "9876543210987654321",
    supplier_id: 11,
    supplier_name: "リサ商店",
    raw_content_preview: "ピカチュウ AR 3枚 @1500円",
    parse_status: "parsed_rule_only",
    parse_engine: "rule_v1",
    received_at: "2026-05-22T12:00:00+00:00",
    llm_cost_usd: null,
  },
  {
    id: 302,
    discord_message_id: "1234567890123456790",
    discord_channel_id: "9876543210987654321",
    supplier_id: 11,
    supplier_name: "リサ商店",
    raw_content_preview: "リザードン eX SAR 2枚 @18000円",
    parse_status: "parsed_llm",
    parse_engine: "hybrid_rule_v1_llm_v1",
    received_at: "2026-05-22T11:45:00+00:00",
    llm_cost_usd: "0.0012",
  },
  {
    id: 303,
    discord_message_id: "1234567890123456791",
    discord_channel_id: "9876543210987654321",
    supplier_id: null,
    supplier_name: null,
    raw_content_preview: "ノイズメッセージ（routing 未登録）",
    parse_status: "ignored_routing",
    parse_engine: null,
    received_at: "2026-05-22T11:30:00+00:00",
    llm_cost_usd: null,
  },
];

test.describe("Sprint 5 / F5 — /super-admin/inbound 一覧", () => {
  test("AC5.5: 中央 admin で 3 件が時系列降順で表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/inbound/discord": sampleInbound,
    });
    await page.goto("/super-admin/inbound");

    // 一覧テーブルが表示される
    await expect(page.getByTestId("inbound-table")).toBeVisible();

    // 3 件すべての row が描画される
    await expect(page.getByTestId("inbound-row-301")).toBeVisible();
    await expect(page.getByTestId("inbound-row-302")).toBeVisible();
    await expect(page.getByTestId("inbound-row-303")).toBeVisible();

    // 行順は API 戻り順 (時系列降順)。row 301 が row 302 より上にあることを確認
    const rows = await page.getByTestId(/^inbound-row-/).all();
    expect(rows.length).toBe(3);
    // 1 行目の testid が 301 (= 最新) であること
    await expect(rows[0]).toHaveAttribute("data-testid", "inbound-row-301");

    // 各 status バッジが正しく付く
    await expect(page.getByTestId("status-301")).toContainText(/解析済|Parsed/);
    await expect(page.getByTestId("status-302")).toContainText(/解析済|Parsed/);
    await expect(page.getByTestId("status-303")).toContainText(
      /未登録|unmapped|Routing/i,
    );
  });

  test("AC5.5 (negative): is_super_admin=false なら 403 メッセージ表示", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/inbound");

    // 一覧テーブルは描画されない
    await expect(page.getByTestId("inbound-table")).toHaveCount(0);

    // 403 メッセージ (accessDenied) が表示される
    await expect(page.getByRole("alert")).toContainText(
      /Jarvis|Central|運用 admin|admins|中央/,
    );
  });

  test("AC5.5 (filter): parse_status フィルタで絞り込み", async ({ page }) => {
    await installAuthBypass(page);
    // 初回 GET は全件、フィルタ後 GET は 1 件のみ返す
    let callCount = 0;
    await page.route("**/api/v1/super-admin/inbound/discord**", async (route) => {
      callCount += 1;
      const url = new URL(route.request().url());
      const status = url.searchParams.get("parse_status");
      const data =
        status === "ignored_routing"
          ? sampleInbound.filter((m) => m.parse_status === "ignored_routing")
          : sampleInbound;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(data),
      });
    });
    await mockApi(page, baseMocks(true));
    await page.goto("/super-admin/inbound");

    await expect(page.getByTestId("inbound-table")).toBeVisible();
    await expect(page.getByTestId(/^inbound-row-/)).toHaveCount(3);

    // filter dropdown で ignored_routing を選択
    await page.getByTestId("filter-parse-status").selectOption("ignored_routing");

    // 1 件のみ表示される (303)
    await expect(page.getByTestId("inbound-row-303")).toBeVisible();
    await expect(page.getByTestId(/^inbound-row-/)).toHaveCount(1);
    expect(callCount).toBeGreaterThanOrEqual(2);
  });
});
