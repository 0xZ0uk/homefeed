import { describe, expect, it } from "vitest";

import {
  loginUrl,
  passwordMatches,
  readAuthConfig,
  safeRedirectTarget,
} from "./auth";

const secret = "x".repeat(32);
const token = "t".repeat(32);

describe("readAuthConfig", () => {
  it("reads the password and session secret", () => {
    expect(
      readAuthConfig({ APP_PASSWORD: "hunter2", SESSION_SECRET: secret }),
    ).toEqual({
      mode: "server",
      password: "hunter2",
      sessionSecret: secret,
    });
  });

  it("treats an empty HOMEFEED_MODE as server mode", () => {
    expect(
      readAuthConfig({
        HOMEFEED_MODE: "",
        APP_PASSWORD: "hunter2",
        SESSION_SECRET: secret,
      }).mode,
    ).toBe("server");
  });

  it("still requires the password in server mode, whatever else is set", () => {
    expect(() =>
      readAuthConfig({
        HOMEFEED_MODE: "server",
        DESKTOP_TOKEN: token,
        SESSION_SECRET: secret,
      }),
    ).toThrow("APP_PASSWORD");
  });

  it("refuses an unknown mode", () => {
    expect(() =>
      readAuthConfig({
        HOMEFEED_MODE: "Desktop",
        APP_PASSWORD: "hunter2",
        SESSION_SECRET: secret,
      }),
    ).toThrow("HOMEFEED_MODE");
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

describe("readAuthConfig in desktop mode", () => {
  it("reads the token and session secret without a password", () => {
    expect(
      readAuthConfig({
        HOMEFEED_MODE: "desktop",
        DESKTOP_TOKEN: token,
        SESSION_SECRET: secret,
      }),
    ).toEqual({ mode: "desktop", desktopToken: token, sessionSecret: secret });
  });

  it("refuses a missing or short token", () => {
    const env = { HOMEFEED_MODE: "desktop", SESSION_SECRET: secret };
    expect(() => readAuthConfig(env)).toThrow("DESKTOP_TOKEN");
    expect(() => readAuthConfig({ ...env, DESKTOP_TOKEN: "short" })).toThrow(
      "DESKTOP_TOKEN",
    );
  });

  it("refuses a missing or short session secret", () => {
    const env = { HOMEFEED_MODE: "desktop", DESKTOP_TOKEN: token };
    expect(() => readAuthConfig(env)).toThrow("SESSION_SECRET");
    expect(() => readAuthConfig({ ...env, SESSION_SECRET: "short" })).toThrow(
      "SESSION_SECRET",
    );
  });

  it("matches the token exactly", async () => {
    expect(await passwordMatches(token, token)).toBe(true);
    expect(await passwordMatches(token.slice(1), token)).toBe(false);
    expect(await passwordMatches(`${token}x`, token)).toBe(false);
    expect(await passwordMatches("", token)).toBe(false);
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
      "/\t/evil.example",
      "/\n/evil.example",
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
