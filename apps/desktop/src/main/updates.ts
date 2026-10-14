/** When the app updates itself (see updater.ts). Pure, so it can be tested without Electron. */

/** First check, once the app is up (not during startup, which is busy enough). */
export const FIRST_CHECK_DELAY_MS = 30_000;
export const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

export type UpdateSupport =
  { enabled: true } | { enabled: false; reason: string };

/**
 * Updates come from the installer's release feed, so only packaged builds update: on
 * Windows the NSIS install, on Linux only the AppImage (electron-updater replaces the file
 * named by `APPIMAGE`; an unpacked build has nothing to replace).
 */
export function updateSupport(input: {
  isPackaged: boolean;
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
}): UpdateSupport {
  if (!input.isPackaged) {
    return { enabled: false, reason: "not a packaged build" };
  }
  if (input.platform === "win32") return { enabled: true };
  if (input.platform === "linux") {
    return input.env["APPIMAGE"]
      ? { enabled: true }
      : { enabled: false, reason: "not running as an AppImage" };
  }
  return { enabled: false, reason: `no installer for ${input.platform}` };
}
