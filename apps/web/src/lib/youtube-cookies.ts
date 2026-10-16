import type { BrowserProfileOut, CookieCheckOut } from "@homefeed/api-client";

/** Pure helpers for YouTube sign-in: the browser yt-dlp takes YouTube cookies from. */

/** Where the settings page's YouTube sign-in section is, for links to it. */
export const YOUTUBE_SIGN_IN_ID = "youtube-sign-in";

/** The browser picker's choices besides the detected profiles. */
export const NO_COOKIES = "";
export const OTHER_BROWSER = "other";

/** The picker's choice for a saved value: none, a detected profile, or one typed in. */
export function browserChoice(
  current: string | null,
  options: readonly BrowserProfileOut[],
): string {
  if (!current) return NO_COOKIES;
  return options.some((option) => option.value === current)
    ? current
    : OTHER_BROWSER;
}

/** What a cookie check found, in a sentence. */
export function cookieCheckMessage(check: CookieCheckOut): string {
  if (check.signed_in) {
    return "Signed in to YouTube. Homefeed can use these cookies.";
  }
  if (check.youtube_cookies === 0) {
    return "This browser has no YouTube cookies. Sign in to YouTube in it, then check again.";
  }
  return "This browser isn't signed in to YouTube. Sign in to YouTube in it, then check again.";
}

/** Whether an error is YouTube's "Sign in to confirm you're not a bot" check. */
export function isBotCheck(message: string): boolean {
  return /confirm you['’]re not a bot/i.test(message);
}
