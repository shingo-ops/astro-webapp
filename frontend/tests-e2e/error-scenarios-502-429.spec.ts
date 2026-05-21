/**
 * エラーシナリオ E2E テスト: 502/429/504 の UI 表示確認
 *
 * フェーズ4 P2 推奨修正エビデンス (#20 E2E 要件)。
 *
 * カバー:
 *  1. OAuth コールバック 502 → ChannelsPage に "meta_api_error" バナー表示
 *  2. OAuth コールバック 504 → ChannelsPage に "meta_timeout" バナー表示
 *  3. DM 送信 502 → InboxPage に "Send error: ..." アラート表示
 *  4. DM 送信 429 → InboxPage に "Send error: Too Many Requests" アラート表示
 *
 * 実機 Meta OAuth / Redis / backend は不要: すべて Playwright route mock。
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

// ── fixtures ──────────────────────────────────────────────────────────────────

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");
const channelsFixture = loadFixture<{ empty: { channels: unknown[] } }>("mock-channels.json");

// ── OAuth コールバック エラーシナリオ ────────────────────────────────────────

test.describe("OAuth callback error display", () => {
  test("502 → meta_api_error バナーが表示される", async ({ page }) => {
    await installAuthBypass(page);

    await mockApi(page, {
      ...commonMocks(),
      // callback endpoint が 502 を返す（Meta API upstream failure）
      "GET /meta/connect/callback": async (route) => {
        await route.fulfill({
          status: 502,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Meta API upstream error" }),
        });
      },
      // /channels への遷移後に channels 一覧を返す
      "GET /meta/channels": channelsFixture.empty,
    });

    // Facebook OAuth がリダイレクトしてきた状態を再現
    await page.goto("/channels/oauth/callback?code=fake-code-502&state=fake-state-502");

    // OAuthCallbackPage が 502 を受け取り → /channels?status=error&reason=meta_api_error に navigate
    await page.waitForURL(/\/channels/, { timeout: 20_000 });

    // ChannelsPage の error バナー（role="alert"）に "Meta API error" 文言が出る
    const alertBanner = page.getByRole("alert");
    await expect(alertBanner).toBeVisible({ timeout: 15_000 });
    await expect(alertBanner).toContainText(
      "Couldn't connect due to a Meta API error. Please try again in a moment.",
    );
  });

  test("504 → meta_timeout バナーが表示される", async ({ page }) => {
    await installAuthBypass(page);

    await mockApi(page, {
      ...commonMocks(),
      // callback endpoint が 504 を返す（Meta API timeout）
      "GET /meta/connect/callback": async (route) => {
        await route.fulfill({
          status: 504,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Gateway Timeout" }),
        });
      },
      "GET /meta/channels": channelsFixture.empty,
    });

    await page.goto("/channels/oauth/callback?code=fake-code-504&state=fake-state-504");

    await page.waitForURL(/\/channels/, { timeout: 20_000 });

    const alertBanner = page.getByRole("alert");
    await expect(alertBanner).toBeVisible({ timeout: 15_000 });
    await expect(alertBanner).toContainText(
      "The Meta API request timed out. Please check your network connection.",
    );
  });
});

// ── DM 送信 エラーシナリオ ────────────────────────────────────────────────────

test.describe("DM send error display", () => {
  test("POST 502 → inbox-send-error アラートが表示される", async ({ page }) => {
    await installAuthBypass(page);

    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
      // 送信が 502 を返す（Meta downstream error）
      "POST /leads/5001/messages": async (route) => {
        await route.fulfill({
          status: 502,
          contentType: "application/json",
          body: JSON.stringify({ detail: "HTTP 502" }),
        });
      },
    });

    await page.goto("/lead-chat?lead_id=5001");

    const textarea = page.getByPlaceholder(/メッセージを入力/);
    await expect(textarea).toBeVisible({ timeout: 20_000 });
    await textarea.fill("test message 502");

    const sendBtn = page.getByRole("button", { name: "送信", exact: true });
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    // send error alert が表示される
    const errorAlert = page.locator(".inbox-send-error[role='alert']");
    await expect(errorAlert).toBeVisible({ timeout: 10_000 });
    await expect(errorAlert).toContainText("Send error:");
    await expect(errorAlert).toContainText("502");
  });

  test("POST 429 → inbox-send-error アラートが表示される", async ({ page }) => {
    await installAuthBypass(page);

    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
      // 送信が 429 を返す（Meta rate limit）
      "POST /leads/5001/messages": async (route) => {
        await route.fulfill({
          status: 429,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Too Many Requests" }),
        });
      },
    });

    await page.goto("/lead-chat?lead_id=5001");

    const textarea = page.getByPlaceholder(/メッセージを入力/);
    await expect(textarea).toBeVisible({ timeout: 20_000 });
    await textarea.fill("test message 429");

    const sendBtn = page.getByRole("button", { name: "送信", exact: true });
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    const errorAlert = page.locator(".inbox-send-error[role='alert']");
    await expect(errorAlert).toBeVisible({ timeout: 10_000 });
    await expect(errorAlert).toContainText("Send error:");
    await expect(errorAlert).toContainText("Too Many Requests");
  });
});
