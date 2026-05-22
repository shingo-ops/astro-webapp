/**
 * Meta OAuth コールバック処理ページ（Phase 1-D Sprint 3）。
 *
 * Facebook OAuth ダイアログから redirect_uri に飛ばされたあと、ここで:
 *  1. URL クエリから code / state を取り出す
 *  2. backend GET /api/v1/meta/connect/callback?code=...&state=... を呼び出す
 *  3. 結果に応じて /channels?status=connected|partial|error&... に navigate する
 *
 * spec §3-2 step 4–5 のフローに対応。
 *
 * 変更履歴:
 *   2026-04-30: Phase 1-D Sprint 3 初版
 */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../lib/api";

interface ConnectedPage {
  page_id: string;
  page_name: string;
  instagram_business_account_id: string | null;
  instagram_username: string | null;
}

interface FailedPage {
  page_id: string | null;
  reason: string;
}

interface CallbackResponse {
  connected_pages: ConnectedPage[];
  failed_pages: FailedPage[];
}

// Meta / backend 側のエラー文言を `?reason=...` 用の短いコードに正規化する。
// detail がそのまま日本語なら "internal_error" に丸めて UI 側で汎用文言を出す。
function normalizeReason(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.responseDetail as { reason?: string } | string | undefined);
    if (typeof detail === "object" && detail && typeof detail.reason === "string") {
      return detail.reason;
    }
    if (err.status === 400) {
      // backend は state 不一致 / Page なし / code 不正で 400 を返す
      const msg = err.message || "";
      if (msg.includes("state")) return "state_mismatch";
      if (msg.includes("Page") || msg.includes("page")) return "no_pages";
      return "state_mismatch";
    }
    if (err.status === 502) return "meta_api_error";
    if (err.status === 504) return "meta_timeout";
    if (err.status === 403) return "permission_denied";
  }
  return "internal_error";
}

export default function OAuthCallbackPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  // useEffect が React Strict Mode で 2 回呼ばれても backend を 1 回しか叩かない
  const inFlight = useRef(false);

  useEffect(() => {
    if (inFlight.current) return;
    inFlight.current = true;

    const url = new URL(window.location.href);
    const code = url.searchParams.get("code");
    const state = url.searchParams.get("state");
    const oauthError = url.searchParams.get("error");
    const errorReason = url.searchParams.get("error_reason"); // user_denied など

    // ユーザーがダイアログでキャンセルした場合
    if (oauthError) {
      const reason = errorReason === "user_denied" ? "user_denied" : "internal_error";
      navigate(`/channels?status=error&reason=${encodeURIComponent(reason)}`, { replace: true });
      return;
    }

    if (!code || !state) {
      navigate("/channels?status=error&reason=state_mismatch", { replace: true });
      return;
    }

    (async () => {
      try {
        const data = await api.get<CallbackResponse>(
          `/meta/connect/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`
        );
        const connected = data.connected_pages || [];
        const failed = data.failed_pages || [];

        if (connected.length === 0 && failed.length === 0) {
          navigate("/channels?status=error&reason=no_pages", { replace: true });
          return;
        }

        if (failed.length > 0 && connected.length > 0) {
          // 部分成功（Sprint 2 evaluator I4 対応）
          const failedNames = failed.map((p) => p.page_id || "(unknown)").join(",");
          navigate(
            `/channels?status=partial&succeeded=${connected.length}&failed=${failed.length}&failed_pages=${encodeURIComponent(failedNames)}`,
            { replace: true }
          );
          return;
        }

        if (failed.length > 0 && connected.length === 0) {
          // 全 Page が失敗
          navigate("/channels?status=error&reason=meta_api_error", { replace: true });
          return;
        }

        // 全成功
        const firstName = connected[0]?.page_name || "";
        navigate(
          `/channels?status=connected&page_name=${encodeURIComponent(firstName)}&count=${connected.length}`,
          { replace: true }
        );
      } catch (e) {
        const reason = normalizeReason(e);
        // 表示用に簡易メッセージも持つ（fallback でこの画面が見える場合のため）
        setError(e instanceof Error ? e.message : t("oauth.error"));
        navigate(`/channels?status=error&reason=${encodeURIComponent(reason)}`, { replace: true });
      }
    })();
  }, [navigate]);

  return (
    <div className="page" style={{ padding: "var(--space-8)" }}>
      <h2>{t("oauth.processing")}</h2>
      <p>{t("oauth.processingDesc")}</p>
      {error && (
        <div className="error" style={{ marginTop: "var(--space-4)" }}>{error}</div>
      )}
    </div>
  );
}
