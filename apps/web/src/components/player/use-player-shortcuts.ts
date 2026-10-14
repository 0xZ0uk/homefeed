import { useEffect, useRef, type RefObject } from "react";

/** Speeds the settings menu offers, and `<` / `>` step through. */
export const PLAYBACK_SPEEDS = [
  0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2,
] as const;

/** Seconds the arrow keys seek by; `j` and `l` seek by twice that. */
export const SEEK_STEP = 5;
const LONG_SEEK_STEP = 10;
const VOLUME_STEP = 0.05;

/** What a key press asks the player to do. */
export type PlayerAction =
  | { type: "toggle-play" }
  | { type: "seek-by"; seconds: number }
  | { type: "seek-to-fraction"; fraction: number }
  | { type: "volume-by"; delta: number }
  | { type: "toggle-mute" }
  | { type: "toggle-fullscreen" }
  | { type: "toggle-pip" }
  | { type: "speed-step"; direction: 1 | -1 };

/** The slice of a `KeyboardEvent` the key mapping reads. */
export interface ShortcutEvent {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  defaultPrevented: boolean;
  target: unknown;
}

/** The slice of an `Element` the ignore rules read. */
interface TargetLike {
  tagName?: string;
  isContentEditable?: boolean;
  closest?: (selector: string) => unknown;
}

const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);
/** Widgets that own the arrow, Home/End and Space keys themselves. */
const OWNING_ROLES =
  '[role="menu"],[role="dialog"],[role="slider"],[role="radiogroup"],[role="listbox"]';
/** Keys that scroll the page, so they're only taken while focus is in the
 * player (Space also with nothing focused, like YouTube). */
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "Home", "End"]);

function asTarget(target: unknown): TargetLike | null {
  return typeof target === "object" && target !== null
    ? (target as TargetLike)
    : null;
}

/** Whether `target` is somewhere keys belong to: a field, menu, dialog or slider. */
export function isShortcutBlocked(target: unknown): boolean {
  const el = asTarget(target);
  if (!el) return false;
  if (el.isContentEditable) return true;
  if (el.tagName && EDITABLE_TAGS.has(el.tagName.toUpperCase())) return true;
  return Boolean(el.closest?.(OWNING_ROLES));
}

/** Whether `target` is the page itself (nothing focused) or inside the player. */
function inPlayScope(target: unknown, inPlayer: (target: unknown) => boolean) {
  const el = asTarget(target);
  if (!el) return true;
  return el.tagName?.toUpperCase() === "BODY" || inPlayer(target);
}

/** Whether `target` is a button, link or anything else Space or Enter activates. */
function isActivatable(target: unknown): boolean {
  const el = asTarget(target);
  if (!el) return false;
  const tag = el.tagName?.toUpperCase();
  return tag === "BUTTON" || tag === "A" || Boolean(el.closest?.("button,a"));
}

/**
 * The action a key press asks for, or null to leave it alone.
 *
 * Modified keys, handled events and keys aimed at fields, menus, dialogs and
 * sliders are left alone. Keys that would scroll the page are only taken when
 * focus is in the player, which `inPlayer` tells (Space also when nothing is
 * focused). Space on a focused button is left for the button.
 */
export function shortcutAction(
  event: ShortcutEvent,
  inPlayer: (target: unknown) => boolean = () => false,
): PlayerAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.defaultPrevented) return null;
  if (isShortcutBlocked(event.target)) return null;
  if (event.key === " " && !inPlayScope(event.target, inPlayer)) return null;
  if (SCROLL_KEYS.has(event.key) && !inPlayer(event.target)) return null;

  switch (event.key) {
    case " ":
      return isActivatable(event.target) ? null : { type: "toggle-play" };
    case "ArrowLeft":
      return { type: "seek-by", seconds: -SEEK_STEP };
    case "ArrowRight":
      return { type: "seek-by", seconds: SEEK_STEP };
    case "ArrowUp":
      return { type: "volume-by", delta: VOLUME_STEP };
    case "ArrowDown":
      return { type: "volume-by", delta: -VOLUME_STEP };
    case "Home":
      return { type: "seek-to-fraction", fraction: 0 };
    case "End":
      return { type: "seek-to-fraction", fraction: 1 };
    case "<":
      return { type: "speed-step", direction: -1 };
    case ">":
      return { type: "speed-step", direction: 1 };
  }

  if (event.key.length === 1 && event.key >= "0" && event.key <= "9") {
    return { type: "seek-to-fraction", fraction: Number(event.key) / 10 };
  }
  switch (event.key.toLowerCase()) {
    case "k":
      return { type: "toggle-play" };
    case "j":
      return { type: "seek-by", seconds: -LONG_SEEK_STEP };
    case "l":
      return { type: "seek-by", seconds: LONG_SEEK_STEP };
    case "m":
      return { type: "toggle-mute" };
    case "f":
      return { type: "toggle-fullscreen" };
    case "i":
      return { type: "toggle-pip" };
  }
  return null;
}

