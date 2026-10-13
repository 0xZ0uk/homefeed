import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  apiCommand,
  missingLayoutParts,
  resolveLayout,
  webCommand,
} from "./paths.js";

const resources = join("/opt", "Homefeed", "resources");
const repo = join("/src", "lenstube");

describe("resolveLayout", () => {
  it("uses the bundled Python and web server when packaged", () => {
    const linux = resolveLayout({
      isPackaged: true,
      platform: "linux",
      appPath: join(resources, "app.asar"),
      resourcesPath: resources,
    });
    expect(linux).toEqual({
      mode: "packaged",
      python: join(resources, "python", "bin", "python3"),
      webRoot: join(resources, "web"),
      srvxBin: join(
        resources,
        "web",
        "node_modules",
        "srvx",
        "bin",
        "srvx.mjs",
      ),
    });
    const windows = resolveLayout({
      isPackaged: true,
      platform: "win32",
      appPath: join(resources, "app.asar"),
      resourcesPath: resources,
    });
    expect(windows.python).toBe(join(resources, "python", "python.exe"));
  });

  it("uses the repo's venv and apps/web build in dev", () => {
    const layout = resolveLayout({
      isPackaged: false,
      platform: "linux",
      appPath: join(repo, "apps", "desktop"),
      resourcesPath: "/irrelevant",
      devSrvxBin: "/store/srvx/bin/srvx.mjs",
    });
    expect(layout).toEqual({
      mode: "dev",
      python: join(repo, ".venv", "bin", "python"),
      webRoot: join(repo, "apps", "web"),
      srvxBin: "/store/srvx/bin/srvx.mjs",
    });
    const windows = resolveLayout({
      isPackaged: false,
      platform: "win32",
      appPath: join(repo, "apps", "desktop"),
      resourcesPath: "/irrelevant",
    });
    expect(windows.python).toBe(join(repo, ".venv", "Scripts", "python.exe"));
  });
});

describe("missingLayoutParts", () => {
  const layout = resolveLayout({
    isPackaged: false,
    platform: "linux",
    appPath: join(repo, "apps", "desktop"),
    resourcesPath: "",
    devSrvxBin: "/srvx.mjs",
  });

  it("is empty when everything exists", () => {
    expect(missingLayoutParts(layout, () => true)).toEqual([]);
  });

  it("says how to fix each missing part", () => {
    const missing = missingLayoutParts(layout, () => false);
    expect(missing).toHaveLength(3);
    expect(missing[0]).toContain("uv sync --all-packages");
    expect(missing[1]).toContain("nub run build");
    expect(missing[2]).toContain("srvx");
  });

  it("checks the web server's entry file", () => {
    const missing = missingLayoutParts(
      layout,
      (path) =>
        path !== join(repo, "apps", "web", "dist", "server", "server.js"),
    );
    expect(missing).toEqual([expect.stringContaining("Web build not found")]);
  });
});

describe("commands", () => {
  const layout = resolveLayout({
    isPackaged: true,
    platform: "linux",
    appPath: "",
    resourcesPath: resources,
  });

  it("runs uvicorn on 127.0.0.1 from the data dir", () => {
    expect(apiCommand(layout, 41234, "/data")).toEqual({
      command: join(resources, "python", "bin", "python3"),
      args: [
        "-I",
        "-u",
        "-X",
        "utf8",
        "-m",
        "uvicorn",
        "homefeed_api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "41234",
        "--no-access-log",
      ],
      cwd: "/data",
    });
  });

  it("runs srvx with the given Node from the web root", () => {
    expect(webCommand(layout, "/opt/Homefeed/homefeed")).toEqual({
      command: "/opt/Homefeed/homefeed",
      args: [
        layout.srvxBin,
        "serve",
        "--prod",
        "--entry=dist/server/server.js",
        "--static=../client",
      ],
      cwd: join(resources, "web"),
    });
  });
});
