import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { RotatingLog } from "./log.js";

function tempDir(): string {
  return mkdtempSync(join(tmpdir(), "homefeed-log-"));
}

describe("RotatingLog", () => {
  it("appends to name.log, creating the directory", () => {
    const dir = join(tempDir(), "logs");
    const log = new RotatingLog(dir, "api");
    log.write("one\n");
    log.write(Buffer.from("two\n"));
    log.close();
    expect(readFileSync(join(dir, "api.log"), "utf8")).toBe("one\ntwo\n");
  });

  it("rotates past maxBytes, keeping `keep` old files", () => {
    const dir = tempDir();
    const log = new RotatingLog(dir, "web", 10, 2);
    for (const chunk of [
      "aaaaaaaa\n",
      "bbbbbbbb\n",
      "cccccccc\n",
      "dddddddd\n",
    ]) {
      log.write(chunk);
    }
    log.close();
    expect(readdirSync(dir).sort()).toEqual([
      "web.1.log",
      "web.2.log",
      "web.log",
    ]);
    expect(readFileSync(join(dir, "web.log"), "utf8")).toBe("dddddddd\n");
    expect(readFileSync(join(dir, "web.1.log"), "utf8")).toBe("cccccccc\n");
    expect(readFileSync(join(dir, "web.2.log"), "utf8")).toBe("bbbbbbbb\n");
  });

  it("counts an existing file's size towards the limit", () => {
    const dir = tempDir();
    writeFileSync(join(dir, "main.log"), "x".repeat(20));
    const log = new RotatingLog(dir, "main", 25, 1);
    log.write("0123456789");
    log.close();
    expect(readFileSync(join(dir, "main.log"), "utf8")).toBe("0123456789");
    expect(readFileSync(join(dir, "main.1.log"), "utf8")).toBe("x".repeat(20));
  });

  it("never splits a single oversized write into an empty rotation", () => {
    const dir = tempDir();
    const log = new RotatingLog(dir, "big", 4, 1);
    log.write("0123456789");
    log.close();
    expect(readFileSync(join(dir, "big.log"), "utf8")).toBe("0123456789");
    expect(existsSync(join(dir, "big.1.log"))).toBe(false);
  });

  it("writes timestamped lines", () => {
    const dir = tempDir();
    const log = new RotatingLog(dir, "main");
    log.line("hello");
    log.close();
    expect(readFileSync(join(dir, "main.log"), "utf8")).toMatch(
      /^\d{4}-\d\d-\d\dT[\d:.]+Z hello\n$/,
    );
  });
});
