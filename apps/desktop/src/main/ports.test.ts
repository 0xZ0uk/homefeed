import { createServer } from "node:net";

import { describe, expect, it } from "vitest";

import { findFreePort, findFreePorts } from "./ports.js";

function listen(port: number): Promise<() => Promise<void>> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on("error", reject);
    server.listen({ host: "127.0.0.1", port }, () =>
      resolve(() => new Promise((done) => server.close(() => done()))),
    );
  });
}

describe("findFreePort", () => {
  it("returns a port that can be listened on", async () => {
    const port = await findFreePort();
    expect(port).toBeGreaterThan(0);
    const close = await listen(port);
    await close();
  });
});

describe("findFreePorts", () => {
  it("returns distinct ports", async () => {
    const ports = await findFreePorts(2);
    expect(ports).toHaveLength(2);
    expect(new Set(ports).size).toBe(2);
  });
});
