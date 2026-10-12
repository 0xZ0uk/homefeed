import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";
import { getCookie, getRequest, setCookie } from "@tanstack/react-start/server";

import {
  DISPLAY_COOKIE,
  normalizeDisplayPrefs,
  parseDisplayPrefs,
  serializeDisplayPrefs,
  type DisplayPrefs,
} from "#/lib/display";

const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

const fetchDisplayPrefs = createServerFn({ method: "GET" }).handler(
  (): DisplayPrefs => parseDisplayPrefs(getCookie(DISPLAY_COOKIE)),
);

/** Save the thumbnail and view count toggles for this browser. */
export const saveDisplayPrefs = createServerFn({ method: "POST" })
  .inputValidator((data: DisplayPrefs) => normalizeDisplayPrefs(data))
  .handler(({ data }): DisplayPrefs => {
    setCookie(DISPLAY_COOKIE, serializeDisplayPrefs(data), {
      path: "/",
      maxAge: ONE_YEAR_SECONDS,
      sameSite: "lax",
      httpOnly: true,
      secure: new URL(getRequest().url).protocol === "https:",
    });
    return data;
  });

export const displayPrefsQuery = queryOptions({
  queryKey: ["display-prefs"],
  queryFn: () => fetchDisplayPrefs(),
  staleTime: Infinity,
});
