import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePermissions } from "./usePermissions";

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
  it("initial state: loading=true, empty permissions, error=null", () => {
    mockGet.mockResolvedValueOnce({ permissions: [] });
    const { result } = renderHook(() => usePermissions());

    expect(result.current.loading).toBe(true);
    expect(result.current.permissions.size).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("on API success: permissions are stored in a Set and loading becomes false", async () => {
    mockGet.mockResolvedValueOnce({
      permissions: ["read:customers", "write:orders"],
    });

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.permissions.has("read:customers")).toBe(true);
    expect(result.current.permissions.has("write:orders")).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("on API failure: error is set and loading becomes false", async () => {
    mockGet.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => usePermissions());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Network error");
    expect(result.current.permissions.size).toBe(0);
  });

  it("hasPermission returns true for a held permission", async () => {
    mockGet.mockResolvedValueOnce({
      permissions: ["read:customers", "write:orders"],
    });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPermission("read:customers")).toBe(true);
    expect(result.current.hasPermission("write:orders")).toBe(true);
  });

  it("hasPermission returns false for a permission not held", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["read:customers"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasPermission("admin:superadmin")).toBe(false);
  });

  it("hasAny returns true when at least one permission is held", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["write:orders"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(
      result.current.hasAny("read:customers", "write:orders"),
    ).toBe(true);
  });

  it("hasAny returns false when none of the permissions are held", async () => {
    mockGet.mockResolvedValueOnce({ permissions: ["write:orders"] });

    const { result } = renderHook(() => usePermissions());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(
      result.current.hasAny("read:customers", "admin:superadmin"),
    ).toBe(false);
  });

  it("reload triggers a second API call and updates permissions", async () => {
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

  it("calls the /me/permissions endpoint", async () => {
    mockGet.mockResolvedValueOnce({ permissions: [] });

    renderHook(() => usePermissions());
    await waitFor(() => expect(mockGet).toHaveBeenCalledOnce());

    expect(mockGet).toHaveBeenCalledWith("/me/permissions");
  });
});
