/**
 * Homefeed's Electron shell. Starts the Python API (with the worker's jobs in-process) and
 * the web server as child processes on free 127.0.0.1 ports, shows the web app in a
 * hardened window, and keeps running in the tray when the window is closed so feeds keep
 * refreshing. See README.md for the runtime layout and paths.ts for how children launch.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  app,
  BrowserWindow,
  dialog,
  Menu,
  nativeImage,
  screen,
  session,
  shell,
  Tray,
} from "electron";

import {
  HIDDEN_FLAG,
  linuxAutostartEnabled,
  linuxExecutable,
  setLinuxAutostart,
} from "./autostart.js";
import {
  apiEnv,
  dataPaths,
  desktopAuthUrl,
  generateSecret,
  webEnv,
  type DataPaths,
} from "./env.js";
import { RotatingLog } from "./log.js";
import {
  apiCommand,
  missingLayoutParts,
  resolveLayout,
  webCommand,
} from "./paths.js";
import { findFreePorts } from "./ports.js";
import { RestartPolicy, Service } from "./service.js";
import { SPLASH_URL } from "./splash.js";
import { Updater } from "./updater.js";
import { classifyUrl } from "./urls.js";
import {
  initialBounds,
  loadWindowState,
  saveWindowState,
} from "./window-state.js";

// Windows: taskbar grouping and notifications. The installer's appId must match.
const APP_ID = "app.homefeed.desktop";
// First start runs migrations and imports heavy libraries; slow disks and antivirus scans
// make that slower on Windows.
const READY_TIMEOUT_MS = 120_000;
// Permissions the web app may get (video fullscreen, copy buttons); everything else is denied.
const ALLOWED_PERMISSIONS = new Set([
  "fullscreen",
  "clipboard-sanitized-write",
]);

const env = process.env;
// For development and manual testing: run against a throwaway profile (data, logs,
// window state) instead of the real one. Must happen before anything reads userData.
const userDataOverride = env["HOMEFEED_USER_DATA_DIR"];
if (userDataOverride) app.setPath("userData", userDataOverride);
app.setAppLogsPath(join(app.getPath("userData"), "logs"));

const logsDir = app.getPath("logs");
const paths: DataPaths = dataPaths(app.getPath("userData"));
const windowStatePath = join(app.getPath("userData"), "window-state.json");
const iconPath = join(app.getAppPath(), "assets", "icon.png");

const shellLog = new RotatingLog(logsDir, "main");
const apiLog = new RotatingLog(logsDir, "api");
const webLog = new RotatingLog(logsDir, "web");

function log(message: string): void {
  shellLog.line(message);
  if (!app.isPackaged) console.log(`[homefeed] ${message}`);
}

type Phase = "starting" | "running" | "failed" | "stopping";

let phase: Phase = "starting";
let startHidden = process.argv.includes(HIDDEN_FLAG);
let quitting = false;
let shutdownDone = false;
let api: Service | null = null;
let web: Service | null = null;
let appOrigin = "";
let mainWindow: BrowserWindow | null = null;
let splashWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
const restarts = new RestartPolicy();
const restarting = new Set<Service>();
const updater = new Updater(log, () => updateTrayMenu());
let updaterStarted = false;

// --- Child processes ------------------------------------------------------------------

function devSrvxBin(): string | undefined {
  if (app.isPackaged) return undefined;
  try {
    return fileURLToPath(
      new URL("../bin/srvx.mjs", import.meta.resolve("srvx/cli")),
    );
  } catch {
    return undefined;
  }
}

/** Start the API and web server and wait for both; returns the URL that signs in. */
async function launchServices(): Promise<string> {
  const layout = resolveLayout({
    isPackaged: app.isPackaged,
    platform: process.platform,
    appPath: app.getAppPath(),
    resourcesPath: process.resourcesPath,
    devSrvxBin: devSrvxBin(),
  });
  const missing = missingLayoutParts(layout);
  if (missing.length > 0) throw new Error(missing.join("\n"));

  mkdirSync(paths.dataDir, { recursive: true });
  const [apiPort, webPort] = (await findFreePorts(2)) as [number, number];
  const desktopToken = generateSecret();
  const sessionSecret = generateSecret();
  log(
    `starting (${layout.mode}): api on ${apiPort}, web on ${webPort}, data in ${paths.dataDir}`,
  );

  api = new Service(
    {
      name: "api",
      ...apiCommand(layout, apiPort, paths.dataDir),
      env: apiEnv({ base: env, paths, jsRuntime: process.execPath }),
      readyUrl: `http://127.0.0.1:${apiPort}/health`,
      isReady: (response) => response.ok,
    },
    apiLog,
  );
  web = new Service(
    {
      name: "web",
      ...webCommand(layout, process.execPath),
      env: webEnv({
        base: env,
        port: webPort,
        apiPort,
        desktopToken,
        sessionSecret,
      }),
      readyUrl: `http://127.0.0.1:${webPort}/`,
      // Without a session the web app answers 401: it's up.
      isReady: (response) => response.status < 500,
      redact: [desktopToken, sessionSecret],
    },
    webLog,
  );
  for (const service of [api, web]) {
    service.onCrash = (code, signal) => void handleCrash(service, code, signal);
    service.start();
  }
  await Promise.all([
    api.waitUntilReady(READY_TIMEOUT_MS),
    web.waitUntilReady(READY_TIMEOUT_MS),
  ]);
  appOrigin = `http://127.0.0.1:${webPort}`;
  return desktopAuthUrl(webPort, desktopToken);
}

