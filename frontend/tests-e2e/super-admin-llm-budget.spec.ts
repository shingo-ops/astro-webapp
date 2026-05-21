/**
 * spec.md v1.1 F4 (Sprint 4) — /super-admin/masters の LLM 予算タブ E2E。
 *
 * AC4.6: 中央 admin が `/super-admin/masters` → LLM 予算タブ → budget を編集 →
 *        `public.tenant_llm_budgets` に即時反映される。
 *        テナント admin (is_super_admin=false) は到達できない (403)。
 *
 * 注意:
 *   既存 super-admin-masters.spec.ts と同じ「Playwright route で /api/v1/* mock」
 *   パターンで実装。実 backend での AC 確認は backend pytest + 本番 VPS スモークで別途。
 *   実 PostgreSQL での AC4.3 (hard_stop) / AC4.4 (月初リセット) は pytest 側で実 DB 検証。
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

const sampleBudgets = [
  {
    tenant_id: 4,
    tenant_code: "highlife-jpn",
    tenant_name: "HIGH LIFE JPN",
    monthly_budget_usd: "5.00",
    current_month_usd: "0.5234",
    last_reset_at: "2026-05-01T00:00:00+00:00",
    hard_stop: true,
    notify_admin: true,
    created_at: "2026-05-01T00:00:00+00:00",
    updated_at: "2026-05-15T12:00:00+00:00",
  },
  {
    tenant_id: 6,
    tenant_code: "tenant-review",
    tenant_name: "撮影 / QA",
    monthly_budget_usd: "1.00",
    current_month_usd: "0.0001",
    last_reset_at: "2026-05-01T00:00:00+00:00",
    hard_stop: true,
    notify_admin: true,
    created_at: "2026-05-15T00:00:00+00:00",
    updated_at: "2026-05-22T00:00:00+00:00",
  },
];

test.describe("Sprint 4 / F4 — /super-admin/masters LLM 予算タブ", () => {
  test("AC4.6: テナント admin (is_super_admin=false) では LLM 予算タブに到達できない (403 メッセージ)", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/masters");

    await expect(page.getByRole("alert")).toContainText(
      /Jarvis|Central|運用 admin|admins/i,
    );
    // LLM 予算タブ自体が描画されない（タブ list 内のボタンが存在しない）
    await expect(page.getByTestId("super-admin-tab-llmBudget")).toHaveCount(0);
  });

  test("AC4.6: 中央 admin で LLM 予算タブが 5 番目に表示され、一覧と編集ボタンが描画される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/knowledge": [],
      "GET /super-admin/aliases": [],
      "GET /super-admin/tcg/series": [],
      "GET /super-admin/dex/pokemon": [],
      "GET /super-admin/suppliers": [],
      "GET /super-admin/llm-budget": sampleBudgets,
    });
    await page.goto("/super-admin/masters");

    // 5 タブが描画される
    await expect(page.getByTestId("super-admin-tab-knowledge")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-tcg")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-dex")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-suppliers")).toBeVisible();
    await expect(page.getByTestId("super-admin-tab-llmBudget")).toBeVisible();

    // LLM 予算タブを開く
    await page.getByTestId("super-admin-tab-llmBudget").click();
    await expect(page.getByTestId("super-admin-llm-budget-tab")).toBeVisible();

    // 2 行表示される
    await expect(page.getByTestId("llm-budget-row-4")).toBeVisible();
    await expect(page.getByTestId("llm-budget-row-6")).toBeVisible();
    // monthly_budget_usd / current_month_usd が正しく表示される
    await expect(page.getByTestId("llm-budget-row-4")).toContainText("$5.00");
    await expect(page.getByTestId("llm-budget-used-6")).toContainText("$0.0001");
    // 編集ボタンが各行にある
    await expect(page.getByTestId("llm-budget-edit-4")).toBeVisible();
    await expect(page.getByTestId("llm-budget-edit-6")).toBeVisible();
  });

  test("AC4.6: 編集ボタンを押すと編集フォームが開き、PUT で保存される", async ({
    page,
  }) => {
    await installAuthBypass(page);

    let putBody: Record<string, unknown> = {};
    let listCalls = 0;
    const updated = [
      {
        ...sampleBudgets[0],
        monthly_budget_usd: "10.00",
        hard_stop: false,
        notify_admin: false,
      },
      sampleBudgets[1],
    ];

    await mockApi(page, {
      ...baseMocks(true),
      "GET /super-admin/knowledge": [],
      "GET /super-admin/aliases": [],
      "GET /super-admin/tcg/series": [],
      "GET /super-admin/dex/pokemon": [],
      "GET /super-admin/suppliers": [],
      "GET /super-admin/llm-budget": (route) => {
        listCalls++;
        const body = listCalls === 1 ? sampleBudgets : updated;
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "PUT /super-admin/llm-budget/4": async (route) => {
        const req = route.request();
        try {
          putBody = req.postDataJSON() as Record<string, unknown>;
        } catch {
          putBody = {};
        }
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(updated[0]),
        });
      },
    });

    await page.goto("/super-admin/masters");
    await page.getByTestId("super-admin-tab-llmBudget").click();
    await expect(page.getByTestId("super-admin-llm-budget-tab")).toBeVisible();

    // tenant_id=4 の編集ボタン
    await page.getByTestId("llm-budget-edit-4").click();
    await expect(page.getByTestId("llm-budget-edit-form")).toBeVisible();

    // monthly_budget を 10.00 に変更
    const budgetInput = page.getByTestId("llm-budget-input-monthly-budget");
    await budgetInput.fill("10.00");
    // hard_stop / notify_admin を OFF
    await page.getByTestId("llm-budget-input-hard-stop").uncheck();
    await page.getByTestId("llm-budget-input-notify-admin").uncheck();

    // 保存
    await page.getByTestId("llm-budget-save").click();

    // 更新後の一覧で $10.00 になっている
    await expect(page.getByTestId("llm-budget-row-4")).toContainText("$10.00");
    // PUT のリクエスト body が期待通り
    expect(putBody.monthly_budget_usd).toBe("10.00");
    expect(putBody.hard_stop).toBe(false);
    expect(putBody.notify_admin).toBe(false);
  });
});
