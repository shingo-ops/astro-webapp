/**
 * 現在のユーザーの有効権限をAPIから取得し、キャッシュするフック。
 * UIのメニュー・ボタン表示制御に使用する。
 *
 * 変更履歴:
 *   2026-04-16: 初版作成（Phase 1）
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";

interface PermissionsResponse {
  permissions: string[];
}

export function usePermissions() {
  const [permissions, setPermissions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get<PermissionsResponse>("/me/permissions");
      setPermissions(new Set(data.permissions));
    } catch (e) {
      // eslint-disable-next-line local/no-japanese-literal -- TODO: i18n対応（ADR-027 既知負債）
      setError(e instanceof Error ? e.message : "権限情報の取得に失敗しました");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const hasPermission = useCallback(
    (key: string) => permissions.has(key),
    [permissions],
  );

  const hasAny = useCallback(
    (...keys: string[]) => keys.some((k) => permissions.has(k)),
    [permissions],
  );

  return useMemo(
    () => ({ permissions, loading, error, hasPermission, hasAny, reload: load }),
    [permissions, loading, error, hasPermission, hasAny, load],
  );
}
