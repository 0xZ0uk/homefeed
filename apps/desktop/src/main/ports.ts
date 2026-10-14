/** Free TCP ports on 127.0.0.1 for the API and web servers. */
import { createServer } from "node:net";

/** A port nothing listens on right now (the OS picks it; another process could still take it). */
export function findFreePort(host = "127.0.0.1"): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.on("error", reject);
    server.listen({ host, port: 0 }, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() =>
        port ? resolve(port) : reject(new Error("No port assigned")),
      );
    });
  });
}

/** `count` distinct free ports. */
export async function findFreePorts(
  count: number,
  host = "127.0.0.1",
): Promise<number[]> {
  const ports = new Set<number>();
  for (let attempt = 0; ports.size < count; attempt++) {
    if (attempt >= count * 10)
      throw new Error(`Could not find ${count} free ports`);
    ports.add(await findFreePort(host));
  }
  return [...ports];
}
