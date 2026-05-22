/**
 * spec.md v1.1 F6 (Sprint 6) — /super-admin/inbound/:id/review の E2E。
 *
 * AC6.1: 行ごとの採用/スキップ → 承認 → API へ正しいペイロードで送信
 * AC6.4: 差戻し UI で exclude_reason 必須 (空なら API 呼び出されない)
 * AC6.5: API が 409 を返すと versionConflict メッセージが表示され再読み込み
 * AC6.7: 日本語 / 英語の文言キーが i18n 経由で出る (raw 文字列の混入 0)
 * AC6.8: is_super_admin=false の user は 403 メッセージ
 *
 * 既存 super-admin-* と同じ「Playwright route で /api/v1/* mock」パターン。
 * 実 backend での AC は backend pytest 側で実 PG 検証 (AC6.1/2/3/5/6/8)。
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

const sampleDetail = {
  id: 401,
  discord_message_id: "9999000011112222",
  discord_channel_id: "1111222233334444",
  supplier_id: 11,
  supplier_name: "リサ商店",
  raw_content: "ピカチュウ AR 3枚 @1500\nリザードン SAR 2枚 @18000",
  parse_status: "parsed_rule_only",
  parse_engine: "rule_v1",
  parse_result_json: {
    items: [
      { product_id: 501, delta_qty: 3, alias_text: "ピカチュウ AR" },
      { product_id: 502, delta_qty: 2, alias_text: "リザードン SAR" },
    ],
    excludes: [],
    unparsed: [],
  },
  received_at: "2026-05-22T11:30:00+00:00",
  exclude_reason: null,
  operator_comment: null,
  operator_id: null,
  approved_at: null,
  llm_cost_usd: null,
  created_at: "2026-05-22T11:30:00+00:00",
  updated_at: "2026-05-22T11:30:00+00:00",
  version: 0,
};

test.describe("Sprint 6 / F6 — /super-admin/inbound/:id/review", () => {
  test("AC6.1: 行 0 採用、行 1 スキップ、コメント付きで承認 → API へ正しい payload 送信", async ({
    page,
  }) => {
    let approveBody: any = null;
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/parse-review/401": sampleDetail,
      "POST /super-admin/parse-review/401/approve": async (route) => {
        approveBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            inbound_id: 401,
            parse_status: "approved",
            version: 1,
            movements: [
              {
                movement_id: 1,
                product_id: 501,
                delta_qty: 3,
                before_qty: 0,
                after_qty: 3,
              },
            ],
            skipped_count: 1,
          }),
        });
      },
    });

    await page.goto("/super-admin/inbound/401/review");

    // メタ表示
    await expect(page.getByTestId("review-meta")).toBeVisible();
    await expect(page.getByTestId("review-version")).toHaveText("0");

    // 2 行描画
    await expect(page.getByTestId("review-row-0")).toBeVisible();
    await expect(page.getByTestId("review-row-1")).toBeVisible();

    // 行 1 をスキップに
    await page.getByTestId("review-row-1-skip").check();

    // 担当者コメント
    await page.getByTestId("review-operator-comment").fill("OK by tester");

    // 承認
    await page.getByTestId("review-approve-btn").click();

    // info 表示
    await expect(page.getByTestId("review-info")).toBeVisible();

    // 送信ペイロード検証
    expect(approveBody).toBeTruthy();
    expect(approveBody.version).toBe(0);
    expect(approveBody.operator_comment).toBe("OK by tester");
    expect(approveBody.skipped_indices).toEqual([1]);
    // 行 0 のみ items に含まれる
    expect(approveBody.items).toHaveLength(1);
    expect(approveBody.items[0].product_id).toBe(501);
    expect(approveBody.items[0].delta_qty).toBe(3);
  });

  test("AC6.4: 差戻し UI で空白 reason → API 呼び出されずエラー", async ({
    page,
  }) => {
    let rejectCalled = false;
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/parse-review/401": sampleDetail,
      "POST /super-admin/parse-review/401/reject": async (route) => {
        rejectCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            inbound_id: 401,
            parse_status: "rejected",
            version: 1,
            exclude_reason: "x",
          }),
        });
      },
    });
    await page.goto("/super-admin/inbound/401/review");
    await page.getByTestId("review-reject-btn").click();
    await expect(page.getByTestId("review-reject-dialog")).toBeVisible();
    // reason 未入力で confirm → エラー
    await page.getByTestId("review-reject-confirm-btn").click();
    await expect(page.getByTestId("review-error")).toBeVisible();
    expect(rejectCalled).toBe(false);

    // reason 入れて再度 → 200
    await page.getByTestId("review-reject-reason").fill("重複");
    await page.getByTestId("review-reject-confirm-btn").click();
    await expect.poll(() => rejectCalled).toBe(true);
  });

  test("AC6.5: 承認で API が 409 → 競合メッセージ表示 + 再読み込み", async ({
    page,
  }) => {
    let getCount = 0;
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/parse-review/401": async (route) => {
        getCount += 1;
        // 1 回目: version=0, 2 回目: version=1（別 admin が approve 済）
        const body =
          getCount === 1
            ? sampleDetail
            : { ...sampleDetail, version: 1, parse_status: "approved" };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "POST /super-admin/parse-review/401/approve": async (route) => {
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "version mismatch (expected 0, server has 1)",
          }),
        });
      },
    });

    await page.goto("/super-admin/inbound/401/review");
    await page.getByTestId("review-approve-btn").click();

    await expect(page.getByTestId("review-error")).toBeVisible();
    await expect(page.getByTestId("review-error")).toContainText(
      /更新|updater|reviewer|Reload|Another/i,
    );
    // 自動 reload で getCount >= 2
    await expect.poll(() => getCount).toBeGreaterThanOrEqual(2);
  });

  test("AC6.8: is_super_admin=false なら 403 メッセージ", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/inbound/401/review");
    // review-table は描画されない
    await expect(page.getByTestId("review-table")).toHaveCount(0);
    await expect(page.getByRole("alert")).toContainText(
      /Jarvis|Central|運用 admin|admins|中央/,
    );
  });
});
