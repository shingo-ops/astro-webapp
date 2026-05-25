/**
 * spec.md v1.1 F2 (Sprint 2) — /admin/inventory-visibility の Playwright E2E。
 *
 * AC2.8: テナント admin がロール × inventory.visibility.* のマトリクスを編集できる
 *        - tenant.inventory_visibility.edit 権限なしなら 403 メッセージ
 *        - 権限ありならマトリクス UI が描画 + 保存ボタンで PUT が飛ぶ
 *
 * 注意: 実際の在庫マスク挙動 (F7 連携) は Sprint 7 で検証。
 *       本テストは権限切替と保存 API 呼び出しのみを検証する。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks = (perms: string[]): MockMap => ({
  "GET /me/permissions": {
    permissions: perms,
    is_super_admin: false,
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
});

const matrixFixture = {
  visibility_keys: [
    "inventory.visibility.full",
    "inventory.visibility.staff",
    "inventory.visibility.viewer",
  ],
  rows: [
    { role_id: 10, role_name: "オーナー", permission_key: "inventory.visibility.full", is_granted: true },
    { role_id: 10, role_name: "オーナー", permission_key: "inventory.visibility.staff", is_granted: true },
    { role_id: 10, role_name: "オーナー", permission_key: "inventory.visibility.viewer", is_granted: true },
    { role_id: 11, role_name: "経理", permission_key: "inventory.visibility.full", is_granted: false },
    { role_id: 11, role_name: "経理", permission_key: "inventory.visibility.staff", is_granted: true },
    { role_id: 11, role_name: "経理", permission_key: "inventory.visibility.viewer", is_granted: true },
  ],
};

test.describe("Sprint 2 / F2 — /admin/inventory-visibility", () => {
  test("AC2.8: 権限なしユーザーは 403 メッセージが表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(["dashboard.view"]));
    await page.goto("/admin/inventory-visibility");

    await expect(page.getByRole("alert")).toContainText(
      /tenant\.inventory_visibility\.edit|権限|permission/i,
    );
    await expect(page.getByTestId("visibility-matrix")).toHaveCount(0);
  });

  test("AC2.8: 権限ありの場合、マトリクスが描画され保存ボタンで PUT が飛ぶ", async ({ page }) => {
    await installAuthBypass(page);
    let putCalled = false;
    let putBody: unknown = null;
    await mockApi(page, {
      ...baseMocks(["dashboard.view", "tenant.inventory_visibility.edit"]),
      "GET /admin/inventory-visibility/matrix": matrixFixture,
      "PUT /admin/inventory-visibility/roles/11": async (route) => {
        putCalled = true;
        putBody = JSON.parse(route.request().postData() || "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ role_id: 11, applied_keys: [] }),
        });
      },
    });
    await page.goto("/admin/inventory-visibility");

    // マトリクス描画
    await expect(page.getByTestId("visibility-matrix")).toBeVisible();
    await expect(page.locator("table tbody tr")).toHaveCount(2);

    // 経理ロールの inventory.visibility.full チェックボックスを OFF→ON
    const checkbox = page.getByTestId("vis-11-inventory.visibility.full");
    await expect(checkbox).not.toBeChecked();
    await checkbox.check();
    await expect(checkbox).toBeChecked();

    // 保存ボタンを押す (経理行の保存)
    const saveButtons = page.getByRole("button", { name: /save|保存/i });
    // 2 行あるので、経理行 (= tr index 1) の中の保存ボタン
    await page.locator("table tbody tr").nth(1).getByRole("button").first().click();

    // PUT が呼ばれて、visibility_keys にチェックした 3 個（full + staff + viewer）が含まれる
    await expect.poll(() => putCalled).toBeTruthy();
    expect(putBody).toMatchObject({
      role_id: 11,
      visibility_keys: expect.arrayContaining([
        "inventory.visibility.full",
      ]),
    });
  });
});
