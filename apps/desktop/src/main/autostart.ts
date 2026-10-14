/**
 * "Start at login". Windows (and macOS) use `app.setLoginItemSettings`; Electron doesn't
 * support it on Linux, where an XDG autostart entry (`~/.config/autostart/*.desktop`) does
 * the same. Either way the app starts with `--hidden`: in the tray, no window.
 */
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export const HIDDEN_FLAG = "--hidden";

export function autostartEntryPath(env: NodeJS.ProcessEnv): string {
  const configHome = env["XDG_CONFIG_HOME"] || join(homedir(), ".config");
  return join(configHome, "autostart", "homefeed.desktop");
}

/** Quote an argument for a desktop entry's Exec key (Desktop Entry spec, "The Exec key"). */
export function quoteExecArg(arg: string): string {
  return `"${arg.replace(/["`$\\]/g, (char) => `\\${char}`)}"`;
}

export function autostartEntry(executable: string): string {
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Name=Homefeed",
    `Exec=${quoteExecArg(executable)} ${HIDDEN_FLAG}`,
    "X-GNOME-Autostart-enabled=true",
    "",
  ].join("\n");
}

export function linuxAutostartEnabled(env: NodeJS.ProcessEnv): boolean {
  return existsSync(autostartEntryPath(env));
}

export function setLinuxAutostart(
  enabled: boolean,
  executable: string,
  env: NodeJS.ProcessEnv,
): void {
  const path = autostartEntryPath(env);
  if (enabled) {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, autostartEntry(executable));
  } else {
    rmSync(path, { force: true });
  }
}

/** The file to start at login on Linux: the AppImage itself when run from one. */
export function linuxExecutable(
  env: NodeJS.ProcessEnv,
  execPath: string,
): string {
  return env["APPIMAGE"] || execPath;
}
