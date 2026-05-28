import { describe, expect, it } from "vitest";
import { inferPlatform, platformLabel } from "./messages";

describe("inferPlatform", () => {
  it("prioritises lead.platform over conversation.platform", () => {
    const result = inferPlatform(
      { platform: "messenger" },
      { platform: "instagram" },
    );
    expect(result).toBe("messenger");
  });

  it("falls back to conversation.platform when lead.platform is null", () => {
    const result = inferPlatform(
      { platform: null },
      { platform: "instagram" },
    );
    expect(result).toBe("instagram");
  });

  it("falls back to conversation.platform when lead is null", () => {
    const result = inferPlatform(null, { platform: "messenger" });
    expect(result).toBe("messenger");
  });

  it("falls back to conversation.platform when lead is undefined", () => {
    const result = inferPlatform(undefined, { platform: "instagram" });
    expect(result).toBe("instagram");
  });

  it("returns null when both are null", () => {
    expect(inferPlatform({ platform: null }, { platform: null })).toBeNull();
  });

  it("returns null when both lead and conversation are null/undefined", () => {
    expect(inferPlatform(null, null)).toBeNull();
    expect(inferPlatform(undefined, undefined)).toBeNull();
  });

  it("returns instagram when lead.platform is instagram", () => {
    expect(inferPlatform({ platform: "instagram" }, null)).toBe("instagram");
  });
});

describe("platformLabel", () => {
  it('returns "Messenger" for "messenger"', () => {
    expect(platformLabel("messenger")).toBe("Messenger");
  });

  it('returns "Instagram" for "instagram"', () => {
    expect(platformLabel("instagram")).toBe("Instagram");
  });

  it("returns the original string for unknown platforms", () => {
    expect(platformLabel("line")).toBe("line");
  });

  it('returns "—" for null', () => {
    expect(platformLabel(null)).toBe("—");
  });

  it('returns "—" for empty string', () => {
    expect(platformLabel("")).toBe("—");
  });
});
