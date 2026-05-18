/**
 * ADR-038 / QA Smoke Suite — tenant_006 (tenant-review) の 3 ユーザー認証情報
 *
 * Secrets は CI から env で注入する (リポジトリには平文を置かない)。
 * 値が無い場合は明示的に Error を投げて smoke を即 fail させる。
 *
 * 必須環境変数 (CI secrets):
 *   QA_ADMIN_EMAIL / QA_ADMIN_PASSWORD
 *   QA_STAFF_EMAIL / QA_STAFF_PASSWORD
 *   QA_VIEWER_EMAIL / QA_VIEWER_PASSWORD
 *
 * 任意環境変数:
 *   QA_TENANT_CODE   default: 'tenant-review'
 *   QA_TENANT_ID     default: 6
 *
 * Firebase で管理されている 3 ユーザーは、scripts/qa/reset-tenant.sh が
 * public.users / tenant_006.staff にも同じ email で seed する。
 */

export interface QaCredential {
  role: "admin" | "staff" | "viewer";
  email: string;
  password: string;
}

function req(name: string): string {
  const v = process.env[name];
  if (!v || v.length === 0) {
    throw new Error(
      `QA smoke abort: required env var '${name}' is missing. CI secrets を確認してください`,
    );
  }
  return v;
}

export const QA_TENANT_CODE = process.env.QA_TENANT_CODE || "tenant-review";
export const QA_TENANT_ID = Number(process.env.QA_TENANT_ID || "6");

export const QA_USERS: Record<"admin" | "staff" | "viewer", QaCredential> = {
  admin: {
    role: "admin",
    email: req("QA_ADMIN_EMAIL"),
    password: req("QA_ADMIN_PASSWORD"),
  },
  staff: {
    role: "staff",
    email: req("QA_STAFF_EMAIL"),
    password: req("QA_STAFF_PASSWORD"),
  },
  viewer: {
    role: "viewer",
    email: req("QA_VIEWER_EMAIL"),
    password: req("QA_VIEWER_PASSWORD"),
  },
};
