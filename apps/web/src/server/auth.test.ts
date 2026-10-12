import { describe, expect, it } from "vitest";

import {
  loginUrl,
  passwordMatches,
  readAuthConfig,
  safeRedirectTarget,
} from "./auth";

const secret = "x".repeat(32);

describe("readAuthConfig", () => {
  it("reads the password and session secret", () => {
    expect(
      readAuthConfig({ APP_PASSWORD: "hunter2", SESSION_SECRET: secret }),
    ).toEqual({ password: "hunter2", sessionSecret: secret });
  });

  it("refuses to run without a password", () => {
    expect(() => readAuthConfig({ SESSION_SECRET: secret })).toThrow(
      "APP_PASSWORD",
    );
    expect(() =>
      readAuthConfig({ APP_PASSWORD: "", SESSION_SECRET: secret }),
    ).toThrow("APP_PASSWORD");
  });

  it("refuses a missing or short session secret", () => {
    expect(() => readAuthConfig({ APP_PASSWORD: "hunter2" })).toThrow(
      "SESSION_SECRET",
    );
    expect(() =>
      readAuthConfig({ APP_PASSWORD: "hunter2", SESSION_SECRET: "short" }),
    ).toThrow("SESSION_SECRET");
  });
});

describe("passwordMatches", () => {
  it("accepts the exact password", async () => {
    expect(await passwordMatches("hunter2", "hunter2")).toBe(true);
  });

  it("rejects anything else", async () => {
    expect(await passwordMatches("hunter3", "hunter2")).toBe(false);
    expect(await passwordMatches("hunter", "hunter2")).toBe(false);
    expect(await passwordMatches("", "hunter2")).toBe(false);
    expect(await passwordMatches("Hunter2", "hunter2")).toBe(false);
  });
});

describe("safeRedirectTarget", () => {
  it("keeps same-origin paths", () => {
    expect(safeRedirectTarget("/queue")).toBe("/queue");
    expect(safeRedirectTarget("/watch/abc?t=10")).toBe("/watch/abc?t=10");
  });

  it("falls back to home for anything else", () => {
    for (const value of [
      undefined,
      null,
      42,
      "",
      "queue",
      "https://evil.example",
      "//evil.example",
      "/\\evil.example",
      "/login",
      "/login?redirect=/queue",
    ]) {
      expect(safeRedirectTarget(value)).toBe("/");
    }
  });
});

describe("loginUrl", () => {
  it("omits the redirect for the home page", () => {
    expect(loginUrl("/")).toBe("/login");
  });

  it("carries the original path", () => {
    expect(loginUrl("/watch/abc?t=10")).toBe(
      "/login?redirect=%2Fwatch%2Fabc%3Ft%3D10",
    );
  });
});
