/**
 * 現在のユーザーが is_super_admin かどうかを判定するフック。
 *
 * spec.md v1.1 F2 (Sprint 2):
 *   /api/v1/me/permissions レスポンスに is_super_admin を含めて返す。
 *   そのレスポンスを再利用して /super-admin/masters への導線判定に使用。
 *
 * 変更履歴:
 *   2026-05-21: 初版（Sprint 2）
 */
import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface MePermissionsResponse {
  permissions: string[];
  is_super_admin: boolean;
}

export function useSuperAdmin() {
  const [isSuperAdmin, setIsSuperAdmin] = useState<boolean>(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get<MePermissionsResponse>("/me/permissions");
        if (!cancelled) {
          setIsSuperAdmin(Boolean(data.is_super_admin));
        }
      } catch {
        if (!cancelled) setIsSuperAdmin(false);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { isSuperAdmin, loading };
}
