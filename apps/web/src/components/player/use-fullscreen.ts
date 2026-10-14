import { useCallback, useSyncExternalStore, type RefObject } from "react";

function subscribe(onChange: () => void) {
  document.addEventListener("fullscreenchange", onChange);
  return () => document.removeEventListener("fullscreenchange", onChange);
}

/**
 * Fullscreen state of `ref`'s element (the player's container, so the controls
 * go fullscreen with the video) and a toggle for it.
 */
export function useFullscreen(ref: RefObject<HTMLElement | null>) {
  const isFullscreen = useSyncExternalStore(
    subscribe,
    () =>
      document.fullscreenElement !== null &&
      document.fullscreenElement === ref.current,
    () => false,
  );

  const toggle = useCallback(() => {
    // A refused request (e.g. not allowed by the embedding page) is not worth surfacing.
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    } else {
      void ref.current?.requestFullscreen?.().catch(() => {});
    }
  }, [ref]);

  return { isFullscreen, toggle };
}
