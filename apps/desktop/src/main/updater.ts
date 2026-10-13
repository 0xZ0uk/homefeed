/**
 * App updates through electron-updater: checks the release feed (GitHub releases of the
 * repo in electron-builder.config.mjs, baked into the install as app-update.yml) once the
 * app is up and every 6 hours, downloads in the background, and installs on quit. When an
 * update is downloaded, `onReady` lets the shell offer "Restart to update" in the tray.
 */
import { Notification } from "electron";
import electronUpdater from "electron-updater";

import {
  CHECK_INTERVAL_MS,
  FIRST_CHECK_DELAY_MS,
  updateSupport,
} from "./updates.js";

// electron-updater is CommonJS: its named exports aren't visible to ES module imports.
const { autoUpdater } = electronUpdater;

export class Updater {
  /** The downloaded version waiting to be installed, if any. */
  readyVersion: string | null = null;
  private timers: NodeJS.Timeout[] = [];

  constructor(
    private readonly log: (message: string) => void,
    private readonly onReady: (version: string) => void,
  ) {}

  /** Starts checking, if this build can update itself (otherwise logs why not). */
  start(input: {
    isPackaged: boolean;
    platform: NodeJS.Platform;
    env: NodeJS.ProcessEnv;
  }): void {
    const support = updateSupport(input);
    if (!support.enabled) {
      this.log(`updates off: ${support.reason}`);
      return;
    }
    // First line only: HTTP errors come with every response header.
    const log = (level: string) => (message: unknown) =>
      this.log(`updater ${level}: ${String(message).split("\n")[0]}`);
    autoUpdater.logger = {
      info: log("info"),
      warn: log("warn"),
      error: log("error"),
      debug: () => {},
    };
    autoUpdater.autoDownload = true;
    autoUpdater.autoInstallOnAppQuit = true;
    // Already logged through `logger`; an "error" event without a listener would throw.
    autoUpdater.on("error", () => {});
    autoUpdater.on("update-downloaded", (info) => {
      if (this.readyVersion === info.version) return;
      this.readyVersion = info.version;
      this.log(`update ${info.version} downloaded; installs on quit`);
      if (Notification.isSupported()) {
        new Notification({
          title: "Homefeed",
          body: "Update ready — restart Homefeed to install",
        }).show();
      }
      this.onReady(info.version);
    });
    this.timers.push(
      setTimeout(() => this.check(), FIRST_CHECK_DELAY_MS),
      setInterval(() => this.check(), CHECK_INTERVAL_MS),
    );
  }

  /**
   * Installs the downloaded update and relaunches. Call only after the child processes
   * have stopped (their files are about to be replaced); `app.quit()` follows.
   */
  quitAndInstall(): void {
    this.stop();
    // Silent: the one-click installer shows nothing; then start the new version.
    autoUpdater.quitAndInstall(true, true);
  }

  stop(): void {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers = [];
  }

  private check(): void {
    // Errors (offline, no release yet) also arrive as "error" events.
    autoUpdater.checkForUpdates().catch(() => {});
  }
}
