import { redirect } from "@tanstack/react-router";
import {
  createCsrfMiddleware,
  createMiddleware,
  createStart,
} from "@tanstack/react-start";

import { LOGIN_PATH, isAuthenticated, loginUrl } from "#/server/auth";

const csrfMiddleware = createCsrfMiddleware({
  filter: (ctx) => ctx.handlerType === "serverFn",
});

/**
 * Every request needs a session except the login page itself. This covers
 * page loads, server routes, and server function calls, so new routes and
 * server functions are protected without opting in.
 */
const authMiddleware = createMiddleware().server(
  async ({ request, pathname, handlerType, next }) => {
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
