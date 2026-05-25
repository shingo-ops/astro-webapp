/**
 * spec.md v1.2 F9 (Sprint 9) — /super-admin/phase-switch の Playwright E2E。
 *
 * AC9.3: Phase 切替は admin のみ可能 (is_super_admin=false なら 403)
 * AC9.5: 現在 Phase A が表示され、B/C ボタンが disabled で
 *        「別 ADR で検討中」のツールチップが出ること
 *
 * 注意:
 *   実 backend には繋がず Playwright route で /api/v1/* を mock する。
 *   実 backend での AC 確認は backend pytest + 本番 VPS スモークで実施。
 */
import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";

const baseMocks = (isSuperAdmin: boolean, currentPhase: "A" | "B" | "C" = "A"): MockMap => ({
  "GET /me/permissions": {
    permissions: ["dashboard.view"],
    is_super_admin: isSuperAdmin,
    tenant_id: 6,
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
  "GET /super-admin/phase-switch/6": {
    tenant_id: 6,
    phase: currentPhase,
    allowed_phases: ["A", "B", "C"],
    scoped_phases: ["A"],
  },
});

test.describe("Sprint 9 / F9 v1.2 — /super-admin/phase-switch", () => {
  test("AC9.3: is_super_admin=false の場合は 403 メッセージが表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(false));
    await page.goto("/super-admin/phase-switch");

    await expect(page.getByRole("alert")).toContainText(/運用|admin|アクセスできません|アクセスできます|forbidden/i);
  });

  test("AC9.5: 現在 Phase A 表示 + B/C ボタンが disabled (Out-of-scope)", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(true, "A"));
    await page.goto("/super-admin/phase-switch");

    // 現在 Phase A が表示される
    await expect(page.getByTestId("current-phase")).toContainText("Phase A");

    // 常時表示の warning banner があること
    await expect(page.getByTestId("phase-a-banner")).toBeVisible();
    await expect(page.getByTestId("phase-a-banner")).toContainText(/Phase A|並走|GS|spreadsheet/i);

    // Phase A ボタンは current なので disabled
    const btnA = page.getByTestId("phase-btn-A");
    await expect(btnA).toBeDisabled();
    await expect(btnA).toHaveAttribute("data-current", "true");

    // Phase B / C は Out-of-scope なので disabled + ツールチップ
    const btnB = page.getByTestId("phase-btn-B");
    await expect(btnB).toBeDisabled();
    await expect(btnB).toHaveAttribute("data-scoped", "false");
    // Tooltip 内容（title 属性）
    await expect(btnB).toHaveAttribute(
      "title",
      /Out-of-scope|別 ADR|separate ADR/i,
    );

    const btnC = page.getByTestId("phase-btn-C");
    await expect(btnC).toBeDisabled();
    await expect(btnC).toHaveAttribute("data-scoped", "false");
  });

  test("AC9.5: scoped_phases に含まれていない Phase は disabled で badge 表示", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, baseMocks(true, "A"));
    await page.goto("/super-admin/phase-switch");

    const btnB = page.getByTestId("phase-btn-B");
    await expect(btnB).toContainText(/別 ADR|separate ADR/i);

    const btnC = page.getByTestId("phase-btn-C");
    await expect(btnC).toContainText(/別 ADR|separate ADR/i);
  });
});
