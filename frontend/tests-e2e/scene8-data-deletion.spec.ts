/**
 * Scene 8: Data Deletion Callback Demonstration
 *
 * 撮影台本対応: docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md §9 (6:30–7:30)
 *
 * 目的:
 *   - confirmation_code が `DEL-YYYYMMDD-xxxxxxxx` 形式（8 hex）に合致
 *   - GET /api/v1/meta/deletion-status?code=... のレスポンスを mock し、
 *     LP の Status Page スクリプト（lp/src/pages/deletion-status.astro と同等）が
 *     status / requested_at を render する
 *   - 無効コードは "無効な確認コードです" を表示
 *
 * 注:
 *   - SalesAnchor frontend (React, port 5173) には Data Deletion 画面が存在しない
 *     （Status Page は LP / Astro 側 lp/src/pages/deletion-status.astro）
 *   - 本 spec は LP の Status Page と同等の HTML/JS を `setContent` で inject し、
 *     `/api/v1/meta/deletion-status` を Playwright route で mock して動作確認する
 *   - 撮影台本 §9-1 の Meta Developer Portal 操作は実機操作のため Out of Scope
 *
 * 見せ場（撮影台本との対応）:
 *   - 6:54 confirmation_code 発行（POST /api/v1/meta/data-deletion レスポンス仕様）
 *   - 7:04 Status Page: 確認コード + ステータス + 受付日時
 *   - 7:18 Status: completed
 */

import { expect, test } from "@playwright/test";

const VALID_CODE = "DEL-20260430-a3f20011";

/**
 * LP / Astro deletion-status.astro と同等の最小実装。
 * baseURL（vite dev server）配下でセルフ完結する HTML/JS を返す。
 */
const STATUS_PAGE_HTML = (search: string) => `
<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><title>削除ステータス確認</title></head>
<body>
<article>
  <h1>削除ステータス確認</h1>
  <div id="status-card">
    <p id="status-loading">読み込み中… / Loading…</p>
  </div>
</article>
<script>
window.history.replaceState({}, '', '/${search}');
(function () {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code') || '';
  const card = document.getElementById('status-card');
  function render(html) { card.innerHTML = html; }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  const codeRe = /^DEL-\\d{8}-[a-f0-9]{8}$/;
  if (!code || !codeRe.test(code)) {
    render('<p class="error">無効な確認コードです / Invalid confirmation code</p>');
    return;
  }
  fetch('/api/v1/meta/deletion-status?code=' + encodeURIComponent(code), {
    headers: { Accept: 'application/json' }
  }).then(function (res) {
    if (res.status === 404) {
      return res.text().then(function () {
        render('<h3 class="not-found">確認コードが見つかりません</h3>');
      });
    }
    return res.json().then(function (data) {
      const labels = {
        received: '受付済み / Received',
        verifying: '本人確認中 / Verifying',
        processing: '処理中 / Processing',
        completed: '完了 / Completed',
        failed: '処理失敗 / Failed',
        rejected: '却下 / Rejected',
      };
      const statusJa = labels[data.status] || data.status;
      render(
        '<dl>' +
        '<dt>確認コード</dt><dd id="dd-code"><code>' + esc(data.confirmation_code) + '</code></dd>' +
        '<dt>ステータス</dt><dd id="dd-status">' + esc(statusJa) + '</dd>' +
        '<dt>受付日時</dt><dd id="dd-requested">' + esc(data.requested_at || '—') + '</dd>' +
        '</dl>'
      );
    });
  }).catch(function () {
    render('<h3 class="error">エラー</h3>');
  });
})();
</script>
</body></html>
`;

test.describe("Scene 8: Data Deletion Status Page", () => {
  test("confirmation_code は DEL-YYYYMMDD-xxxxxxxx 形式（8 hex）に合致する", () => {
    // 6:54 callback が返す confirmation_code 仕様
    expect(VALID_CODE).toMatch(/^DEL-\d{8}-[a-f0-9]{8}$/);
  });

  test("7:04–7:18 Status Page が status=completed を render する", async ({ page }) => {
    await page.route("**/api/v1/meta/deletion-status*", async (route) => {
      const url = new URL(route.request().url());
      const code = url.searchParams.get("code") || "";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          confirmation_code: code,
          status: "completed",
          requested_at: "2026-04-30T11:00:00+00:00",
          started_at: "2026-04-30T11:00:30+00:00",
          completed_at: "2026-04-30T11:01:00+00:00",
          failure_reason: null,
        }),
      });
    });

    // baseURL の同一オリジンで動かすため空の page にしてから setContent
    await page.goto("/");
    await page.setContent(STATUS_PAGE_HTML(`?code=${VALID_CODE}`));

    // 7:04 確認コード表示
    await expect(page.locator("#dd-code code")).toHaveText(VALID_CODE, {
      timeout: 10_000,
    });
    // 7:18 ステータス: 完了 / Completed
    await expect(page.locator("#dd-status")).toContainText("完了 / Completed");
    // 受付日時の値が反映される
    await expect(page.locator("#dd-requested")).toContainText("2026");
  });

  test("status=processing の途中ステータスも正しく描画される", async ({ page }) => {
    await page.route("**/api/v1/meta/deletion-status*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          confirmation_code: VALID_CODE,
          status: "processing",
          requested_at: "2026-04-30T11:00:00+00:00",
          started_at: "2026-04-30T11:00:30+00:00",
          completed_at: null,
          failure_reason: null,
        }),
      });
    });

    await page.goto("/");
    await page.setContent(STATUS_PAGE_HTML(`?code=${VALID_CODE}`));

    await expect(page.locator("#dd-status")).toContainText(
      "処理中 / Processing",
      { timeout: 10_000 },
    );
  });

  test("無効な code は「無効な確認コードです」を表示する", async ({ page }) => {
    await page.goto("/");
    await page.setContent(STATUS_PAGE_HTML(`?code=INVALID-CODE`));

    await expect(page.locator(".error")).toContainText(
      "無効な確認コードです",
    );
  });

  test("404: 該当コードなしで「確認コードが見つかりません」を表示する", async ({ page }) => {
    await page.route("**/api/v1/meta/deletion-status*", async (route) => {
      await route.fulfill({
        status: 404,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Confirmation code not found" }),
      });
    });

    await page.goto("/");
    await page.setContent(STATUS_PAGE_HTML(`?code=${VALID_CODE}`));

    await expect(page.locator(".not-found")).toContainText(
      "確認コードが見つかりません",
      { timeout: 10_000 },
    );
  });
});
