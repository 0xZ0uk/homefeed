import { createFileRoute } from "@tanstack/react-router";

import {
  isDesktopMode,
  logInWithDesktopToken,
  safeRedirectTarget,
} from "#/server/auth";

/**
 * Entry point for the Electron shell: `?token=<DESKTOP_TOKEN>&next=<path>`
 * starts a session and redirects to `next`. Exempt from the auth middleware
 * (see `src/start.ts`) and only available in desktop mode.
 */
export const Route = createFileRoute("/desktop-auth")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        if (!isDesktopMode()) {
          return new Response("Not found", { status: 404 });
        }
        const params = new URL(request.url).searchParams;
        const token = params.get("token");
        if (token === null || !(await logInWithDesktopToken(token))) {
          return new Response("Forbidden", { status: 403 });
        }
        return new Response(null, {
          status: 303,
          headers: { Location: safeRedirectTarget(params.get("next")) },
        });
      },
    },
  },
});
