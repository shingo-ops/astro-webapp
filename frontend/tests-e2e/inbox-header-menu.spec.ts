/**
 * Inbox ヘッダー三点メニュー — レスポンシブ動作 E2E テスト
 *
 * 対象コンポーネント: InboxMessageThread.tsx (.inbox-header-menu-wrap)
 *
 * テスト観点:
 *   - ≤1279px: 三点ボタンが表示され、インラインボタン群は非表示
 *   - 三点ボタンクリックでドロップダウンが開く
 *   - メニュー外クリックでドロップダウンが閉じる
 *   - ≥1280px: インラインボタン群が表示され、三点ボタンは非表示
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");

test.describe("Inbox ヘッダー三点メニュー", () => {
  async function setupInboxWithConversation(page: import("@playwright/test").Page) {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
    });
    await page.goto("/lead-chat");
    await expect(page.getByRole("heading", { name: "受信箱" })).toBeVisible({ timeout: 20_000 });
    await page.locator("button.conversation-item", { hasText: "Taro Sender" }).click();
    await expect(page.locator(".inbox-center-header")).toBeVisible({ timeout: 10_000 });
  }

  test("≤1279px: 三点ボタンが表示され、インラインボタン群は非表示になる", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await setupInboxWithConversation(page);

    // 三点ボタンが表示される
    await expect(page.locator(".inbox-header-menu-btn")).toBeVisible();

    // インラインアクションボタン群は非表示
    await expect(page.locator(".inbox-header-actions")).toBeHidden();
  });

  test("≤1279px: 三点ボタンクリックでドロップダウンが開く", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await setupInboxWithConversation(page);

    const menuBtn = page.locator(".inbox-header-menu-btn");
    const menu = page.locator(".inbox-header-menu");

    // 初期状態: メニューは非表示
    await expect(menu).not.toBeVisible();

    // 三点ボタンをクリック
    await menuBtn.click();

    // メニューが表示される
    await expect(menu).toBeVisible();

    // 4つのメニュー項目（未読・除外・削除・顧客情報）が表示される
    await expect(menu.getByRole("menuitem")).toHaveCount(4);
  });

  test("≤1279px: メニュー外クリックでドロップダウンが閉じる", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await setupInboxWithConversation(page);

    const menuBtn = page.locator(".inbox-header-menu-btn");
    const menu = page.locator(".inbox-header-menu");

    await menuBtn.click();
    await expect(menu).toBeVisible();

    // メッセージエリア（メニュー外）をクリック
    await page.locator(".inbox-messages").click({ position: { x: 50, y: 50 } });

    await expect(menu).not.toBeVisible();
  });

  test("≥1280px: インラインボタン群が表示され、三点ボタンは非表示になる", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setupInboxWithConversation(page);

    // インラインボタン群が表示される
    await expect(page.locator(".inbox-header-actions")).toBeVisible();

    // 三点ボタンは非表示
    await expect(page.locator(".inbox-header-menu-btn")).toBeHidden();
  });
});
