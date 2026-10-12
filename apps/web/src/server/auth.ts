import {
  clearSession,
  getCookie,
  getRequest,
  unsealSession,
  updateSession,
} from "@tanstack/react-start/server";

/**
 * Single-password auth for the whole web app.
 *
 * The session lives in a cookie sealed (encrypted and signed) with
 * `SESSION_SECRET`. Enforcement happens in the global request middleware in
 * `src/start.ts`; routes and server functions don't need to check it themselves.
 */

export const LOGIN_PATH = "/login";
export const LOGOUT_PATH = "/logout";

const SESSION_COOKIE = "homefeed_session";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;
const MIN_SECRET_LENGTH = 32;

interface AuthSessionData {
  authenticated: boolean;
}

export interface AuthConfig {
  password: string;
  sessionSecret: string;
}

/** Read and validate auth settings. Throws rather than running unprotected. */
export function readAuthConfig(
  env: Record<string, string | undefined> = process.env,
): AuthConfig {
  const password = env.APP_PASSWORD;
  const sessionSecret = env.SESSION_SECRET;
  if (!password) {
    throw new Error("APP_PASSWORD must be set");
  }
  if (!sessionSecret || sessionSecret.length < MIN_SECRET_LENGTH) {
    throw new Error(
      `SESSION_SECRET must be at least ${MIN_SECRET_LENGTH} characters`,
    );
  }
  return { password, sessionSecret };
}

/** Compare passwords without leaking where they differ through timing. */
export async function passwordMatches(
  candidate: string,
  expected: string,
): Promise<boolean> {
  const [a, b] = await Promise.all([sha256(candidate), sha256(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) {
    diff |= a[i]! ^ b[i]!;
  }
  return diff === 0;
}

async function sha256(value: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return new Uint8Array(digest);
}

/**
 * Where to send the user after login. Only same-origin paths are allowed, so
 * the `redirect` parameter can't be used to bounce users to another site.
 */
export function safeRedirectTarget(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    value === LOGIN_PATH ||
    value.startsWith(`${LOGIN_PATH}?`)
  ) {
    return "/";
  }
  return value;
}

/** Login page URL that returns to `target` after signing in. */
export function loginUrl(target: string): string {
  const redirect = safeRedirectTarget(target);
  return redirect === "/"
    ? LOGIN_PATH
    : `${LOGIN_PATH}?${new URLSearchParams({ redirect })}`;
}

function sessionConfig() {
  const { sessionSecret } = readAuthConfig();
  return {
    name: SESSION_COOKIE,
    password: sessionSecret,
    maxAge: SESSION_MAX_AGE_SECONDS,
    // Only read the session from the cookie, never from a request header.
    sessionHeader: false as const,
    cookie: {
      httpOnly: true,
      sameSite: "lax" as const,
      path: "/",
      // The app may be served over plain HTTP on the home network.
      secure: new URL(getRequest().url).protocol === "https:",
    },
  };
}

/** Whether the current request carries a valid session. Server only. */
export async function isAuthenticated(): Promise<boolean> {
  const config = sessionConfig();
  // Unseal the cookie directly rather than via getSession, which would issue
  // an empty session cookie to every unauthenticated visitor.
  const sealed = getCookie(SESSION_COOKIE);
  if (!sealed) return false;
  try {
    const session = await unsealSession(config, sealed);
    return (
      (session.data as AuthSessionData | undefined)?.authenticated === true
    );
  } catch {
    // Tampered, signed with another secret, or expired.
    return false;
  }
}

/** Check the password and start a session if it matches. Server only. */
export async function logIn(password: string): Promise<boolean> {
  if (!(await passwordMatches(password, readAuthConfig().password))) {
    return false;
  }
  await updateSession<AuthSessionData>(sessionConfig(), {
    authenticated: true,
  });
  return true;
}

/** End the current session. Server only. */
export async function logOut(): Promise<void> {
  await clearSession(sessionConfig());
}
