import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  autostartEntry,
  autostartEntryPath,
  linuxAutostartEnabled,
  linuxExecutable,
  quoteExecArg,
  setLinuxAutostart,
} from "./autostart.js";

describe("autostart entry", () => {
  it("quotes the executable per the desktop entry spec", () => {
    expect(quoteExecArg("/opt/Home feed/app")).toBe('"/opt/Home feed/app"');
    expect(quoteExecArg('a"b`c$d\\e')).toBe('"a\\"b\\`c\\$d\\\\e"');
  });

  it("starts the app hidden", () => {
    expect(autostartEntry("/home/u/Homefeed.AppImage")).toContain(
      'Exec="/home/u/Homefeed.AppImage" --hidden\n',
    );
  });

  it("prefers the AppImage over the extracted executable", () => {
    expect(
      linuxExecutable(
        { APPIMAGE: "/home/u/H.AppImage" },
        "/tmp/.mount_x/homefeed",
      ),
    ).toBe("/home/u/H.AppImage");
    expect(linuxExecutable({}, "/opt/homefeed/homefeed")).toBe(
      "/opt/homefeed/homefeed",
    );
  });

  it("is written to and removed from XDG_CONFIG_HOME/autostart", () => {
    const env = {
      XDG_CONFIG_HOME: mkdtempSync(join(tmpdir(), "homefeed-xdg-")),
    };
    const path = autostartEntryPath(env);
    expect(path).toBe(
      join(env.XDG_CONFIG_HOME, "autostart", "homefeed.desktop"),
    );
    expect(linuxAutostartEnabled(env)).toBe(false);
    setLinuxAutostart(true, "/opt/homefeed/homefeed", env);
    expect(linuxAutostartEnabled(env)).toBe(true);
    expect(readFileSync(path, "utf8")).toContain("Name=Homefeed");
    setLinuxAutostart(false, "/opt/homefeed/homefeed", env);
    expect(linuxAutostartEnabled(env)).toBe(false);
  });
});
