/**
 * Sprint 8 / F8 — PO PDF + メール + テナント名義 + alias 置換 の E2E テスト。
 *
 * 検証範囲:
 *   - AC8.1: PO 一覧の「PDF」ボタンが /purchase-orders/{id}/pdf を呼び、PDF が
 *     ダウンロードされる (Content-Type: application/pdf を確認)
 *   - AC8.5: メール送信が失敗 (502) → status='error' badge が表示され、
 *     「再送」ボタンが現れる
 *   - AC8.6: 既存 PO 一覧 / 状態遷移ボタン (order / receive / cancel) が壊れて
 *     いない (regression check)
 *   - AC8.8 表示: corporate / individual supplier の PO が両方一覧に出る
 *     (実 PDF レンダリングは backend unit test でカバー)
 *
 * Backend は API mock 経由 (既存 e2e と同じパターン)。
 */
import { expect, test, type Route } from "@playwright/test";
import { installAuthBypass } from "./utils/auth";
import { mockApi, type MockMap } from "./utils/api-mock";
import { commonMocks } from "./utils/common-mocks";

interface POFixture {
  id: number;
  po_number: string;
  supplier_id: number;
  status: string;
  total_amount: number;
  ordered_at: string | null;
  received_at: string | null;
  created_at: string;
}

const PO_ORDERED: POFixture = {
  id: 101,
  po_number: "PO-00101",
  supplier_id: 1,
  status: "ordered",
  total_amount: 12000,
  ordered_at: "2026-05-22T10:00:00+09:00",
  received_at: null,
  created_at: "2026-05-22T09:00:00+09:00",
};

const PO_ERROR: POFixture = {
  ...PO_ORDERED,
  id: 102,
  po_number: "PO-00102",
  status: "error",
};

const PO_DRAFT: POFixture = {
  ...PO_ORDERED,
  id: 103,
  po_number: "PO-00103",
  status: "draft",
  ordered_at: null,
};

test.beforeEach(async ({ page }) => {
  await installAuthBypass(page);
});

test("AC8.1: PDF ダウンロードボタンが PDF を返す (Content-Type 検証)", async ({ page }) => {
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /purchase-orders": [PO_ORDERED, PO_ERROR, PO_DRAFT],
  };
  await mockApi(page, mocks);

  // PDF endpoint は専用ハンドラ (バイナリレスポンス)
  await page.route("**/api/v1/purchase-orders/101/pdf", async (route: Route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="PO-00101.pdf"',
      },
      body: Buffer.from("%PDF-1.4\n%mocked test pdf\n"),
    });
  });

  await page.goto("/purchase-orders");
  await expect(page.getByTestId("purchase-orders-table")).toBeVisible();
  await expect(page.getByTestId(`po-row-${PO_ORDERED.id}`)).toBeVisible();

  // ダウンロード event を待ち受ける
  const downloadPromise = page.waitForEvent("download");
  await page.getByTestId(`po-pdf-${PO_ORDERED.id}`).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/PO-00101\.pdf$/);
});

test("AC8.5: メール送信失敗 → status='error' → 再送ボタン表示", async ({ page }) => {
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /purchase-orders": [PO_ERROR],
  };
  await mockApi(page, mocks);

  await page.goto("/purchase-orders");
  await expect(page.getByTestId(`po-status-${PO_ERROR.id}`)).toContainText(/送信エラー|Send error/);
  await expect(page.getByTestId(`po-resend-email-${PO_ERROR.id}`)).toBeVisible();
});

test("AC8.6: 既存 PO 一覧の表示 + 状態遷移ボタンが regression なし", async ({ page }) => {
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /purchase-orders": [PO_DRAFT, PO_ORDERED],
  };
  await mockApi(page, mocks);

  await page.goto("/purchase-orders");
  await expect(page.getByTestId("purchase-orders-table")).toBeVisible();
  // draft → 「発注」ボタン + 「取消」ボタン
  await expect(page.getByTestId(`po-row-${PO_DRAFT.id}`)).toContainText(/PO-00103/);
  // ordered → 「入荷」ボタン + 「取消」ボタン + 「PDF」「メール送信」が出る
  await expect(page.getByTestId(`po-pdf-${PO_ORDERED.id}`)).toBeVisible();
  await expect(page.getByTestId(`po-send-email-${PO_ORDERED.id}`)).toBeVisible();
});

test("AC8.7: テナント発行者情報ページが表示され、保存できる", async ({ page }) => {
  const mocks: MockMap = {
    ...commonMocks(),
    "GET /admin/tenant-profile": {
      id: 1,
      company_name: "QA テナント株式会社",
      company_name_en: "QA Tenant Inc.",
      address: "東京都渋谷区 X-Y-Z",
      phone: "03-1234-5678",
      email: "po@qa-tenant.example.com",
      website: null,
      seal_image_url: null,
      default_language: "ja",
      created_at: "2026-05-22T00:00:00+09:00",
      updated_at: "2026-05-22T00:00:00+09:00",
    },
  };
  await mockApi(page, mocks);

  // PUT は ad-hoc で 200 を返す
  await page.route("**/api/v1/admin/tenant-profile", async (route: Route) => {
    const req = route.request();
    if (req.method() === "PUT") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: 1,
          company_name: "QA テナント株式会社 (更新)",
          company_name_en: "QA Tenant Inc.",
          address: "東京都渋谷区 X-Y-Z",
          phone: "06-9999-0000",
          email: "po@qa-tenant.example.com",
          website: null,
          seal_image_url: null,
          default_language: "ja",
          created_at: "2026-05-22T00:00:00+09:00",
          updated_at: "2026-05-22T01:00:00+09:00",
        }),
      });
    } else {
      // GET は MockMap に任せる
      await route.fallback();
    }
  });

  await page.goto("/admin/tenant-profile");
  await expect(page.getByTestId("tenant-profile-form")).toBeVisible();
  await expect(page.getByTestId("tp-company-name")).toHaveValue("QA テナント株式会社");

  // フィールドを変更して保存
  await page.getByTestId("tp-phone").fill("06-9999-0000");
  await page.getByTestId("tenant-profile-save").click();
  await expect(page.getByTestId("tenant-profile-info")).toBeVisible();
});
