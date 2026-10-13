import { createServerFn } from "@tanstack/react-start";

import { isDesktopMode, type AppMode } from "#/server/auth";

/** Which mode the app runs in, so the UI can hide what doesn't apply. */
export const getAppMode = createServerFn({ method: "GET" }).handler(
  (): AppMode => (isDesktopMode() ? "desktop" : "server"),
);
