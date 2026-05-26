/**
 * spec.md v1.3 F11 AC11.3 + AC11.6 — /super-admin/inbound/:id/review の
 * F6 承認 UI に condition / quantity_offered / unit_price フィールドが
 * 配線され、承認時にバックエンドへ正しく送信されることを Playwright で確認する。
 *
 * AC 対応:
 *   AC11.3: F6 承認時に inventory が UPSERT される (UPSERT 側の DB レベル検証は
 *           backend/tests/test_f11_inventory_upsert.py で実 PG で検証済)
 *   AC11.6: Playwright で AC11.3 を実機検証
 *
 * 本 spec は UI 配線のみカバーする:
 *   - 3 つの新規入力 (condition select / quantity_offered / unit_price) が描画
 *   - 値を入れて承認すると POST body に items[].condition / quantity_offered / unit_price が含まれる
 *   - 空欄なら null として送信される (Pydantic Optional)
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks: MockMap = {
  "GET /me/permissions": {
    permissions: ["dashboard.view"],
    is_super_admin: true,
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
      show_sidebar: true,
    },
  },
};

const sampleDetail = {
  id: 901,
  discord_message_id: "1234000056789999",
  discord_channel_id: "1111222233334444",
  supplier_id: 31,
  supplier_name: "AC11.3 仕入元",
  raw_content: "ピカチュウ AR Box 2セット @4500",
  parse_status: "parsed_rule_only",
  parse_engine: "rule_v1",
  parse_result_json: {
    items: [
      { product_id: 701, delta_qty: 2, alias_text: "ピカチュウ AR Box" },
    ],
    excludes: [],
    unparsed: [],
  },
  received_at: "2026-05-26T09:00:00+00:00",
  exclude_reason: null,
  operator_comment: null,
  operator_id: null,
  approved_at: null,
  llm_cost_usd: null,
  created_at: "2026-05-26T09:00:00+00:00",
  updated_at: "2026-05-26T09:00:00+00:00",
  version: 0,
};

test.describe("Sprint 11 / F11 AC11.3 — ParseReviewPage inventory fields wiring", () => {
  test("condition / quantity_offered / unit_price 入力が描画される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks,
      "GET /super-admin/parse-review/901": sampleDetail,
    });

    await page.goto("/super-admin/inbound/901/review");

    // 3 つの新規入力が row 0 に描画される
    await expect(page.getByTestId("review-row-0-condition")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("review-row-0-quantity-offered")).toBeVisible();
    await expect(page.getByTestId("review-row-0-unit-price")).toBeVisible();
  });

  test("AC11.3: 値を入れて承認 → POST body に items[].condition / quantity_offered / unit_price が乗る", async ({
    page,
  }) => {
    let approveBody: Record<string, unknown> | null = null;
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks,
      "GET /super-admin/parse-review/901": sampleDetail,
      "POST /super-admin/parse-review/901/approve": async (route) => {
        approveBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            inbound_id: 901,
            parse_status: "approved",
            version: 1,
            movements: [
              {
                movement_id: 11,
                product_id: 701,
                delta_qty: 2,
                before_qty: 0,
                after_qty: 2,
              },
            ],
            skipped_count: 0,
          }),
        });
      },
    });

    await page.goto("/super-admin/inbound/901/review");

    // condition / quantity_offered / unit_price を入力
    await page
      .getByTestId("review-row-0-condition")
      .selectOption("sealed");
    await page.getByTestId("review-row-0-quantity-offered").fill("2");
    await page.getByTestId("review-row-0-unit-price").fill("4500");

    // 承認
    await page.getByTestId("review-approve-btn").click();

    await expect.poll(() => approveBody).not.toBeNull();
    expect(approveBody).toBeTruthy();
    const items = (approveBody as Record<string, unknown>).items as Array<
      Record<string, unknown>
    >;
    expect(items).toHaveLength(1);
    expect(items[0].product_id).toBe(701);
    expect(items[0].delta_qty).toBe(2);
    expect(items[0].condition).toBe("sealed");
    expect(items[0].quantity_offered).toBe(2);
    expect(items[0].unit_price).toBe(4500);
  });

  test("空欄のまま承認 → condition / quantity_offered / unit_price が null で送信される", async ({
    page,
  }) => {
    let approveBody: Record<string, unknown> | null = null;
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks,
      "GET /super-admin/parse-review/901": sampleDetail,
      "POST /super-admin/parse-review/901/approve": async (route) => {
        approveBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            inbound_id: 901,
            parse_status: "approved",
            version: 1,
            movements: [],
            skipped_count: 0,
          }),
        });
      },
    });

    await page.goto("/super-admin/inbound/901/review");
    await expect(page.getByTestId("review-row-0-condition")).toBeVisible({
      timeout: 15_000,
    });

    // 空欄のまま承認
    await page.getByTestId("review-approve-btn").click();

    await expect.poll(() => approveBody).not.toBeNull();
    const items = (approveBody as Record<string, unknown>).items as Array<
      Record<string, unknown>
    >;
    expect(items[0].condition).toBeNull();
    expect(items[0].quantity_offered).toBeNull();
    expect(items[0].unit_price).toBeNull();
  });

  test("M5: 2 行 (1 行採用 + 1 行スキップ) で採用行のみに inventory フィールドが乗る", async ({
    page,
  }) => {
    // M5 follow-up: F6 (skipped 切り替え) + F11 AC11.3 (inventory フィールド) の
    // 複合シナリオ。row 0 採用 + row 1 スキップ + row 0 にのみ
    // condition/quantity_offered/unit_price 入力 → POST items に row 0 のみ
    // が含まれ、その row が inventory フィールドを保持していることを確認。
    let approveBody: Record<string, unknown> | null = null;
    const multiRowDetail = {
      ...sampleDetail,
      id: 902,
      raw_content: "ピカチュウ AR Box 2セット @4500\nリザードン SAR 1セット @18000",
      parse_result_json: {
        items: [
          { product_id: 701, delta_qty: 2, alias_text: "ピカチュウ AR Box" },
          { product_id: 702, delta_qty: 1, alias_text: "リザードン SAR" },
        ],
        excludes: [],
        unparsed: [],
      },
    };

    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks,
      "GET /super-admin/parse-review/902": multiRowDetail,
      "POST /super-admin/parse-review/902/approve": async (route) => {
        approveBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            inbound_id: 902,
            parse_status: "approved",
            version: 1,
            movements: [
              {
                movement_id: 21,
                product_id: 701,
                delta_qty: 2,
                before_qty: 0,
                after_qty: 2,
              },
            ],
            skipped_count: 1,
          }),
        });
      },
    });

    await page.goto("/super-admin/inbound/902/review");

    // 2 行描画されるまで待つ
    await expect(page.getByTestId("review-row-0-condition")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("review-row-1-condition")).toBeVisible();

    // row 0 (採用) に inventory フィールド入力
    await page.getByTestId("review-row-0-condition").selectOption("sealed");
    await page.getByTestId("review-row-0-quantity-offered").fill("2");
    await page.getByTestId("review-row-0-unit-price").fill("4500");

    // row 1 をスキップにチェック
    await page.getByTestId("review-row-1-skip").check();

    // 承認
    await page.getByTestId("review-approve-btn").click();

    await expect.poll(() => approveBody).not.toBeNull();
    const body = approveBody as Record<string, unknown>;
    const items = body.items as Array<Record<string, unknown>>;
    const skipped = body.skipped_indices as number[];

    // row 1 はスキップなので items に含まれない (採用行 1 件のみ)
    expect(items).toHaveLength(1);
    expect(items[0].product_id).toBe(701);
    expect(items[0].condition).toBe("sealed");
    expect(items[0].quantity_offered).toBe(2);
    expect(items[0].unit_price).toBe(4500);
    expect(skipped).toEqual([1]);
  });
});
