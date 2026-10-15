import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { Info } from "lucide-react";
import { useId, type ReactNode } from "react";

import { Button } from "#/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import {
  breakdownTerms,
  formatScore,
  scoreDirection,
  type ScoreDirection,
} from "#/lib/breakdown";
import { cn } from "#/lib/utils";

/**
 * The (i) button on a card's thumbnail. Pointing at it, or pressing it (click,
 * tap, or Enter or Space on it), opens a popover with why the video is here
 * (`children`, the reason as the card puts it) and, when there is one, the
 * score breakdown: how the item's score was made, each term green when it
 * adds and red when it takes away. The popover stays open while the pointer
 * is on it; Escape or clicking away closes it. The button is raised above the
 * card's stretched link so it can be pressed, and its name carries the whole
 * reason, so a screen reader hears it without opening anything.
 */
export function WhyThisPopover({
  title,
  explanation,
  breakdown,
  className,
  children,
}: {
  /** The video's title, to tell this card's button from the others'. */
  title: string;
  explanation: string;
  breakdown?: ScoreBreakdownOut;
  className?: string;
  /** The reason as the popover shows it. */
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={200}
        closeDelay={150}
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            className={cn(
              "relative z-10 bg-black/80 text-white hover:bg-black hover:text-white aria-expanded:bg-black aria-expanded:text-white dark:hover:bg-black",
              className,
            )}
          />
        }
      >
        <Info aria-hidden="true" className="size-4.5" />
        <span className="sr-only">
          Why this is here: {explanation}, for {title}
        </span>
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        className="w-80 max-w-[calc(100vw-2rem)] gap-3 p-3 motion-reduce:data-open:animate-none motion-reduce:data-closed:animate-none"
      >
        {/* An h3 like the card titles, so the breakdown's h4 follows it in order. */}
        <PopoverTitle render={<h3 />} className="text-sm font-semibold">
          Why this is here
        </PopoverTitle>
        <p className="flex items-start gap-2 text-sm leading-snug">
          {children}
        </p>
        {breakdown && (
          <section aria-labelledby={headingId}>
            <h4
              id={headingId}
              className="mb-1.5 text-xs font-medium tracking-[0.05em] text-muted-foreground uppercase"
            >
              Score breakdown
            </h4>
            <BreakdownTable breakdown={breakdown} />
          </section>
        )}
      </PopoverContent>
    </Popover>
  );
}

/**
 * How a term's points read: green when they add to the score, red when they
 * take from it (the sign says so too), and a term that changes nothing is
 * greyed, label and all, so the ones that count stand out.
 */
const DIRECTION: Record<ScoreDirection, string> = {
  up: "font-medium text-score-up",
  down: "font-medium text-score-down",
  none: "text-muted-foreground",
};

function BreakdownTable({ breakdown }: { breakdown: ScoreBreakdownOut }) {
  const total = scoreDirection(breakdown.final);
  return (
    <table className="w-full text-sm">
      <thead className="sr-only">
        <tr>
          <th scope="col">Term</th>
          <th scope="col">Points</th>
        </tr>
      </thead>
      <tbody>
        {breakdownTerms(breakdown).map((term) => {
          const direction = scoreDirection(term.value);
          return (
            <tr key={term.key} className="align-top">
              <th
                scope="row"
                className={cn(
                  "py-0.5 pe-3 text-start font-normal",
                  direction === "none" && "text-muted-foreground",
                )}
              >
                {term.label}
                {term.detail && (
                  <span className="block text-xs text-muted-foreground">
                    {term.detail}
                  </span>
                )}
              </th>
              <td
                className={cn(
                  "py-0.5 text-end tabular-nums",
                  DIRECTION[direction],
                )}
              >
                {formatScore(term.value)}
              </td>
            </tr>
          );
        })}
      </tbody>
      <tfoot>
        <tr className="border-t font-semibold">
          <th scope="row" className="pt-1.5 pe-3 text-start">
            Score
          </th>
          <td
            className={cn(
              "pt-1.5 text-end tabular-nums",
              total !== "none" && DIRECTION[total],
              "font-semibold",
            )}
          >
            {formatScore(breakdown.final)}
          </td>
        </tr>
      </tfoot>
    </table>
  );
}
