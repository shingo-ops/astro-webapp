import { describe, expect, it } from "vitest";
import { inferPlatform, platformLabel } from "./messages";

describe("inferPlatform", () => {
  it("lead.platform を最優先で返す", () => {
    const result = inferPlatform(
      { platform: "messenger" },
      { platform: "instagram" },
    );
    expect(result).toBe("messenger");
  });

  it("lead.platform が null のとき conversation.platform にフォールバックする", () => {
    const result = inferPlatform(
      { platform: null },
      { platform: "instagram" },
    );
    expect(result).toBe("instagram");
  });

  it("lead が null のとき conversation.platform にフォールバックする", () => {
    const result = inferPlatform(null, { platform: "messenger" });
    expect(result).toBe("messenger");
  });

  it("lead が undefined のとき conversation.platform にフォールバックする", () => {
    const result = inferPlatform(undefined, { platform: "instagram" });
    expect(result).toBe("instagram");
  });

  it("両方 null のとき null を返す", () => {
    expect(inferPlatform({ platform: null }, { platform: null })).toBeNull();
  });

  it("両方 null/undefined のとき null を返す", () => {
    expect(inferPlatform(null, null)).toBeNull();
    expect(inferPlatform(undefined, undefined)).toBeNull();
  });

  it("lead.platform が instagram でも正しく返す", () => {
    expect(inferPlatform({ platform: "instagram" }, null)).toBe("instagram");
  });
});

describe("platformLabel", () => {
  it('"messenger" → "Messenger"', () => {
    expect(platformLabel("messenger")).toBe("Messenger");
  });

  it('"instagram" → "Instagram"', () => {
    expect(platformLabel("instagram")).toBe("Instagram");
  });

  it("未知の文字列はそのまま返す", () => {
    expect(platformLabel("line")).toBe("line");
  });

  it('null → "—"', () => {
    expect(platformLabel(null)).toBe("—");
  });

  it('空文字 → "—"', () => {
    expect(platformLabel("")).toBe("—");
  });
});
