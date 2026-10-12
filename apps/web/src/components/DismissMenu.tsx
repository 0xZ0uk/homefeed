import { useEffect, useId, useRef, useState } from "react";

import { DISMISS_REASONS } from "#/lib/dismiss";

/**
 * A "Dismiss" button that opens a small menu of reasons, plus "No reason".
 * Picking one calls `onDismiss`. A disclosure like the score breakdown: the
 * button reports `aria-expanded`, the choices follow it in the tab order, and
 * Escape or a click elsewhere closes it.
 */
export function DismissMenu({
  title,
  disabled = false,
  onDismiss,
}: {
  /** The video's title, for the button's accessible name. */
  title: string;
  disabled?: boolean;
  onDismiss: (reason: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const headingId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (rootRef.current?.contains(document.activeElement)) {
        buttonRef.current?.focus();
      }
      setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function choose(reason: string | null) {
    setOpen(false);
    onDismiss(reason);
  }

  const choiceClass =
    "w-full rounded px-2 py-1 text-left hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-blue-600";

  return (
    <div ref={rootRef} className="relative shrink-0">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="rounded px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 disabled:opacity-50"
      >
        Dismiss<span className="sr-only"> {title}</span>
      </button>
      <section
        id={panelId}
        aria-labelledby={headingId}
        hidden={!open}
        className="absolute top-full right-0 z-10 mt-1 w-48 rounded border bg-white p-2 text-sm text-gray-800 shadow-lg"
      >
        <h4 id={headingId} className="mb-1 px-2 text-xs font-semibold">
          Why dismiss it?
        </h4>
        <ul className="flex flex-col">
          {DISMISS_REASONS.map((reason) => (
            <li key={reason}>
              <button
                type="button"
                className={choiceClass}
                onClick={() => choose(reason)}
              >
                {reason}
              </button>
            </li>
          ))}
          <li className="mt-1 border-t pt-1">
            <button
              type="button"
              className={`${choiceClass} text-gray-600`}
              onClick={() => choose(null)}
            >
              No reason
            </button>
          </li>
        </ul>
      </section>
    </div>
  );
}
