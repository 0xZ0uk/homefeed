import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";

import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import { breakdownTerms, formatScore } from "#/lib/breakdown";
import { cn } from "#/lib/utils";

/**
 * The look of a card's reason: a soft panel, so it reads as one thing (and,
 * when it opens the breakdown, as a control) rather than loose text.
 */
export const REASON =
  "flex w-full items-start gap-2 rounded-lg bg-secondary/60 px-2.5 py-2 text-start text-sm leading-snug";

/**
 * A card's reason (`children`) as a button: pressing it (click, tap, or Enter
 * or Space on it) opens a popover with the whole reason and the score
 * breakdown, how the item's score was made; Escape or clicking away closes
 * it. A chevron says it opens. The button is raised above the card's
 * stretched link so it can be pressed, and names the video for screen
 * readers.
 */
export function WhyThisPopover({
  title,
  explanation,
  breakdown,
  children,
}: {
  /** The video's title, to tell this card's button from the others'. */
  title: string;
  explanation: string;
  breakdown: ScoreBreakdownOut;
  /** The reason as the card shows it. */
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <Popover>
      <PopoverTrigger
        className={cn(
          REASON,
          "relative z-10 border border-transparent pe-1.5 outline-none hover:bg-secondary focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 aria-expanded:bg-secondary",
        )}
      >
        <span className="sr-only">Why this is here: </span>
        {children}
        <span className="sr-only">, for {title}</span>
        <ChevronRight
          aria-hidden="true"
          className="mt-px size-4 shrink-0 text-muted-foreground rtl:-scale-x-100"
        />
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="start"
        className="w-80 max-w-[calc(100vw-2rem)] gap-3 p-3 motion-reduce:data-open:animate-none motion-reduce:data-closed:animate-none"
      >
        {/* An h3 like the card titles, so the breakdown's h4 follows it in order. */}
        <PopoverTitle render={<h3 />} className="text-sm font-semibold">
          Why this is here
        </PopoverTitle>
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
