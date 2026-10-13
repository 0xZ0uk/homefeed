import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { Info } from "lucide-react";
import { useId } from "react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "#/components/ui/popover";
import { breakdownTerms, formatScore } from "#/lib/breakdown";

/**
 * An info button for the top-right of a feed card's thumbnail. Hovering it
 * (or clicking, tapping, or pressing Enter/Space on it) opens a popover with
 * the item's one-line explanation and its full score breakdown; Escape or
 * moving away closes it. Like the card's menu, the button shows only on card
 * hover on devices that hover, and always on touch screens. Its parent must
 * be the card's `relative` thumbnail.
 */
export function WhyThisPopover({
  explanation,
  breakdown,
}: {
  explanation: string;
  breakdown: ScoreBreakdownOut;
}) {
  const headingId = useId();
  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={150}
        closeDelay={100}
        aria-label="Why this is here"
        className="absolute top-1.5 right-1.5 z-10 flex size-7 items-center justify-center rounded-full bg-black/70 text-white outline-none hover:bg-black/85 focus-visible:ring-3 focus-visible:ring-ring/50 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/card:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100 [@media(hover:hover)]:data-popup-open:opacity-100"
      >
        <Info aria-hidden="true" className="size-4" />
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        className="w-80 max-w-[calc(100vw-2rem)] gap-3 p-3"
      >
        <p className="text-sm">{explanation}</p>
        <section aria-labelledby={headingId}>
          <h4 id={headingId} className="mb-2 text-sm font-semibold">
            Score breakdown
          </h4>
          <BreakdownTable breakdown={breakdown} />
        </section>
      </PopoverContent>
    </Popover>
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
