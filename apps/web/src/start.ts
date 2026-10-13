import { redirect } from "@tanstack/react-router";
import {
  createCsrfMiddleware,
  createMiddleware,
  createStart,
} from "@tanstack/react-start";

import {
  DESKTOP_AUTH_PATH,
  LOGIN_PATH,
  LOGOUT_PATH,
  isAuthenticated,
  isDesktopMode,
  loginUrl,
} from "#/server/auth";

const csrfMiddleware = createCsrfMiddleware({
  filter: (ctx) => ctx.handlerType === "serverFn",
});

/**
 * Every request needs a session except the login page itself (or, in desktop
 * mode, `/desktop-auth`). This covers
 * page loads, server routes, and server function calls, so new routes and
 * server functions are protected without opting in.
 */
const authMiddleware = createMiddleware().server(
  async ({ request, pathname, handlerType, next }) => {
    if (isDesktopMode()) {
      if (handlerType === "router" && pathname === DESKTOP_AUTH_PATH) {
        return next();
      }
      // There's no password to type: the session only comes from the shell.
      if (pathname === LOGIN_PATH || pathname === LOGOUT_PATH) {
        return new Response("Not found", { status: 404 });
      }
      if (await isAuthenticated()) {
        return next();
      }
      return new Response(
        "<!doctype html><title>Homefeed</title><p>Open Homefeed from the desktop app</p>",
        {
          status: 401,
          headers: { "Content-Type": "text/html; charset=utf-8" },
        },
      );
    }

    const authenticated = await isAuthenticated();
    const isLoginPage = handlerType === "router" && pathname === LOGIN_PATH;

    if (isLoginPage) {
      if (authenticated && request.method === "GET") {
        throw redirect({ href: "/" });
      }
      return next();
    }
    if (authenticated) {
      return next();
    }

    // For server function calls, send the user back to the page they were on
    // (the client router follows the serialized redirect).
    const url = new URL(
      handlerType === "serverFn"
        ? (request.headers.get("referer") ?? "/")
        : request.url,
      request.url,
    );
    throw redirect({ href: loginUrl(url.pathname + url.search) });
  },
);

export const startInstance = createStart(() => ({
  requestMiddleware: [csrfMiddleware, authMiddleware],
}));
