import { describe, expect, it } from "vitest";

import { classifyUrl } from "./urls.js";

const origin = "http://127.0.0.1:5001";

describe("classifyUrl", () => {
  it("keeps same-origin URLs in the app", () => {
    expect(classifyUrl("http://127.0.0.1:5001/watch/abc?t=1", origin)).toBe(
      "app",
    );
    expect(classifyUrl("http://127.0.0.1:5001", origin)).toBe("app");
  });

  it("sends web and mail links to the default browser", () => {
    expect(
      classifyUrl("https://www.youtube.com/watch?v=dQw4w9WgXcQ", origin),
    ).toBe("external");
    expect(classifyUrl("http://example.com/", origin)).toBe("external");
    expect(classifyUrl("mailto:someone@example.com", origin)).toBe("external");
  });

  it("treats other ports and hosts as external, not as the app", () => {
    expect(classifyUrl("http://127.0.0.1:5000/health", origin)).toBe(
      "external",
    );
    expect(classifyUrl("http://localhost:5001/", origin)).toBe("external");
  });

  it("blocks other schemes and garbage", () => {
    expect(classifyUrl("file:///etc/passwd", origin)).toBe("blocked");
    expect(classifyUrl("javascript:alert(1)", origin)).toBe("blocked");
    expect(classifyUrl("vscode://open", origin)).toBe("blocked");
    expect(classifyUrl("not a url", origin)).toBe("blocked");
  });

  it("matches nothing before the app's origin is known", () => {
    expect(classifyUrl("http://127.0.0.1:5001/", "")).toBe("external");
  });
});
