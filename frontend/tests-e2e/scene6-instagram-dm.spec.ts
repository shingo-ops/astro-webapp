/**
 * Scene 6: Instagram DM Received and Replied
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §7 (4:30–5:30)
 *
 * 目的:
 *   - /lead-chat で Instagram プラットフォームの会話が表示される
 *   - Instagram 会話を選択 → inbound メッセージ表示
 *   - 返信送信 → outbound バブル表示（messaging_type=RESPONSE）
 *
 * 見せ場（撮影台本との対応）:
 *   - 4:52 inbound メッセージ "Hi, do you ship internationally?"
 *   - 5:14 送信ボタン → outbound バブル + RESPONSE
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");

test.describe("Scene 6: Instagram DM", () => {
  test("4:30–4:52 Instagram 会話が Inbox に表示される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5002/messages": messagesFixture.instagram_within_24h,
      "POST /leads/5002/messages/mark-read": { marked_count: 1 },
    });

    await page.goto("/lead-chat");
    // ADR-044: i18n 化により t("inbox.title") = "受信箱"
    await expect(
      page.getByRole("heading", { name: "受信箱" }),
    ).toBeVisible({ timeout: 20_000 });

    // 4:44 Instagram 会話アイテム
    const hanakoBtn = page.locator("button.conversation-item", {
      hasText: "Hanako Insta",
    });
    await expect(hanakoBtn).toBeVisible();

    // 4:52 会話クリック → inbound メッセージ
    await hanakoBtn.click();
    // 左ペイン会話 + 右ペイン本文の両方に出るため、`<main>` 配下に絞る
    const mainArea = page.locator("main main");
    await expect(
      mainArea.getByText("Hi, do you ship internationally?"),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("5:14–5:20 Instagram 会話に返信送信できる（RESPONSE）", async ({ page }) => {
    await installAuthBypass(page);

    let sendCalled = false;
    let messagesCallCount = 0;

    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5002/messages": async (route) => {
        messagesCallCount++;
        const body =
          messagesCallCount === 1
            ? messagesFixture.instagram_within_24h
            : messagesFixture.instagram_after_send;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "POST /leads/5002/messages/mark-read": { marked_count: 1 },
      "POST /leads/5002/messages": async (route) => {
        sendCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: 9102,
            message_id: "mid.instagram.002",
            messaging_type: "RESPONSE",
            message_tag: null,
            sent_at: "2026-04-30T11:02:00+00:00",
            lead_id: 5002,
            platform: "instagram",
          }),
        });
      },
    });

    await page.goto("/lead-chat?lead_id=5002");

    // ADR-044: i18n 化により placeholder は t("inbox.messagePlaceholder")
    const textarea = page.getByPlaceholder(/メッセージを入力/);
    await expect(textarea).toBeVisible({ timeout: 20_000 });

    const replyText =
      "Yes! We ship to over 30 countries. Please share your country and we'll provide shipping options.";
    await textarea.fill(replyText);

    await page.getByRole("button", { name: "送信", exact: true }).click();

    await expect.poll(() => sendCalled, { timeout: 10_000 }).toBe(true);

    // outbound バブル表示（左ペインの last_message_text と被る可能性があるため main 配下）
    const mainArea = page.locator("main main");
    await expect(
      mainArea.getByText(
        "Yes! We ship to over 30 countries. Please share your country and we'll provide shipping options.",
      ),
    ).toBeVisible({ timeout: 10_000 });
  });
});
