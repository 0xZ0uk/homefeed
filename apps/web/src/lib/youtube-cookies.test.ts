import { describe, expect, it } from "vitest";

import {
  NO_COOKIES,
  OTHER_BROWSER,
  browserChoice,
  cookieCheckMessage,
  isBotCheck,
} from "./youtube-cookies";

const zen = { label: "Zen (Work)", value: "firefox:/home/me/.zen/abcd.Work" };

describe("browserChoice", () => {
  it("picks none, a detected profile or a value typed in", () => {
    expect(browserChoice(null, [zen])).toBe(NO_COOKIES);
    expect(browserChoice(zen.value, [zen])).toBe(zen.value);
    expect(browserChoice("chrome:Profile 2", [zen])).toBe(OTHER_BROWSER);
  });
});

describe("cookieCheckMessage", () => {
  it("says whether the cookies are signed in", () => {
    expect(
      cookieCheckMessage({ youtube_cookies: 20, signed_in: true }),
    ).toMatch(/^Signed in/);
    expect(
      cookieCheckMessage({ youtube_cookies: 3, signed_in: false }),
    ).toMatch(/isn't signed in/);
    expect(
      cookieCheckMessage({ youtube_cookies: 0, signed_in: false }),
    ).toMatch(/no YouTube cookies/);
  });
});

describe("isBotCheck", () => {
  it("recognizes YouTube's bot check", () => {
    expect(
      isBotCheck(
        "[youtube] XuOdXelwse4: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
      ),
    ).toBe(true);
    expect(isBotCheck("Sign in to confirm you're not a bot")).toBe(true);
    expect(isBotCheck("This video is private")).toBe(false);
  });
});
