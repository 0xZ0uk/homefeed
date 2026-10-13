/**
 * A child server process (the API or the web server): spawned with its output going to a
 * log file, polled until it answers over HTTP, and stopped with its whole process tree.
 */
import { spawn, type ChildProcess } from "node:child_process";

import { killTree, killTreeSync, spawnDetached } from "./kill.js";
import type { RotatingLog } from "./log.js";
import type { Command } from "./paths.js";

export interface ServiceSpec extends Command {
  name: string;
  env: NodeJS.ProcessEnv;
  /** Polled until `isReady` accepts the response. */
  readyUrl: string;
  isReady: (response: Response) => boolean;
  /** Secrets to mask in the log (srvx logs request URLs, and /desktop-auth has the token). */
  redact?: string[];
}

export class Service {
  private child: ChildProcess | null = null;
  private exited: Promise<void> = Promise.resolve();
  private stopping = false;

  /** Called when the process exits without `stop()` having been asked for. */
  onCrash: (code: number | null, signal: NodeJS.Signals | null) => void =
    () => {};

  constructor(
    readonly spec: ServiceSpec,
    private readonly log: RotatingLog,
  ) {}

  get running(): boolean {
    return this.child !== null;
  }

  start(): void {
    if (this.child) return;
    const { spec, log } = this;
    this.stopping = false;
    log.line(
      `--- starting ${spec.name}: ${spec.command} ${spec.args.join(" ")} (cwd ${spec.cwd})`,
    );
    const child = spawn(spec.command, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: spawnDetached(process.platform),
      windowsHide: true,
    });
    this.child = child;
    const write = (chunk: Buffer) => log.write(redact(chunk, spec.redact));
    child.stdout?.on("data", write);
    child.stderr?.on("data", write);
    this.exited = new Promise((resolve) => {
      child.on("error", (error) => {
        log.line(`--- ${spec.name} failed to start: ${error.message}`);
        if (this.child === child) this.child = null;
        resolve();
        if (!this.stopping) this.onCrash(null, null);
      });
      child.on("exit", (code, signal) => {
        log.line(`--- ${spec.name} exited (code ${code}, signal ${signal})`);
        if (this.child === child) this.child = null;
        resolve();
        if (!this.stopping) this.onCrash(code, signal);
      });
    });
  }

  /**
   * Resolves once the service answers; rejects when it exits first, after `timeoutMs`, or
   * when `signal` aborts.
   */
  async waitUntilReady(timeoutMs: number, signal?: AbortSignal): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    let exited = false;
    void this.exited.then(() => (exited = true));
    while (true) {
      signal?.throwIfAborted();
      if (exited || !this.child)
        throw new Error(`${this.spec.name} exited while starting`);
      try {
        const response = await fetch(this.spec.readyUrl, {
          signal: AbortSignal.timeout(2000),
          redirect: "manual",
        });
        await response.body?.cancel();
        if (this.spec.isReady(response)) return;
      } catch {
        // Not listening yet.
      }
      if (Date.now() > deadline) {
        throw new Error(
          `${this.spec.name} didn't start within ${timeoutMs / 1000}s`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }

  async stop(): Promise<void> {
    const child = this.child;
    this.stopping = true;
    if (!child?.pid) return;
    this.log.line(`--- stopping ${this.spec.name} (pid ${child.pid})`);
    await killTree(child.pid, this.exited);
  }

  /** For `process.on("exit")`: no waiting possible. */
  killSync(): void {
    this.stopping = true;
    if (this.child?.pid) killTreeSync(this.child.pid);
  }
}

export function redact(chunk: Buffer, secrets: string[] = []): Buffer | string {
  if (secrets.length === 0) return chunk;
  let text = chunk.toString();
  for (const secret of secrets)
    if (secret) text = text.replaceAll(secret, "<redacted>");
  return text;
}

/** At most `maxRestarts` restarts per `windowMs`, so a crash loop ends in the error window. */
export class RestartPolicy {
  private restarts: number[] = [];

  constructor(
    readonly maxRestarts = 3,
    readonly windowMs = 10 * 60 * 1000,
  ) {}

  /** Whether another restart is allowed now; records it if so. */
  tryRestart(now = Date.now()): boolean {
    this.restarts = this.restarts.filter((time) => now - time < this.windowMs);
    if (this.restarts.length >= this.maxRestarts) return false;
    this.restarts.push(now);
    return true;
  }

  reset(): void {
    this.restarts = [];
  }
}
