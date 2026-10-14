/** Which URLs the main window may load, and which go to the default browser. */

export type UrlKind = "app" | "external" | "blocked";

const EXTERNAL_PROTOCOLS = new Set(["http:", "https:", "mailto:"]);

/**
 * `app`: same origin as the web server (load it in the window); `external`: a web or mail
 * link (open it with `shell.openExternal`); `blocked`: anything else (file:, javascript:,
 * custom schemes, unparsable).
 */
export function classifyUrl(url: string, appOrigin: string): UrlKind {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "blocked";
  }
  if (parsed.origin === appOrigin) return "app";
  return EXTERNAL_PROTOCOLS.has(parsed.protocol) ? "external" : "blocked";
}
