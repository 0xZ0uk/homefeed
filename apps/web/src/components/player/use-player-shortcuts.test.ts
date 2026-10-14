import { describe, expect, it } from "vitest";

import {
  PLAYBACK_SPEEDS,
  isShortcutBlocked,
  shortcutAction,
  steppedSpeed,
  type ShortcutEvent,
} from "./use-player-shortcuts";

/** A fake element: only what the ignore rules read. */
function el(
  tagName: string,
  opts: { editable?: boolean; roles?: string[] } = {},
) {
  return {
    tagName,
    isContentEditable: opts.editable ?? false,
    closest: (selector: string) =>
      (opts.roles ?? []).some((role) => selector.includes(`[role="${role}"]`))
        ? {}
        : null,
  };
}

const BODY = el("BODY");
const PLAYER_BUTTON = el("DIV");
/** `inPlayer` for tests: only `PLAYER_BUTTON` is in the player. */
const inPlayer = (target: unknown) => target === PLAYER_BUTTON;

function press(key: string, extra: Partial<ShortcutEvent> = {}): ShortcutEvent {
  return {
    key,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    defaultPrevented: false,
    target: BODY,
    ...extra,
  };
}

describe("shortcutAction", () => {
  it("maps play/pause keys", () => {
    expect(shortcutAction(press("k"))).toEqual({ type: "toggle-play" });
    expect(shortcutAction(press("K"))).toEqual({ type: "toggle-play" });
    expect(shortcutAction(press(" "))).toEqual({ type: "toggle-play" });
  });

  it("maps seeking keys", () => {
    expect(shortcutAction(press("j"))).toEqual({
      type: "seek-by",
      seconds: -10,
    });
    expect(shortcutAction(press("l"))).toEqual({
      type: "seek-by",
      seconds: 10,
    });
    expect(shortcutAction(press("ArrowLeft"))).toEqual({
      type: "seek-by",
      seconds: -5,
    });
    expect(shortcutAction(press("ArrowRight"))).toEqual({
      type: "seek-by",
      seconds: 5,
    });
  });

  it("maps volume, mute, fullscreen and picture-in-picture", () => {
    expect(
      shortcutAction(press("ArrowUp", { target: PLAYER_BUTTON }), inPlayer),
    ).toEqual({
      type: "volume-by",
      delta: 0.05,
    });
    expect(
      shortcutAction(press("ArrowDown", { target: PLAYER_BUTTON }), inPlayer),
    ).toEqual({
      type: "volume-by",
      delta: -0.05,
    });
    expect(shortcutAction(press("m"))).toEqual({ type: "toggle-mute" });
    expect(shortcutAction(press("f"))).toEqual({ type: "toggle-fullscreen" });
    expect(shortcutAction(press("i"))).toEqual({ type: "toggle-pip" });
  });

  it("jumps to a tenth of the video on digits, and to either end", () => {
    expect(shortcutAction(press("0"))).toEqual({
      type: "seek-to-fraction",
      fraction: 0,
    });
    expect(shortcutAction(press("5"))).toEqual({
      type: "seek-to-fraction",
      fraction: 0.5,
    });
    expect(shortcutAction(press("9"))).toEqual({
      type: "seek-to-fraction",
      fraction: 0.9,
    });
    expect(
      shortcutAction(press("Home", { target: PLAYER_BUTTON }), inPlayer),
    ).toEqual({
      type: "seek-to-fraction",
      fraction: 0,
    });
    expect(
      shortcutAction(press("End", { target: PLAYER_BUTTON }), inPlayer),
    ).toEqual({
      type: "seek-to-fraction",
      fraction: 1,
    });
  });

  it("steps the speed with < and >", () => {
    expect(shortcutAction(press("<", { shiftKey: true }))).toEqual({
      type: "speed-step",
      direction: -1,
    });
    expect(shortcutAction(press(">", { shiftKey: true }))).toEqual({
      type: "speed-step",
      direction: 1,
    });
  });

  it("ignores other keys", () => {
    expect(shortcutAction(press("a"))).toBeNull();
    expect(shortcutAction(press("Enter"))).toBeNull();
    expect(shortcutAction(press("Tab"))).toBeNull();
    expect(shortcutAction(press("10"))).toBeNull();
  });

  it("ignores keys held with ctrl, meta or alt", () => {
    expect(shortcutAction(press("k", { ctrlKey: true }))).toBeNull();
    expect(shortcutAction(press("f", { metaKey: true }))).toBeNull();
    expect(shortcutAction(press("ArrowLeft", { altKey: true }))).toBeNull();
  });

  it("ignores events something else already handled", () => {
    expect(shortcutAction(press("k", { defaultPrevented: true }))).toBeNull();
  });

  it("ignores keys aimed at fields", () => {
    for (const tag of ["INPUT", "TEXTAREA", "SELECT"]) {
      expect(shortcutAction(press("k", { target: el(tag) }))).toBeNull();
    }
    expect(
      shortcutAction(press("k", { target: el("DIV", { editable: true }) })),
    ).toBeNull();
  });

  it("ignores keys inside menus, dialogs, sliders and other widgets", () => {
    for (const role of ["menu", "dialog", "slider", "radiogroup", "listbox"]) {
      const target = el("DIV", { roles: [role] });
      expect(shortcutAction(press("ArrowLeft", { target }))).toBeNull();
      expect(shortcutAction(press("k", { target }))).toBeNull();
    }
  });

  describe("scrolling keys", () => {
    const link = el("A");
    const insidePlayer = (target: unknown) => target === link;

    it("only Space works on the page itself", () => {
      expect(shortcutAction(press(" "))).toEqual({ type: "toggle-play" });
      for (const key of ["ArrowUp", "ArrowDown", "Home", "End"]) {
        expect(shortcutAction(press(key))).toBeNull();
      }
    });

    it("work for something inside the player", () => {
      const target = el("DIV");
      const inside = (t: unknown) => t === target;
      expect(shortcutAction(press(" ", { target }), inside)).toEqual({
        type: "toggle-play",
      });
      expect(
        shortcutAction(press("ArrowUp", { target }), inside),
      ).not.toBeNull();
    });

    it("are left alone for focus elsewhere on the page", () => {
      const target = el("DIV");
      for (const key of [" ", "ArrowUp", "ArrowDown", "Home", "End"]) {
        expect(shortcutAction(press(key, { target }))).toBeNull();
      }
      // Other keys still work from anywhere.
      expect(shortcutAction(press("k", { target }))).toEqual({
        type: "toggle-play",
      });
      expect(shortcutAction(press("ArrowLeft", { target }))).not.toBeNull();
    });

    it("leave Space to a focused button or link", () => {
      const button = el("BUTTON");
      expect(
        shortcutAction(press(" ", { target: button }), () => true),
      ).toBeNull();
      expect(
        shortcutAction(press(" ", { target: link }), insidePlayer),
      ).toBeNull();
      // But k still plays from a focused button.
      expect(shortcutAction(press("k", { target: button }))).toEqual({
        type: "toggle-play",
      });
    });
  });
});

describe("isShortcutBlocked", () => {
  it("is false without an element", () => {
    expect(isShortcutBlocked(null)).toBe(false);
    expect(isShortcutBlocked(undefined)).toBe(false);
  });
});

describe("steppedSpeed", () => {
  it("steps to the next speed up or down", () => {
    expect(steppedSpeed(1, 1)).toBe(1.25);
    expect(steppedSpeed(1, -1)).toBe(0.75);
    expect(steppedSpeed(0.25, 1)).toBe(0.5);
  });

  it("stops at the ends", () => {
    expect(steppedSpeed(2, 1)).toBe(2);
    expect(steppedSpeed(0.25, -1)).toBe(0.25);
  });

  it("steps from a speed that isn't in the list", () => {
    expect(steppedSpeed(1.1, 1)).toBe(1.25);
    expect(steppedSpeed(1.1, -1)).toBe(1);
  });

  it("only uses listed speeds", () => {
    expect(PLAYBACK_SPEEDS).toContain(steppedSpeed(1.6, 1));
  });
});
