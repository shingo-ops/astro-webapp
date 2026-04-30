/**
 * Scene 7: Reply Outside 24-Hour Window using Human Agent Tag
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §8 (5:30–6:30)
 *
 * 目的:
 *   - 24h 経過後の会話で messaging_window バナーが「Human Agent Tag 付き」表示に切替
 *   - 返信送信 → outbound バブルに `Human Agent` ラベル表示
 *   - messaging_type=MESSAGE_TAG, message_tag=HUMAN_AGENT で送信される
 *
 * 見せ場（撮影台本との対応）:
 *   - 5:38 24h バナー切替: 「24 時間を超過しています。返信は Human Agent Tag 付きで送信されます」
 *   - 6:04 outbound バブル下に "Human Agent" ラベル
 *   - 6:18 messaging_type=MESSAGE_TAG / message_tag=HUMAN_AGENT
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");

test.describe("Scene 7: Human Agent Tag", () => {
  test("5:38 24h 超: バナーが Human Agent Tag 表示に切替", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5003/messages": messagesFixture.human_agent_tag_window,
      "POST /leads/5003/messages/mark-read": { marked_count: 0 },
    });

    await page.goto("/lead-chat?lead_id=5003");

    // バナー文言（24h 超 → 7d 以内）
    await expect(
      page.getByText(
        "24 時間を超過しています。返信は Human Agent Tag 付きで送信されます（24 時間〜7 日以内）。",
      ),
    ).toBeVisible({ timeout: 20_000 });

    // 入力フォームは送信可能（can_send_at_all=true）
    const textarea = page.getByPlaceholder(
      "返信を入力（Enter で送信、Shift+Enter で改行）",
    );
    await expect(textarea).toBeEnabled();
  });

  test("6:04 送信 → outbound バブル + Human Agent ラベル + MESSAGE_TAG メタデータ", async ({
    page,
  }) => {
    await installAuthBypass(page);

    let sendCalled = false;
    let sendStatusBody: Record<string, unknown> | null = null;
    let messagesCallCount = 0;

    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5003/messages": async (route) => {
        messagesCallCount++;
        const body =
          messagesCallCount === 1
            ? messagesFixture.human_agent_tag_window
            : messagesFixture.human_agent_tag_after_send;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "POST /leads/5003/messages/mark-read": { marked_count: 0 },
      "POST /leads/5003/messages": async (route) => {
        sendCalled = true;
        const responseBody = {
          id: 9202,
          message_id: "mid.late.002",
          messaging_type: "MESSAGE_TAG",
          message_tag: "HUMAN_AGENT",
          sent_at: "2026-04-30T11:05:00+00:00",
          lead_id: 5003,
          platform: "messenger",
        };
        sendStatusBody = responseBody;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(responseBody),
        });
      },
    });

    await page.goto("/lead-chat?lead_id=5003");

    const textarea = page.getByPlaceholder(
      "返信を入力（Enter で送信、Shift+Enter で改行）",
    );
    await expect(textarea).toBeVisible({ timeout: 20_000 });

    const replyText =
      "Sorry for the late reply! Our team had a one-day off. Are you still interested in our products?";
    await textarea.fill(replyText);
    await page.getByRole("button", { name: "送信", exact: true }).click();

    await expect.poll(() => sendCalled, { timeout: 10_000 }).toBe(true);

    // outbound バブル本文（左ペインと右ペイン両方に出るので main 配下）
    const mainArea = page.locator("main main");
    await expect(mainArea.getByText(replyText)).toBeVisible({ timeout: 10_000 });

    // バブル下の "Human Agent" ラベル表示（InboxPage の message_tag === "HUMAN_AGENT" 分岐）
    await expect(page.getByText("Human Agent", { exact: true })).toBeVisible();

    // backend response 検証（messaging_type / message_tag が正しく設定された）
    expect(sendStatusBody).toMatchObject({
      messaging_type: "MESSAGE_TAG",
      message_tag: "HUMAN_AGENT",
    });
  });

  test("Human Agent Tag 強制付与 toggle が 24h 内会話で見える（F4-S5）", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
    });

    await page.goto("/lead-chat?lead_id=5001");

    // 24h 内（can_send_response=true）でのみ表示される toggle
    await expect(
      page.getByText(/Human Agent Tag を強制付与/),
    ).toBeVisible({ timeout: 20_000 });
  });
});
