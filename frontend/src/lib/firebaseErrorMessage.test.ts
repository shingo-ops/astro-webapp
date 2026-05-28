import { describe, expect, it, vi } from "vitest";
import { firebaseErrorMessage } from "./firebaseErrorMessage";

/** t mock — returns the key as-is */
const t = vi.fn((key: string) => key);

describe("firebaseErrorMessage", () => {
  it("maps auth/invalid-credential to the correct i18n key", () => {
    expect(firebaseErrorMessage({ code: "auth/invalid-credential" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("maps auth/wrong-password to invalidCredential (unified key)", () => {
    expect(firebaseErrorMessage({ code: "auth/wrong-password" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("maps auth/user-not-found to invalidCredential", () => {
    expect(firebaseErrorMessage({ code: "auth/user-not-found" }, t)).toBe(
      "firebaseError.invalidCredential",
    );
  });

  it("maps auth/invalid-email to invalidEmail", () => {
    expect(firebaseErrorMessage({ code: "auth/invalid-email" }, t)).toBe(
      "firebaseError.invalidEmail",
    );
  });

  it("maps auth/user-disabled to userDisabled", () => {
    expect(firebaseErrorMessage({ code: "auth/user-disabled" }, t)).toBe(
      "firebaseError.userDisabled",
    );
  });

  it("maps auth/too-many-requests to tooManyRequests", () => {
    expect(firebaseErrorMessage({ code: "auth/too-many-requests" }, t)).toBe(
      "firebaseError.tooManyRequests",
    );
  });

  it("maps auth/network-request-failed to networkRequestFailed", () => {
    expect(
      firebaseErrorMessage({ code: "auth/network-request-failed" }, t),
    ).toBe("firebaseError.networkRequestFailed");
  });

  it("maps auth/requires-recent-login to requiresRecentLogin", () => {
    expect(
      firebaseErrorMessage({ code: "auth/requires-recent-login" }, t),
    ).toBe("firebaseError.requiresRecentLogin");
  });

  it("falls back to default for unknown error codes", () => {
    expect(firebaseErrorMessage({ code: "auth/unknown-xyz" }, t)).toBe(
      "firebaseError.default",
    );
  });

  it("falls back to default for objects without a code property", () => {
    expect(firebaseErrorMessage({ message: "some error" }, t)).toBe(
      "firebaseError.default",
    );
  });

  it("falls back to default for null", () => {
    expect(firebaseErrorMessage(null, t)).toBe("firebaseError.default");
  });

  it("falls back to default for undefined", () => {
    expect(firebaseErrorMessage(undefined, t)).toBe("firebaseError.default");
  });

  it("falls back to default for string errors", () => {
    expect(firebaseErrorMessage("some string error", t)).toBe(
      "firebaseError.default",
    );
  });

  it("passes the correct key to the t function", () => {
    t.mockClear();
    firebaseErrorMessage({ code: "auth/invalid-credential" }, t);
    expect(t).toHaveBeenCalledWith("firebaseError.invalidCredential");
  });
});
