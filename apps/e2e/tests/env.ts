/** Where the e2e servers listen, and the web app's login secrets. Not the dev
 * ports (8000/3000), so the suite can run next to `nub run dev`. */
export const API_URL = `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8799"}`;
export const WEB_URL = `http://localhost:${process.env.E2E_WEB_PORT ?? "3799"}`;
export const APP_PASSWORD = "e2e-password";
export const SESSION_SECRET = "e2e-session-secret-0123456789abcdef";

/** The logged-in session, saved by `auth.setup.ts` for the other tests. */
export const AUTH_FILE = new URL("./.auth/session.json", import.meta.url)
  .pathname;
