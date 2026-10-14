/**
 * electron-builder: the Windows installer (NSIS) and the Linux AppImage. Run through
 * `nub run dist` (or the release workflow) after the bundle scripts; see README.md,
 * "Building installers".
 *
 * Unsigned on purpose: there's no code-signing certificate, so Windows SmartScreen warns
 * on first install (INSTALL.md explains "More info → Run anyway").
 */

// The GitHub repo whose releases the app updates from (and CI publishes to): this one.
// It's private, so only an install that can read it (e.g. with a token) finds updates;
// anywhere else the check is a logged 404. HOMEFEED_RELEASES_REPO overrides it at build
// time (owner/name). See README.md, "Releasing".
const RELEASES_REPO =
  // eslint-disable-next-line turbo/no-undeclared-env-vars -- not a turbo task
  process.env.HOMEFEED_RELEASES_REPO || "0xZ0uk/lenstube";
const [owner, repo] = RELEASES_REPO.split("/");

/** @type {import("electron-builder").Configuration} */
export default {
  appId: "app.homefeed.desktop",
  productName: "Homefeed",
  copyright: "Copyright © Pedro Santana",
  directories: { output: "build/release", buildResources: "assets" },
  // No certificate: never require signing (CI also sets CSC_IDENTITY_AUTO_DISCOVERY=false
  // and no CSC_LINK, so nothing is signed).
  forceCodeSigning: false,

  // The shell only: the main process bundled into one file (scripts/bundle-main.mjs),
  // no node_modules. Python and the web server are extraResources, outside the asar.
  asar: true,
  files: ["package.json", "dist/bundle/main.js", "assets/icon.png"],
  // desktopName: the window's WM_CLASS / app_id on Linux, matching the .desktop entry.
  extraMetadata: {
    main: "dist/bundle/main.js",
    desktopName: "homefeed.desktop",
  },
  extraResources: [
    { from: "build/python", to: "python" },
    { from: "build/web", to: "web" },
    // electron-builder always drops a copied directory's top-level node_modules.
    { from: "build/web/node_modules", to: "web/node_modules" },
  ],
  // Nothing to rebuild: the shell has no native modules (the Python bundle has its own).
  npmRebuild: false,
  nodeGypRebuild: false,

  // CI uploads to a draft release and publishes it once every installer is in (see
  // .github/workflows/desktop-release.yml).
  publish: { provider: "github", owner, repo, releaseType: "draft" },

  win: {
    target: [{ target: "nsis", arch: ["x64"] }],
    icon: "assets/icon.ico",
    artifactName: "Homefeed-Setup-${version}.${ext}",
    // Unsigned, so the updater can't check a publisher signature on new installers (they
    // come from the releases repo over HTTPS, with their sha512 from latest.yml).
    verifyUpdateCodeSignature: false,
  },
  nsis: {
    // One click: no questions for non-technical users (no admin prompt, no directory
    // picker); installs per user into %LOCALAPPDATA%\Programs\Homefeed and starts the app.
    oneClick: true,
    perMachine: false,
    runAfterFinish: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "Homefeed",
    installerIcon: "assets/icon.ico",
    uninstallerIcon: "assets/icon.ico",
    // Keep the data (feeds, ratings, models) on uninstall; INSTALL.md says where it is.
    deleteAppDataOnUninstall: false,
  },

  linux: {
    target: [{ target: "AppImage", arch: ["x64"] }],
    icon: "assets/icon.png",
    category: "AudioVideo",
    artifactName: "Homefeed-${version}-x86_64.${ext}",
    executableName: "homefeed",
  },
};
