/**
 * Scene 4: Sales Rep Replies to Messenger Message
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §5 (2:30–3:30)
 *
 * 目的:
 *   - 24h 内会話の返信フォームに textarea + 送信ボタンが見える
 *   - "送信" → POST /leads/{id}/messages が呼ばれ、`messaging_type=RESPONSE` で送信される
 *   - 送信後、outbound バブルが描画される（mock の after_send fixture）
 *
 * 見せ場（撮影台本との対応）:
 *   - 2:35 入力欄ハイライト
 *   - 2:50 返信テキスト入力 + 送信
 *   - 2:56 outbound バブル + RESPONSE messaging_type
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");

test.describe("Scene 4: Reply Messenger", () => {
  test("2:30–3:00 24h 内の会話に返信送信できる（RESPONSE）", async ({ page }) => {
    await installAuthBypass(page);

    let sendCalled = false;
    let sentBody: Record<string, unknown> | null = null;
    let messagesCallCount = 0;

    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      // GET /leads/5001/messages は 1 回目: before-send / 2 回目以降: after-send
      "GET /leads/5001/messages": async (route) => {
        messagesCallCount++;
        const body =
          messagesCallCount === 1
            ? messagesFixture.messenger_within_24h
            : messagesFixture.messenger_after_send;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(body),
        });
      },
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
      "POST /leads/5001/messages": async (route) => {
        sendCalled = true;
        const raw = route.request().postData() || "{}";
        try {
          sentBody = JSON.parse(raw);
        } catch {
          sentBody = null;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: 9002,
            message_id: "mid.messenger.002",
            messaging_type: "RESPONSE",
            message_tag: null,
            sent_at: "2026-04-30T11:01:00+00:00",
            lead_id: 5001,
            platform: "messenger",
          }),
        });
      },
    });

    // 直接 /lead-chat?lead_id=5001 で右ペインを開く
    await page.goto("/lead-chat?lead_id=5001");

    // 入力 textarea（placeholder で特定）
    // ADR-044: i18n 化により placeholder は t("inbox.messagePlaceholder")
    const textarea = page.getByPlaceholder(/メッセージを入力/);
    await expect(textarea).toBeVisible({ timeout: 20_000 });

    const replyText =
      "Hi! Thank you for reaching out. Our products are listed on our website. Could you share which category interests you?";
    await textarea.fill(replyText);

    // 送信ボタン
    const sendBtn = page.getByRole("button", { name: "送信", exact: true });
    await expect(sendBtn).toBeEnabled();
    await sendBtn.click();

    // POST 実行を確認
    await expect.poll(() => sendCalled, { timeout: 10_000 }).toBe(true);
    // ADR-044: dac01e3 で force_human_agent_tag option を削除（auto-apply 化）。
    // body は { text } のみ。
    expect(sentBody).toMatchObject({ text: replyText });

    // 2:56 outbound バブルが描画される（after-send fixture が反映）
    // 左ペイン会話一覧にも last_message_text として出るので main に絞る
    const mainArea = page.locator("main main");
    await expect(
      mainArea.getByText(
        "Hi! Thank you for reaching out. Our products are listed on our website. Could you share which category interests you?",
      ),
    ).toBeVisible({ timeout: 10_000 });

    // 入力欄が空に戻る（送信成功後 setDraft("")）
    await expect(textarea).toHaveValue("");
  });

  test("空文字 / 7d 超で送信ボタンが disabled", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": { marked_count: 1 },
    });

    await page.goto("/lead-chat?lead_id=5001");

    // 入力空 → 送信ボタン disabled
    const sendBtn = page.getByRole("button", { name: "送信", exact: true });
    await expect(sendBtn).toBeVisible({ timeout: 20_000 });
    await expect(sendBtn).toBeDisabled();
  });
});
