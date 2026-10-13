import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  apiEnv,
  dataPaths,
  desktopAuthUrl,
  generateSecret,
  webEnv,
} from "./env.js";

describe("generateSecret", () => {
  it("is long enough for the web server and different each time", () => {
    const a = generateSecret();
    expect(a.length).toBeGreaterThanOrEqual(32);
    expect(a).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(generateSecret()).not.toBe(a);
  });
});

describe("dataPaths", () => {
  it("puts the database in userData/data", () => {
    expect(dataPaths("/home/u/.config/Homefeed")).toEqual({
      dataDir: join("/home/u/.config/Homefeed", "data"),
      databasePath: join("/home/u/.config/Homefeed", "data", "homefeed.sqlite"),
    });
  });
});

describe("apiEnv", () => {
  const paths = dataPaths("/ud");

  it("sets the desktop defaults and keeps the rest of the environment", () => {
    const env = apiEnv({
      base: {
        PATH: "/usr/bin",
        EMBEDDING_PROVIDER: "openrouter",
        PYTHONPATH: "/elsewhere",
      },
      paths,
      jsRuntime: "/opt/Homefeed/homefeed",
    });
    expect(env).toEqual({
      PATH: "/usr/bin",
      DATA_DIR: paths.dataDir,
      DATABASE_PATH: paths.databasePath,
      RUN_WORKER_IN_API: "true",
      EMBEDDING_PROVIDER: "local",
      EMBEDDING_MODEL: "BAAI/bge-small-en-v1.5",
      LLM_PROVIDER: "openrouter",
      YTDLP_AUTO_UPDATE: "true",
      HOMEFEED_JS_RUNTIME: "/opt/Homefeed/homefeed",
      ELECTRON_RUN_AS_NODE: "1",
      HOMEFEED_NO_DOTENV: "1",
    });
  });
});

describe("webEnv", () => {
  it("runs the web server in desktop mode on 127.0.0.1", () => {
    const env = webEnv({
      base: { PATH: "/usr/bin", HOMEFEED_MODE: "server" },
      port: 5001,
      apiPort: 5000,
      desktopToken: "t".repeat(43),
      sessionSecret: "s".repeat(43),
    });
    expect(env).toEqual({
      PATH: "/usr/bin",
      ELECTRON_RUN_AS_NODE: "1",
      NODE_ENV: "production",
      NO_COLOR: "1",
      HOST: "127.0.0.1",
      PORT: "5001",
      API_URL: "http://127.0.0.1:5000",
      HOMEFEED_MODE: "desktop",
      DESKTOP_TOKEN: "t".repeat(43),
      SESSION_SECRET: "s".repeat(43),
    });
  });
});

describe("desktopAuthUrl", () => {
  it("encodes the token and next path", () => {
    expect(desktopAuthUrl(5001, "a+b/c=")).toBe(
      "http://127.0.0.1:5001/desktop-auth?token=a%2Bb%2Fc%3D&next=%2F",
    );
  });
});