async function stopServices(): Promise<void> {
  await Promise.all([api?.stop(), web?.stop()]);
}

/** A child died after startup: restart it a few times, then give up with the error window. */
async function handleCrash(
  service: Service,
  code: number | null,
  signal: NodeJS.Signals | null,
): Promise<void> {
  // A crash while restarting is handled by the restart loop below.
  if (phase !== "running" || restarting.has(service)) return;
  const name = service.spec.name;
  log(`${name} exited unexpectedly (code ${code}, signal ${signal})`);
  restarting.add(service);
  try {
    while (phase === "running") {
      if (!restarts.tryRestart()) {
        await fail(
          new Error(`The ${name} process keeps stopping (see ${name}.log).`),
        );
        return;
      }
      log(`restarting ${name}`);
      service.start();
      try {
        await service.waitUntilReady(READY_TIMEOUT_MS);
        log(`${name} is back`);
        mainWindow?.webContents.reload();
        return;
      } catch (error) {
        log(
          `${name} didn't come back: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }
  } finally {
    restarting.delete(service);
  }
}

async function start(): Promise<void> {
  phase = "starting";
  if (!startHidden) showSplash();
  try {
    const authUrl = await launchServices();
    phase = "running";
    await openMainWindow(authUrl);
    if (!updaterStarted) {
      updaterStarted = true;
      updater.start({
        isPackaged: app.isPackaged,
        platform: process.platform,
        env,
      });
    }
  } catch (error) {
    await fail(error);
  } finally {
    closeSplash();
  }
}

/** Stop everything and show the error window: Retry, Open logs or Quit. */
async function fail(error: unknown): Promise<void> {
  if (phase === "failed" || phase === "stopping") return;
  phase = "failed";
  const message = error instanceof Error ? error.message : String(error);
  log(`failed: ${message}`);
  await stopServices();
  closeSplash();
  mainWindow?.hide();
  while (!quitting) {
    const { response } = await dialog.showMessageBox({
      type: "error",
      title: "Homefeed",
      message: "Homefeed couldn't start",
      detail: `${message}\n\nLogs are in ${logsDir}`,
      buttons: ["Retry", "Open logs", "Quit"],
      defaultId: 0,
      cancelId: 2,
      noLink: true,
    });
    if (response === 1) {
      await shell.openPath(logsDir);
      continue;
    }
    if (response === 0) {
      restarts.reset();
      startHidden = false;
      void start();
    } else {
      app.quit();
    }
    return;
  }
}

// --- Windows --------------------------------------------------------------------------

function showSplash(): void {
  if (splashWindow) return;
  splashWindow = new BrowserWindow({
    width: 360,
    height: 220,
    frame: false,
    resizable: false,
    center: true,
    show: false,
    title: "Homefeed",
    icon: iconPath,
    backgroundColor: "#0f0f0f",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  splashWindow.once("ready-to-show", () => splashWindow?.show());
  splashWindow.on("closed", () => (splashWindow = null));
  void splashWindow.loadURL(SPLASH_URL);
}

function closeSplash(): void {
  splashWindow?.destroy();
  splashWindow = null;
}

function saveMainWindowState(): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  saveWindowState(windowStatePath, {
    bounds: mainWindow.getNormalBounds(),
    maximized: mainWindow.isMaximized(),
  });
}

function createMainWindow(): BrowserWindow {
  const state = loadWindowState(windowStatePath);
  const bounds = initialBounds(
    state,
    screen.getAllDisplays().map((display) => display.workArea),
  );
  const win = new BrowserWindow({
    ...bounds,
    minWidth: 480,
    minHeight: 360,
    show: false,
    title: "Homefeed",
    icon: iconPath,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      spellcheck: false,
    },
  });
  if (state?.maximized) win.once("show", () => win.maximize());

  // Closing hides to the tray: the worker keeps refreshing feeds.
  win.on("close", (event) => {
    saveMainWindowState();
    if (!quitting) {
      event.preventDefault();
      win.hide();
    }
  });
  win.on("closed", () => (mainWindow = null));

  const contents = win.webContents;
  contents.on("will-navigate", (event, url) => {
    const kind = classifyUrl(url, appOrigin);
    if (kind === "app") return;
    event.preventDefault();
    if (kind === "external") void shell.openExternal(url);
  });
  contents.setWindowOpenHandler(({ url }) => {
    const kind = classifyUrl(url, appOrigin);
    if (kind === "external") void shell.openExternal(url);
    else if (kind === "app") void win.loadURL(url);
    return { action: "deny" };
  });
  contents.on("render-process-gone", (_event, details) => {
    log(`renderer gone (${details.reason}); reloading`);
    if (details.reason !== "clean-exit") contents.reload();
  });
  return win;
}

async function openMainWindow(url: string): Promise<void> {
  mainWindow ??= createMainWindow();
  try {
    await mainWindow.loadURL(url);
  } catch (error) {
    // Logged only: the window shows Chromium's error page, and Retry reloads.
    log(
      `loading the app failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!startHidden) showMainWindow();
}

function showMainWindow(): void {
  startHidden = false;
  if (!mainWindow) {
    // Still starting (e.g. launched at login, hidden): show progress instead.
    if (phase === "starting") showSplash();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

// --- Tray -----------------------------------------------------------------------------

function autostartEnabled(): boolean {
  if (process.platform === "linux") return linuxAutostartEnabled(env);
  return app.getLoginItemSettings({ args: [HIDDEN_FLAG] }).openAtLogin;
}

function setAutostart(enabled: boolean): void {
  if (process.platform === "linux") {
    setLinuxAutostart(enabled, linuxExecutable(env, process.execPath), env);
  } else {
    app.setLoginItemSettings({ openAtLogin: enabled, args: [HIDDEN_FLAG] });
  }
}

function updateTrayMenu(): void {
  const update = updater.readyVersion;
  tray?.setContextMenu(
    Menu.buildFromTemplate([
      ...(update
        ? [
            {
              label: `Restart to update (${update})`,
              click: restartToUpdate,
            },
            { type: "separator" as const },
          ]
        : []),
      { label: "Open Homefeed", click: showMainWindow },
      { type: "separator" },
      {
        label: "Start at login",
        type: "checkbox",
        checked: app.isPackaged && autostartEnabled(),
        // In dev the executable is Electron itself, which wouldn't start Homefeed.
        enabled: app.isPackaged,
        click: (item) => {
          setAutostart(item.checked);
          updateTrayMenu();
        },
      },
      {
        label: "Open data folder",
        click: () => void shell.openPath(paths.dataDir),
      },
      { label: "Open logs", click: () => void shell.openPath(logsDir) },
      { type: "separator" },
      { label: "Quit Homefeed", click: () => app.quit() },
    ]),
  );
}

function createTray(): void {
  const size = process.platform === "win32" ? 16 : 32;
  tray = new Tray(
    nativeImage.createFromPath(iconPath).resize({ width: size, height: size }),
  );
  tray.setToolTip("Homefeed");
  tray.on("click", showMainWindow);
  updateTrayMenu();
}

// --- App lifecycle --------------------------------------------------------------------

/** Stops the children before quitting (any quit, including one that installs an update). */
async function shutdown(): Promise<void> {
  phase = "stopping";
  quitting = true;
  updater.stop();
  saveMainWindowState();
  log("quitting");
  try {
    await stopServices();
  } finally {
    shutdownDone = true;
    log("stopped");
  }
}

/** Tray "Restart to update": stop the children first, their files are being replaced. */
function restartToUpdate(): void {
  if (phase === "stopping") return;
  log(`restarting to install update ${updater.readyVersion}`);
  void shutdown().finally(() => {
    updater.quitAndInstall();
    // If the installer couldn't start, quit anyway (the children are gone); the update
    // is then retried on quit.
    setTimeout(() => app.quit(), 3000);
  });
}

function killServicesSync(): void {
  api?.killSync();
  web?.killSync();
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  // Whatever happens to the shell, its children must not outlive it.
  process.on("exit", killServicesSync);
  process.on("uncaughtException", (error) => {
    log(`uncaught exception: ${error.stack ?? error.message}`);
    killServicesSync();
    dialog.showErrorBox(
      "Homefeed crashed",
      `${error.message}\n\nLogs are in ${logsDir}`,
    );
    app.exit(1);
  });
  for (const signal of ["SIGINT", "SIGTERM"] as const)
    process.on(signal, () => app.quit());

  app.on("second-instance", showMainWindow);
  // Windows only close on quit; until then the app lives in the tray.
  app.on("window-all-closed", () => {});
  app.on("before-quit", (event) => {
    quitting = true;
    if (shutdownDone) return;
    event.preventDefault();
    if (phase === "stopping") return;
    void shutdown().finally(() => app.quit());
  });

  if (process.platform === "win32") app.setAppUserModelId(APP_ID);
  void app.whenReady().then(() => {
    log(
      `Homefeed ${app.getVersion()} (Electron ${process.versions.electron}), logs in ${logsDir}`,
    );
    if (app.isPackaged) Menu.setApplicationMenu(null);
    session.defaultSession.setPermissionRequestHandler(
      (_contents, permission, callback) =>
        callback(ALLOWED_PERMISSIONS.has(permission)),
    );
    createTray();
    void start();
  });
}
