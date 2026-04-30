/**
 * Scene 5: Connect Instagram Business Account
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §6 (3:30–4:30)
 *
 * 目的:
 *   - /channels で接続済 Page カードに Instagram 連携情報が表示される
 *     - instagram_username (@highlifejpn_test)
 *     - instagram_business_account_id (17841...)
 *   - Active バッジ + 接続日時 + 接続者名が出ている
 *   - 切断ボタンが見える（クリックはしない）
 *
 * 見せ場（撮影台本との対応）:
 *   - 3:33 シーン 2 で接続した Page カード
 *   - 3:38 Instagram セクション拡大ハイライト → @highlifejpn_test + IG-BIZ-id
 *   - 4:06 切断ボタン視認（クリックなし）
 *
 * 注: スクリプト §6-1 の「詳細パネル」は UI 仕様に存在しないので、
 *     カードの表示要素のみで完結（撮影台本 §6-3「詳細パネルが UI 仕様にない場合は
 *     カードの表示要素のみで完結させて構わない」に準拠）。
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

test.describe("Scene 5: Connect Instagram", () => {
  test("3:38 Channel カードに IG username + IG business account ID が表示される", async ({
    page,
  }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /meta/channels": channelsFixture.with_high_life_jpn,
    });

    await page.goto("/channels");
    await expect(
      page.getByRole("heading", { name: "Channels（メッセージ連携）" }),
    ).toBeVisible({ timeout: 20_000 });

    // Page カード見出し
    await expect(
      page.getByRole("heading", { name: "HIGH LIFE JPN Test Page" }),
    ).toBeVisible();

    // Active バッジ
    await expect(page.getByText("接続中", { exact: true })).toBeVisible();

    // Instagram username（@highlifejpn_test）
    await expect(page.getByText("@highlifejpn_test")).toBeVisible();

    // Instagram business account ID（17841400000000200）
    await expect(page.getByText("17841400000000200")).toBeVisible();

    // 接続者名
    await expect(page.getByText(/接続者: E2E Test User/)).toBeVisible();

    // 4:06 切断ボタン（active page に対する）
    await expect(page.getByRole("button", { name: "切断" })).toBeVisible();
  });

  test("Page ID も card に表示される", async ({ page }) => {
    await installAuthBypass(page);
    await mockApi(page, {
      ...commonMocks(),
      "GET /meta/channels": channelsFixture.with_high_life_jpn,
    });

    await page.goto("/channels");
    await expect(
      page.getByRole("heading", { name: "HIGH LIFE JPN Test Page" }),
    ).toBeVisible({ timeout: 20_000 });

    // Page ID は mono span に出る
    await expect(page.getByText("100000000000100")).toBeVisible();
  });
});
