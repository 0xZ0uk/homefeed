import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { plural } from "#/lib/insights";
import { DISMISS_GROUP_LABEL } from "#/lib/dismiss";
import {
  SIGNAL_EFFECTS,
  describeRatedShare,
  dismissalReason,
  totalDismissals,
  type Taste,
} from "#/lib/taste";

/**
 * How Homefeed learns from you: your ratings, the "More like this" and "Less
 * like this" you gave, and what you dismissed lately. Each says how much, and
 * in a line what it does to the ranking.
 */
export function TasteSignals({ taste }: { taste: Taste }) {
  const { signals, days } = taste;
  const dismissed = totalDismissals(signals.dismissals);
  const ratedShare = describeRatedShare(signals.ratings, signals.watched);

  return (
    <section aria-labelledby="signals-heading" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="signals-heading" className="text-lg font-semibold">
          Signals
        </h2>
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          How Homefeed learns from you, beyond the topics and channels you set
          by hand. Counts are all-time, except for dismissals, which are those
          of the last {days} days.
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2">
        <Signal
          title="Ratings"
          value={signals.ratings}
          effect={SIGNAL_EFFECTS.ratings}
        >
          {signals.ratings === 0 ? (
            <>
              You haven't rated a video yet. Rate one from your{" "}
              <Link to="/" className={LINK}>
                feed
              </Link>{" "}
              or after you watch it.
            </>
          ) : (
            ratedShare
          )}
        </Signal>
        <Signal
          title="More like this"
          value={signals.more_like_this}
          effect={SIGNAL_EFFECTS.more}
        >
          {signals.more_like_this === 0 &&
            "Press “More like this” on a card in your feed to ask for videos like it."}
        </Signal>
        <Signal
          title="Less like this"
          value={signals.less_like_this}
          effect={SIGNAL_EFFECTS.less}
        >
          {signals.less_like_this === 0 &&
            "Press “Less like this” on a card to steer the feed away from videos like it."}
        </Signal>
        <Signal
          title={`Dismissed in the last ${days} days`}
          value={dismissed}
          effect={SIGNAL_EFFECTS.dismissals}
        >
          {dismissed === 0 ? (
            `Dismiss a video from its card's menu, under “${DISMISS_GROUP_LABEL}”.`
          ) : (
            <ul aria-label="Dismissals by reason" className="flex flex-col">
              {signals.dismissals.map(({ reason, count }) => (
                <li
                  key={reason ?? "none"}
                  className="flex justify-between gap-4"
                >
                  <span className="min-w-0 break-words">
                    {dismissalReason(reason)}
                  </span>
                  <span className="tabular-nums">
                    <span className="sr-only">{plural(count, "video")}</span>
                    <span aria-hidden="true">{count}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Signal>
      </ul>
    </section>
  );
}

const LINK =
  "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/** One signal: its name, how much of it there is, what to know about that
 * (`children`) and in a line what it does to the ranking. */
function Signal({
  title,
  value,
  effect,
  children,
}: {
  title: string;
  value: number;
  effect: string;
  children?: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border p-4">
      <h3 className="text-sm font-medium text-muted-foreground">{title}</h3>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {children ? <div className="text-sm">{children}</div> : null}
      <p className="text-sm text-muted-foreground">{effect}</p>
    </li>
  );
}
