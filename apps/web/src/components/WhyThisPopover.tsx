import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { useEffect, useId, useRef, useState } from "react";

import { breakdownTerms, formatScore } from "#/lib/breakdown";

/**
 * A feed item's one-line explanation, as a button that opens its full score
 * breakdown below it. A disclosure: the button reports `aria-expanded` and
 * controls the panel, which follows it in the tab order. Escape closes the
 * panel (returning focus to the button if it was inside), as does a click
 * anywhere else.
 */
export function WhyThisPopover({
  explanation,
  breakdown,
}: {
  explanation: string;
  breakdown: ScoreBreakdownOut;
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

  return (
    <div ref={rootRef} className="relative min-w-0">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="rounded text-left underline decoration-dotted underline-offset-2 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <span className="sr-only">Why this is here: </span>
        {explanation}
        <span aria-hidden="true" className="ml-1 inline-block text-xs">
          {open ? "▴" : "▾"}
        </span>
      </button>
      <section
        id={panelId}
        aria-labelledby={headingId}
        hidden={!open}
        className="absolute top-full left-0 z-20 mt-1 w-80 max-w-[calc(100vw-2rem)] rounded-xl bg-popover p-3 text-sm text-popover-foreground shadow-lg ring-1 ring-foreground/10"
      >
        <h4 id={headingId} className="mb-2 text-sm font-semibold">
          Score breakdown
        </h4>
        <BreakdownTable breakdown={breakdown} />
      </section>
    </div>
  );
}

function BreakdownTable({ breakdown }: { breakdown: ScoreBreakdownOut }) {
  return (
    <table className="w-full text-sm">
      <thead className="sr-only">
        <tr>
          <th scope="col">Term</th>
          <th scope="col">Points</th>
        </tr>
      </thead>
      <tbody>
        {breakdownTerms(breakdown).map((term) => (
          <tr key={term.key} className="align-top">
            <th scope="row" className="py-0.5 pr-3 text-left font-normal">
              {term.label}
              {term.detail && (
                <span className="block text-xs text-muted-foreground">
                  {term.detail}
                </span>
              )}
            </th>
            <td className="py-0.5 text-right tabular-nums">
              {formatScore(term.value)}
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="border-t font-medium">
          <th scope="row" className="pt-1 pr-3 text-left">
            Score
          </th>
          <td className="pt-1 text-right tabular-nums">
            {formatScore(breakdown.final)}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
