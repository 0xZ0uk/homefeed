import { describe, expect, it } from "vitest";

import { apiErrorMessage } from "./api";

describe("apiErrorMessage", () => {
  it("uses a string detail", () => {
    expect(apiErrorMessage({ detail: "Not a channel URL" }, "fallback")).toBe(
      "Not a channel URL",
    );
  });

  it("falls back for anything else", () => {
    for (const error of [
      undefined,
      null,
      "oops",
      {},
      { detail: "" },
      { detail: [{ loc: ["body", "url"], msg: "Field required" }] },
    ]) {
      expect(apiErrorMessage(error, "fallback")).toBe("fallback");
    }
  });
});
