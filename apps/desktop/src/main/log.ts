/**
 * Log files with simple size-based rotation: once `name.log` would pass `maxBytes`, it
 * becomes `name.1.log` (older ones shift up, the oldest past `keep` is deleted).
 */
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  renameSync,
  rmSync,
  statSync,
  writeSync,
} from "node:fs";
import { join } from "node:path";

export const DEFAULT_MAX_BYTES = 5 * 1024 * 1024;

export class RotatingLog {
  readonly path: string;
  private fd: number | null = null;
  private size = 0;

  constructor(
    readonly dir: string,
    readonly name: string,
    readonly maxBytes = DEFAULT_MAX_BYTES,
    readonly keep = 2,
  ) {
    this.path = join(dir, `${name}.log`);
  }

  write(chunk: string | Uint8Array): void {
    const data = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
    if (this.fd === null) this.open();
    if (this.size > 0 && this.size + data.length > this.maxBytes) {
      this.rotate();
      this.open();
    }
    try {
      writeSync(this.fd!, data);
      this.size += data.length;
    } catch {
      // Logging must never take the app down (disk full, file removed under us...).
    }
  }

  /** A timestamped line. */
  line(message: string): void {
    this.write(`${new Date().toISOString()} ${message}\n`);
  }

  close(): void {
    if (this.fd !== null) closeSync(this.fd);
    this.fd = null;
  }

  private open(): void {
    mkdirSync(this.dir, { recursive: true });
    this.fd = openSync(this.path, "a");
    this.size = statSync(this.path).size;
  }

  private rotate(): void {
    this.close();
    const rotated = (n: number) => join(this.dir, `${this.name}.${n}.log`);
    rmSync(rotated(this.keep), { force: true });
    for (let n = this.keep - 1; n >= 1; n--) {
      if (existsSync(rotated(n))) renameSync(rotated(n), rotated(n + 1));
    }
    if (this.keep >= 1) renameSync(this.path, rotated(1));
    else rmSync(this.path, { force: true });
  }
}
