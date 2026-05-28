import { describe, expect, it, vi } from "vitest";
import { firebaseErrorMessage } from "./firebaseErrorMessage";

/** t 関数のモック — キーをそのまま返す */
const t = vi.fn((key: string) => key);

describe("firebaseErrorMessage", () => {
  it("auth/invalid-credential を正しいキーにマップする", () => {
    expect(firebaseErrorMessage({ code: "auth/invalid-credential" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("auth/wrong-password を invalidCredential にマップする（統合キー）", () => {
    expect(firebaseErrorMessage({ code: "auth/wrong-password" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("auth/user-not-found を invalidCredential にマップする", () => {
    expect(firebaseErrorMessage({ code: "auth/user-not-found" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("auth/invalid-email を invalidEmail にマップする", () => {
    expect(firebaseErrorMessage({ code: "auth/invalid-email" }, t)).toBe(
      "firebaseError.invalidEmail",
    );
  });

  it("auth/user-disabled を userDisabled にマップする", () => {
    expect(firebaseErrorMessage({ code: "auth/user-disabled" }, t)).toBe(
      "firebaseError.userDisabled",
    );
  });

  it("auth/too-many-requests を tooManyRequests にマップする", () => {
    expect(firebaseErrorMessage({ code: "auth/too-many-requests" }, t)).toBe(
      "firebaseError.tooManyRequests",
    );
  });

  it("auth/network-request-failed を networkRequestFailed にマップする", () => {
    expect(
      firebaseErrorMessage({ code: "auth/network-request-failed" }, t),
    ).toBe("firebaseError.networkRequestFailed");
  });

  it("auth/requires-recent-login を requiresRecentLogin にマップする", () => {
    expect(
      firebaseErrorMessage({ code: "auth/requires-recent-login" }, t),
    ).toBe("firebaseError.requiresRecentLogin");
  });

  it("未知の error code は default にフォールバックする", () => {
    expect(firebaseErrorMessage({ code: "auth/unknown-xyz" }, t)).toBe(
      "firebaseError.default",
    );
  });

  it("code を持たないオブジェクトは default にフォールバックする", () => {
    expect(firebaseErrorMessage({ message: "some error" }, t)).toBe(
      "firebaseError.default",
    );
  });

  it("null は default にフォールバックする", () => {
    expect(firebaseErrorMessage(null, t)).toBe("firebaseError.default");
  });

  it("undefined は default にフォールバックする", () => {
    expect(firebaseErrorMessage(undefined, t)).toBe("firebaseError.default");
  });

  it("文字列エラーは default にフォールバックする", () => {
    expect(firebaseErrorMessage("some string error", t)).toBe(
      "firebaseError.default",
    );
  });

  it("t 関数に正しいキーが渡されている", () => {
    t.mockClear();
    firebaseErrorMessage({ code: "auth/invalid-credential" }, t);
    expect(t).toHaveBeenCalledWith("firebaseError.invalidCredential");
  });
});
