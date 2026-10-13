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
 *
 * With `HOMEFEED_MODE=desktop` (the Electron shell) there is no password.
 * The shell opens `/desktop-auth` with a per-launch `DESKTOP_TOKEN`, which
 * starts the same session; anything else gets a 401.
 */

export const LOGIN_PATH = "/login";
export const LOGOUT_PATH = "/logout";
export const DESKTOP_AUTH_PATH = "/desktop-auth";

const SESSION_COOKIE = "homefeed_session";
const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;
const MIN_SECRET_LENGTH = 32;

interface AuthSessionData {
  authenticated: boolean;
}

export type AppMode = "server" | "desktop";

export type AuthConfig =
  | { mode: "server"; password: string; sessionSecret: string }
  | { mode: "desktop"; desktopToken: string; sessionSecret: string };

/** Read and validate auth settings. Throws rather than running unprotected. */
export function readAuthConfig(
  env: Record<string, string | undefined> = process.env,
): AuthConfig {
  const mode = env.HOMEFEED_MODE || "server";
  if (mode !== "server" && mode !== "desktop") {
    throw new Error('HOMEFEED_MODE must be "server" or "desktop"');
  }
  const sessionSecret = env.SESSION_SECRET;
  if (mode === "desktop") {
    const desktopToken = env.DESKTOP_TOKEN;
    if (!desktopToken || desktopToken.length < MIN_SECRET_LENGTH) {
      throw new Error(
        `DESKTOP_TOKEN must be at least ${MIN_SECRET_LENGTH} characters`,
      );
    }
    checkSessionSecret(sessionSecret);
    return { mode, desktopToken, sessionSecret };
  }
  const password = env.APP_PASSWORD;
  if (!password) {
    throw new Error("APP_PASSWORD must be set");
  }
  checkSessionSecret(sessionSecret);
  return { mode, password, sessionSecret };
}

function checkSessionSecret(
  secret: string | undefined,
): asserts secret is string {
  if (!secret || secret.length < MIN_SECRET_LENGTH) {
    throw new Error(
      `SESSION_SECRET must be at least ${MIN_SECRET_LENGTH} characters`,
    );
  }
}

/** Whether the app runs inside the desktop shell. Server only. */
export function isDesktopMode(): boolean {
  return readAuthConfig().mode === "desktop";
}

/**
 * Compare secrets (passwords, the desktop token) without leaking where they
 * differ through timing.
 */
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
    // Browsers strip tabs and newlines from URLs, so "/\t/evil.example"
    // would turn into "//evil.example".
    hasControlCharacter(value) ||
    value === LOGIN_PATH ||
    value.startsWith(`${LOGIN_PATH}?`)
  ) {
    return "/";
  }
  return value;
}

function hasControlCharacter(value: string): boolean {
  for (let i = 0; i < value.length; i++) {
    const code = value.charCodeAt(i);
    if (code <= 0x1f || code === 0x7f) return true;
  }
  return false;
}

/** Login page URL that returns to `target` after signing in. */
export function loginUrl(target: string): string {
  const redirect = safeRedirectTarget(target);
  return redirect === "/"
    ? LOGIN_PATH
    : `${LOGIN_PATH}?${new URLSearchParams({ redirect })}`;
}

function sessionConfig() {
  const { mode, sessionSecret } = readAuthConfig();
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
      // The app may be served over plain HTTP on the home network, and the
      // desktop shell always uses http://127.0.0.1.
      secure:
        mode !== "desktop" && new URL(getRequest().url).protocol === "https:",
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
  const config = readAuthConfig();
  if (
    config.mode !== "server" ||
    !(await passwordMatches(password, config.password))
  ) {
    return false;
  }
  await startSession();
  return true;
}

/** Check the desktop token and start a session if it matches. Server only. */
export async function logInWithDesktopToken(token: string): Promise<boolean> {
  const config = readAuthConfig();
  if (
    config.mode !== "desktop" ||
    !(await passwordMatches(token, config.desktopToken))
  ) {
    return false;
  }
  await startSession();
  return true;
}

async function startSession(): Promise<void> {
  await updateSession<AuthSessionData>(sessionConfig(), {
    authenticated: true,
  });
}

/** End the current session. Server only. */
export async function logOut(): Promise<void> {
  await clearSession(sessionConfig());
}
