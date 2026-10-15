import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { useId } from "react";

import { Button } from "#/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import { breakdownTerms, formatScore } from "#/lib/breakdown";

/**
 * The "Details" button beside a card's reason. Pressing it (click, tap, or
 * Enter or Space on it) opens a popover with the whole reason and the score
 * breakdown, how the item's score was made; Escape or clicking away closes
 * it. The button is raised above the card's stretched link so it can be
 * pressed, and names the video for screen readers.
 */
export function WhyThisPopover({
  title,
  explanation,
  breakdown,
}: {
  /** The video's title, to tell this card's button from the others'. */
  title: string;
  explanation: string;
  breakdown: ScoreBreakdownOut;
}) {
  const headingId = useId();
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            className="relative z-10 -my-0.5 shrink-0 px-2"
          />
        }
      >
        Details<span className="sr-only"> for {title}</span>
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
