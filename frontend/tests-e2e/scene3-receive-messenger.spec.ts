/**
 * Scene 3: Incoming Messenger Message Arrives in Inbox
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §4 (1:30–2:30)
 *
 * 目的:
 *   - /lead-chat (InboxPage) で会話リスト + 未読バッジが描画される
 *   - 会話を選択 → メッセージ履歴に inbound バブルで表示
 *   - platform バッジ「Messenger」 + 24h バナーが表示される
 *   - mark-read API が呼ばれて既読状態になる
 *
 * 見せ場（撮影台本との対応）:
 *   - 1:34 Inbox 画面（左ペイン会話リスト + 右ペイン）
 *   - 1:53 左ペインに新会話 + 未読バッジ "1"
 *   - 2:06 会話クリック → inbound バブル "Hello, I'd like to ask about your products."
 *   - 2:12 platform バッジ「Messenger」
 *   - 2:16 24h バナー
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
    await expect(
      page.getByRole("heading", { name: "受信トレイ" }),
    ).toBeVisible({ timeout: 20_000 });

    // 1:53 会話リストに Taro Sender が出ている + 未読バッジ "1"
    const taroBtn = page.locator("button.conversation-item", {
      hasText: "Taro Sender",
    });
    await expect(taroBtn).toBeVisible();

    // 未読バッジ（数字 1）
    const unreadBadge = taroBtn.locator(".badge", { hasText: "1" });
    await expect(unreadBadge).toBeVisible();

    // platform バッジ「Messenger」が会話アイテムに含まれる
    await expect(taroBtn.locator(".badge", { hasText: "Messenger" })).toBeVisible();

    // 2:06 会話クリック → 右ペインに inbound バブル
    await taroBtn.click();

    // 右ペイン: lead 詳細リンク
    await expect(page.getByRole("link", { name: "リード詳細" })).toBeVisible({
      timeout: 10_000,
    });

    // inbound メッセージ本文（左ペインの会話アイテムと右ペインの両方に同じ文字列が
    // 出るので、InboxPage の内側 `<main>`（Layout の外側 main の子）に絞る）
    // Layout は <main class="main-content-top">、Inbox は <main> の入れ子。
    const inboxMain = page.locator("main main");
    await expect(
      inboxMain.getByText("Hello, I'd like to ask about your products."),
    ).toBeVisible();

    // 2:12 右ペイン上の platform バッジ Messenger
    // InboxPage の内側 <main> 内の <header> を取る
    const headerArea = page.locator("main main header");
    await expect(headerArea.getByText("Messenger")).toBeVisible();

    // 2:16 24h バナー（緑「通常返信ウィンドウ内」）
    await expect(
      page.getByText("通常返信ウィンドウ内（24 時間以内）。返信は RESPONSE タイプで送信されます。"),
    ).toBeVisible();

    // 2:22 mark-read API が呼ばれる
    await expect.poll(() => markReadCalled, { timeout: 10_000 }).toBe(true);
  });

  test("platform フィルタを Messenger に切替できる", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /conversations": conversationsFixture,
    });

    await page.goto("/lead-chat");
    await expect(
      page.getByRole("heading", { name: "受信トレイ" }),
    ).toBeVisible({ timeout: 20_000 });

    // フィルタボタン群
    await expect(page.getByRole("button", { name: "すべて" })).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Messenger", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Instagram", exact: true }),
    ).toBeVisible();

    // クリックでフィルタが効く（active class が btn-primary になる）
    await page.getByRole("button", { name: "Messenger", exact: true }).click();
    const messengerBtn = page.getByRole("button", { name: "Messenger", exact: true });
    await expect(messengerBtn).toHaveClass(/btn-primary/);
  });
});
