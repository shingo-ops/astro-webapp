import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePermissions } from "./usePermissions";

// api モジュールをモック
vi.mock("../lib/api", () => ({
  api: {
    get: vi.fn(),
  },
}));

import { api } from "../lib/api";
const mockGet = vi.mocked(api.get);

afterEach(() => {
  vi.clearAllMocks();
});

describe("usePermissions", () => {
  it("初期状態: loading=true、permissions は空、error は null", () => {
    mockGet.mockResolvedValueOnce({ permissions: [] });
    const { result } = renderHook(() => usePermissions());

    expect(result.current.loading).toBe(true);
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("API 成功時: permissions が Set に格納され loading=false になる", async () => {
    mockGet.mockResolvedValueOnce({
      permissions: ["read:customers", "write:orders"],
    });

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.permissions.has("read:customers")).toBe(true);
    expect(result.current.permissions.has("write:orders")).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("API 失敗時: error が設定され loading=false になる", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Network error");
    expect(result.current.permissions.size).toBe(0);
  });

  it("hasPermission: 持っている権限は true を返す", async () => {
    mockGet.mockResolvedValueOnce({
      permissions: ["read:customers", "write:orders"],
    });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPermission("read:customers")).toBe(true);
    expect(result.current.hasPermission("write:orders")).toBe(true);
  });

  it("hasPermission: 持っていない権限は false を返す", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["read:customers"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPermission("admin:superadmin")).toBe(false);
  });

  it("hasAny: 少なくとも1つ持っていれば true を返す", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["write:orders"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(
      result.current.hasAny("read:customers", "write:orders"),
    ).toBe(true);
  });

  it("hasAny: 1つも持っていなければ false を返す", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["write:orders"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(
      result.current.hasAny("read:customers", "admin:superadmin"),
    ).toBe(false);
  });

  it("reload: 再度 API を呼び出し permissions を更新する", async () => {
    mockGet
      .mockResolvedValueOnce({ permissions: ["read:customers"] })
      .mockResolvedValueOnce({ permissions: ["read:customers", "write:orders"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.permissions.has("write:orders")).toBe(false);

    result.current.reload();
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.permissions.has("write:orders")).toBe(true);
  });

  it("/me/permissions エンドポイントを呼び出す", async () => {
    mockGet.mockResolvedValueOnce({ permissions: [] });

    renderHook(() => usePermissions());
    await waitFor(() => expect(mockGet).toHaveBeenCalledOnce());

    expect(mockGet).toHaveBeenCalledWith("/me/permissions");
  });
});
