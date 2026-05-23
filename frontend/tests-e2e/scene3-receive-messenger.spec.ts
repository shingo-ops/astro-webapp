/**
 * Scene 3: Incoming Messenger Message Arrives in Inbox
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §4 (1:30–2:30)
 *
 * 目的:
 *   - /lead-chat (InboxPage) で会話リスト + 未読バッジが描画される
 *   - 会話を選択 → メッセージ履歴に inbound バブルで表示
 *   - mark-read API が呼ばれて既読状態になる
 *
 * 見せ場（撮影台本との対応）:
 *   - 1:34 Inbox 画面（左ペイン会話リスト + 右ペイン）
 *   - 1:53 左ペインに新会話 + 未読バッジ "1"
 *   - 2:06 会話クリック → inbound バブル "Hello, I'd like to ask about your products."
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

const conversationsFixture = loadFixture("mock-conversations.json");
const messagesFixture = loadFixture<Record<string, unknown>>("mock-messages.json");

test.describe("Scene 3: Incoming Messenger", () => {
  test("1:34–2:16 Inbox に Messenger 受信が表示され既読化される", async ({ page }) => {
    await installAuthBypass(page);

    let markReadCalled = false;
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
      "GET /leads/5001/messages": messagesFixture.messenger_within_24h,
      "POST /leads/5001/messages/mark-read": async (route) => {
        markReadCalled = true;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ marked_count: 1 }),
        });
      },
    });

    await page.goto("/lead-chat");

    // 1:34 受信トレイ見出し（左ペイン）
    // ADR-044: i18n 化により t("inbox.title") = "受信箱"
    await expect(
      page.getByRole("heading", { name: "受信箱" }),
    ).toBeVisible({ timeout: 20_000 });

    // 1:53 会話リストに Taro Sender が出ている + 未読バッジ "1"
    const taroBtn = page.locator("button.conversation-item", {
      hasText: "Taro Sender",
    });
    await expect(taroBtn).toBeVisible();

    // 未読バッジ（数字 1）
    const unreadBadge = taroBtn.locator(".badge", { hasText: "1" });
    await expect(unreadBadge).toBeVisible();

    // 2:06 会話クリック → 右ペインに inbound バブル
    await taroBtn.click();

    // 右ペイン: lead リンク（ADR-044: i18n 化により t("inbox.lead") = "リード"）
    // サイドバーにも "リード" NavLink が存在するため main main に絞る（ADR-059）
    await expect(page.locator("main main").getByRole("link", { name: "リード", exact: true })).toBeVisible({
      timeout: 10_000,
    });

    // inbound メッセージ本文（左ペインの会話アイテムと右ペインの両方に同じ文字列が
    // 出るので、InboxPage の内側 `<main>`（Layout の外側 main の子）に絞る）
    // Layout は <main class="main-content-top">、Inbox は <main> の入れ子。
    const inboxMain = page.locator("main main");
    await expect(
      inboxMain.getByText("Hello, I'd like to ask about your products."),
    ).toBeVisible();

    // ADR-044: dac01e3 で MessagingWindowBanner UI を削除（HUMAN_AGENT auto-apply 化）。
    // 24h バナー検証は撤去。代わりに右ペインに返信用 textarea が表示されることを確認。
    await expect(
      page.getByPlaceholder(/メッセージを入力/),
    ).toBeVisible();

    // 2:22 mark-read API が呼ばれる
    await expect.poll(() => markReadCalled, { timeout: 10_000 }).toBe(true);
  });

  test("サブフィルターピル（未読 / フォローアップ）が機能する", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
    });

    await page.goto("/lead-chat");
    // ADR-044: i18n 化により t("inbox.title") = "受信箱"
    await expect(
      page.getByRole("heading", { name: "受信箱" }),
    ).toBeVisible({ timeout: 20_000 });

    // サブフィルターバー（Inbox 再設計: タブバー削除 → サブフィルターピル追加）
    const subFilterBar = page.locator(".inbox-sub-filter-bar");
    const unreadBtn = subFilterBar.getByRole("button", { name: "未読" });
    const followUpBtn = subFilterBar.getByRole("button", { name: "フォローアップ" });
    await expect(unreadBtn).toBeVisible();
    await expect(followUpBtn).toBeVisible();

    // クリックで active class が付く
    await unreadBtn.click();
    await expect(unreadBtn).toHaveClass(/active/);

    // もう一度クリックで解除される
    await unreadBtn.click();
    await expect(unreadBtn).not.toHaveClass(/active/);
  });
});