/** The speed one step from `current` through {@link PLAYBACK_SPEEDS}, clamped. */
export function steppedSpeed(current: number, direction: 1 | -1): number {
  const speeds = PLAYBACK_SPEEDS;
  if (direction === 1) {
    return speeds.find((speed) => speed > current) ?? Math.max(...speeds);
  }
  return (
    [...speeds].reverse().find((speed) => speed < current) ??
    Math.min(...speeds)
  );
}

/** Plays when paused (or ended, from the start), pauses when playing. */
export function togglePlayback(media: HTMLMediaElement) {
  if (media.paused || media.ended) {
    // A refused play (e.g. no source yet) is not worth surfacing.
    void media.play().catch(() => {});
  } else {
    media.pause();
  }
}

/** Seeks to `time`, kept inside the video. */
export function seekTo(media: HTMLMediaElement, time: number) {
  const duration = Number.isFinite(media.duration) ? media.duration : Infinity;
  media.currentTime = Math.min(Math.max(time, 0), duration);
}

/** Enters or leaves picture-in-picture, where the browser has it. */
export function togglePictureInPicture(media: HTMLVideoElement) {
  if (!document.pictureInPictureEnabled) return;
  const request =
    document.pictureInPictureElement === media
      ? document.exitPictureInPicture()
      : media.requestPictureInPicture();
  void request.catch(() => {});
}

/** Sets the volume (0 to 1); zero counts as muted. */
export function setVolume(media: HTMLMediaElement, volume: number) {
  media.volume = volume;
  media.muted = volume === 0;
}

/** Mutes, or unmutes (to an audible level if the volume was left at zero). */
export function toggleMute(media: HTMLMediaElement) {
  if (media.muted && media.volume === 0) media.volume = 0.5;
  media.muted = !media.muted;
}

/** Sets the playback speed. */
export function setPlaybackRate(media: HTMLMediaElement, rate: number) {
  media.playbackRate = rate;
}

function volumeBy(media: HTMLMediaElement, delta: number) {
  // Quieter while muted stays muted; louder unmutes at the remembered volume plus the step.
  if (media.muted && delta < 0) return;
  const volume =
    Math.round(Math.min(Math.max(media.volume + delta, 0), 1) * 100) / 100;
  setVolume(media, volume);
}

interface ShortcutOptions {
  media: HTMLVideoElement | null;
  toggleFullscreen: () => void;
  /** The player's container; Space and the scrolling keys work inside it. */
  containerRef?: RefObject<HTMLElement | null>;
  /** Called after a shortcut ran, e.g. to bring the controls back. */
  onAction?: (action: PlayerAction) => void;
}

/** Keyboard shortcuts for the player, on one `keydown` listener on the document. */
export function usePlayerShortcuts({
  media,
  toggleFullscreen,
  containerRef,
  onAction,
}: ShortcutOptions) {
  // The listener reads the latest props without re-attaching.
  const latest = useRef({ toggleFullscreen, onAction });
  useEffect(() => {
    latest.current = { toggleFullscreen, onAction };
  });

  useEffect(() => {
    if (!media) return;

    const inPlayer = (target: unknown) =>
      target instanceof Node &&
      Boolean(containerRef?.current?.contains(target));

    const onKeyDown = (event: KeyboardEvent) => {
      const action = shortcutAction(event, inPlayer);
      if (!action) return;
      event.preventDefault();

      switch (action.type) {
        case "toggle-play":
          togglePlayback(media);
          break;
        case "seek-by":
          seekTo(media, media.currentTime + action.seconds);
          break;
        case "seek-to-fraction":
          if (Number.isFinite(media.duration)) {
            seekTo(media, media.duration * action.fraction);
          }
          break;
        case "volume-by":
          volumeBy(media, action.delta);
          break;
        case "toggle-mute":
          toggleMute(media);
          break;
        case "toggle-fullscreen":
          latest.current.toggleFullscreen();
          break;
        case "toggle-pip":
          togglePictureInPicture(media);
          break;
        case "speed-step":
          media.playbackRate = steppedSpeed(
            media.playbackRate,
            action.direction,
          );
          break;
      }
      latest.current.onAction?.(action);
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [media, containerRef]);
}
