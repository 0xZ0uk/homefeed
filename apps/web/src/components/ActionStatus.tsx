import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import { Button } from "#/components/ui/button";
import type { ActionStatus } from "#/lib/card-actions";
import { cn } from "#/lib/utils";

/** How long a status stays, unless someone is using it. */
const STATUS_MS = 10_000;
/** How long to wait before looking again at a status that was in use. */
const RECHECK_MS = 1_000;
/** The frames to wait for a menu closing with the same press to let go of focus. */
const FOCUS_WAIT_FRAMES = 20;

/**
 * Whether someone is using the status line: the pointer is on its button, or
 * keyboard focus is in it. Looked at when the status is due to go, rather than
 * kept up to date from events, which a removed button (the one just pressed)
 * doesn't always send. Focus counts when it shows (`:focus-visible`), so that
 * a mouse user whose focus was moved there for them isn't kept waiting.
 */
function inUse(line: HTMLElement | null): boolean {
  if (!line) return false;
  return (
    line.matches(":hover, :focus-visible") ||
    line.querySelector(":focus-visible") !== null
  );
}

/**
 * Focuses `element` once nothing else has focus. A menu closing as the press
 * that caused the status is handled takes focus back as it goes (and a modal
 * one pulls it back while it is open), so focusing at once would be undone.
 * Gives up waiting after a few frames.
 */
function takeFocus(element: HTMLElement) {
  let frames = 0;
  const attempt = () => {
    const active = document.activeElement;
    if (!active || active === document.body || frames++ >= FOCUS_WAIT_FRAMES) {
      element.focus({ preventScroll: true });
    } else {
      requestAnimationFrame(attempt);
    }
  };
  requestAnimationFrame(attempt);
}

/**
 * The outcome of the last quick action on a card, and the line that shows it
 * (see `ActionStatusLine`). `announce` replaces the status, and moves focus to
 * the line when the status asks for it, e.g. because the card the focused
 * control was on is gone (see `takeFocus`).
 *
 * A status goes after a few seconds, but not while it is being used (see
 * `inUse`, so an Undo can be reached), and each new one gets its full time.
 */
export function useActionStatus() {
  const [status, setStatus] = useState<ActionStatus | null>(null);
  const ref = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (!status) return;
    let timer = window.setTimeout(function check() {
      if (inUse(ref.current)) timer = window.setTimeout(check, RECHECK_MS);
      else setStatus(null);
    }, STATUS_MS);
    return () => window.clearTimeout(timer);
  }, [status]);

  const announce = useCallback((next: ActionStatus) => {
    setStatus(next);
    if (next.focus && ref.current) takeFocus(ref.current);
  }, []);
  return { status, announce, ref };
}

/**
 * A polite status line for what a card's action did, with an "Undo" button
 * when it can be undone, shown as a small floating panel: the caller places
 * it (e.g. absolutely, under a sticky bar) so that it needs no room and is in
 * view wherever the page is scrolled to. Pointer clicks pass through the panel
 * to the cards under it (only its button takes them), so it never covers the
 * buttons of the card that was just used. It is on the page, empty, from the
 * start so that a screen reader announces what appears in it; until then it is
 * visually hidden rather than removed, which would silence it. It can take
 * focus (hence the ring).
 */
export function ActionStatusLine({
  status,
  statusRef,
  className,
}: {
  status: ActionStatus | null;
  statusRef: RefObject<HTMLParagraphElement | null>;
  className?: string;
}) {
  return (
    <p
      ref={statusRef}
      role="status"
      tabIndex={-1}
      className={cn(
        "pointer-events-none flex w-fit flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-none focus-visible:ring-3 focus-visible:ring-ring empty:sr-only",
        className,
      )}
    >
      {status && (
        <>
          <span className={status.ok ? undefined : "text-destructive"}>
            {status.message}
          </span>
          {status.undo && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={status.undo}
              className="pointer-events-auto"
            >
              Undo
            </Button>
          )}
        </>
      )}
    </p>
  );
}
