/**
 * Scene 2: Connect Facebook Page via OAuth
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §3 (0:30–1:30)
 *
 * 目的:
 *   - /channels で接続済 Page 0 件の状態（empty CTA）が描画される
 *   - 「Facebook ページを接続」ボタン押下で POST /meta/connect/start が呼ばれ、
 *     auth_url にリダイレクトされようとする（実機 OAuth は通さず、URL を捕捉）
 *   - OAuthCallbackPage が GET /meta/connect/callback を呼び、/channels?status=connected に
 *     遷移して Page カードが Active バッジ付きで描画される（callback success path）
 *
 * 見せ場（撮影台本との対応）:
 *   - 0:30 Channels 画面遷移
 *   - 0:36 「Facebook ページを接続」ボタン → クリック
 *   - 1:06 callback redirect 後の Page カード
 *   - 1:18 「Active」バッジ + page_token_expires_at（残り日数）
 *
 * Out of Scope（実機 Meta OAuth 通し）:
 *   - facebook.com/v19.0/dialog/oauth の DOM は対象外（Sprint 7 撮影で対応）
 */

import { expect, test } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";
import { loadFixture } from "./utils/fixtures";

interface ChannelsFixture {
  empty: { channels: unknown[] };
  with_high_life_jpn: { channels: unknown[] };
}
const channelsFixture = loadFixture<ChannelsFixture>("mock-channels.json");

test.describe("Scene 2: Connect Facebook Page via OAuth", () => {
  test("0:30 接続前: 空 state で Onboarding CTA が見える", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /meta/channels": channelsFixture.empty,
    });

    await page.goto("/channels");

    // ページ見出し
    await expect(
      page.getByRole("heading", { name: "チャンネル (Meta連携)" }),
    ).toBeVisible({ timeout: 20_000 });

    // 0 件 onboarding（空 state） — ADR-044: i18n 化により t("channels.noChannels")
    await expect(
      page.getByRole("heading", {
        name: "接続済みチャンネルがありません",
      }),
    ).toBeVisible();

    // 接続ボタン: t("channels.connect") = "Facebookページを接続"（半角スペースなし）
    const connectButtons = page.getByRole("button", {
      name: "Facebookページを接続",
    });
    await expect(connectButtons.first()).toBeVisible();
  });

  test("0:36 「接続」クリック → POST /meta/connect/start → auth_url 取得", async ({
    page,
  }) => {
    await installAuthBypass(page);

    // start endpoint に到達したことを記録
    let startCalled = false;
    let startBody: string | null = null;

    await mockApi(page, {
      ...commonMocks(),
      "GET /meta/channels": channelsFixture.empty,
      "POST /meta/connect/start": async (route) => {
        startCalled = true;
        startBody = route.request().postData();
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            auth_url:
              "https://www.facebook.com/v19.0/dialog/oauth?client_id=e2e&redirect_uri=https%3A%2F%2Fapp.salesanchor.jp%2Fchannels%2Foauth%2Fcallback&scope=pages_show_list%2Cpages_manage_metadata%2Cpages_messaging%2Cpages_read_engagement%2Cinstagram_basic%2Cinstagram_manage_messages&state=e2e-state",
            state: "e2e-state",
            expires_at: "2026-04-30T11:30:00+00:00",
          }),
        });
      },
    });

    // window.location.href への遷移は実 facebook.com に飛ばさない（page.route で navigation を block）
    await page.route("https://www.facebook.com/**", async (route) => {
      // facebook.com への遷移は中断 → blank で返す
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: "<html><body>[E2E] facebook.com mock — OAuth dialog not rendered</body></html>",
      });
    });

    await page.goto("/channels");
    await expect(
      page.getByRole("heading", { name: "チャンネル (Meta連携)" }),
    ).toBeVisible({ timeout: 20_000 });

    // 接続ボタンを押す（ヘッダ側を click） — i18n 化以降は "Facebookページを接続"
    await page.getByRole("button", { name: "Facebookページを接続" }).first().click();

    // POST /meta/connect/start が叩かれるまで待つ
    await expect.poll(() => startCalled, { timeout: 10_000 }).toBe(true);
    // body は空 object で送信される（仕様: api.post('/meta/connect/start', {})）
    expect(startBody).toMatch(/^\{/);

    // 遷移先が facebook.com になることを確認（mock により blank が返る）
    await page.waitForURL(/facebook\.com/, { timeout: 10_000 });
  });

  test("1:06 callback success → /channels に Active Page カードが出る", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      // OAuthCallbackPage の GET /meta/connect/callback
      "GET /meta/connect/callback": {
        connected_pages: [
          {
            page_id: "100000000000100",
            page_name: "HIGH LIFE JPN Test Page",
            instagram_business_account_id: "17841400000000200",
            instagram_username: "highlifejpn_test",
          },
        ],
        failed_pages: [],
      },
      // /channels への navigate 後の一覧取得
      "GET /meta/channels": channelsFixture.with_high_life_jpn,
    });

    // OAuth プロバイダがリダイレクトしてきた状態を再現
    await page.goto(
      "/channels/oauth/callback?code=fake-oauth-code&state=fake-state",
    );

    // 1:06–1:10 callback 処理 → /channels?status=connected に navigate
    await page.waitForURL(/\/channels(\?.*)?$/, { timeout: 20_000 });

    // success バナー（status=connected の page_name 付き）
    // ADR-044: 接続成功メッセージは ChannelsPage.tsx:117 で英語固定文字列
    await expect(
      page.getByText(/"HIGH LIFE JPN Test Page" connected successfully/),
    ).toBeVisible({ timeout: 10_000 });

    // 1:10–1:18 Page カード描画
    await expect(
      page.getByRole("heading", { name: "HIGH LIFE JPN Test Page" }),
    ).toBeVisible();

    // Active バッジ — ADR-044: i18n 化により t("channels.status_active") = "有効"
    await expect(page.getByText("有効", { exact: true })).toBeVisible();

    // Instagram 連携の表示（@highlifejpn_test）
    await expect(page.getByText("@highlifejpn_test")).toBeVisible();

    // page_token_expires_at の残り日数表示 — t("channels.daysLeft") = "あとN日"
    await expect(page.getByText(/あと\d+日/)).toBeVisible();
  });
});
