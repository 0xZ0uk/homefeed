import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { SlidersHorizontal } from "lucide-react";
import { useId, useState } from "react";

import { MixDial } from "#/components/MixDial";
import { RefreshFeedButton } from "#/components/RefreshFeedButton";
import { TopicWeights } from "#/components/TopicWeights";
import { Button } from "#/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "#/components/ui/popover";
import { undismissedItems } from "#/lib/dismiss";
import {
  MIX_TOPICS,
  currentMix,
  mixLabel,
  topicCounts,
  type TopicCount,
} from "#/lib/feed-mix";
import { cn } from "#/lib/utils";
import type { Feed } from "#/server/feeds";
import { settingsQuery } from "#/server/settings";

/**
 * Under Today's header: what today's picks are about, as the five topics most
 * of the undismissed ones carry (each a link to the tag's page, with how many
 * picks carry it), the mix the next feed will be built with, and a "Rebalance"
 * button. The button opens a popover to change that mix and the boost of each
 * topic I follow; both only count from the next feed, which the popover says,
 * with a way to build it now.
 */
export function MixStrip({ feed }: { feed: Feed }) {
  const headingId = useId();
  const counts = topicCounts(undismissedItems(feed.items));
  const { data: settings } = useQuery(settingsQuery);

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-wrap items-center gap-x-4 gap-y-2"
    >
      <h2 id={headingId} className="text-sm font-medium">
        Topics today
      </h2>
      {counts.length > 0 ? (
        <ul aria-label="Top topics today" className="flex flex-wrap gap-2">
          {counts.slice(0, MIX_TOPICS).map((topic) => (
            <li key={topic.slug} className="min-w-0">
              <TopicChip topic={topic} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          No topics yet: videos get them once they've been analysed.
        </p>
      )}
      <div className="flex items-center gap-3 sm:ml-auto">
        {settings && (
          <p className="text-sm text-muted-foreground">
            Mix:{" "}
            <span className="font-medium text-foreground">
              {mixLabel(currentMix(settings.values))}
            </span>
          </p>
        )}
        <Rebalance feedId={feed.id} counts={counts} />
      </div>
    </section>
  );
}

/** A topic and how many picks carry it, as a link to the tag's page. */
function TopicChip({ topic }: { topic: TopicCount }) {
  return (
    <Link
      to="/tags/$slug"
      params={{ slug: topic.slug }}
      className="flex h-8 max-w-full items-center gap-2 rounded-lg bg-secondary px-3 text-sm outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {/* The words for a screen reader are in the label's own item, so they
          read "woodworking, 2 picks"; the count beside it is for the eye. */}
      <span className="min-w-0 truncate">
        {topic.label}
        <span className="sr-only">
          , {topic.count} {topic.count === 1 ? "pick" : "picks"}
        </span>
      </span>
      <span aria-hidden="true" className="text-muted-foreground tabular-nums">
        {topic.count}
      </span>
    </Link>
  );
}

/** The "Rebalance" button and the popover it opens. */
function Rebalance({
  feedId,
  counts,
}: {
  feedId: number;
  counts: readonly TopicCount[];
}) {
  return (
    <Popover>
      <PopoverTrigger
        render={
          <Button variant="outline" size="lg" className="rounded-lg px-3" />
        }
      >
        <SlidersHorizontal aria-hidden="true" />
        Rebalance
      </PopoverTrigger>
      <PopoverContent
        side="bottom"
        align="end"
        className="max-h-[min(40rem,calc(100svh-6rem))] w-[30rem] max-w-[calc(100vw-2rem)] gap-5 overflow-y-auto p-4 motion-reduce:data-open:animate-none motion-reduce:data-closed:animate-none"
      >
        <RebalancePanel feedId={feedId} counts={counts} />
      </PopoverContent>
    </Popover>
  );
}

/**
 * What the popover holds: the dial, the sliders of the topics I follow and,
 * once either was changed, a note that it applies to the next feed with a
 * button to build that now. It goes again when the feed is replaced, as the
 * change is in it then.
 */
function RebalancePanel({
  feedId,
  counts,
}: {
  feedId: number;
  counts: readonly TopicCount[];
}) {
  // The feed that was current when something was changed.
  const [changedAt, setChangedAt] = useState<number | null>(null);
  const waiting = changedAt === feedId;
  const picks = new Map(counts.map(({ slug, count }) => [slug, count]));

  return (
    <>
      <PopoverHeader>
        {/* An h3: the popover belongs to the strip's h2. */}
        <PopoverTitle render={<h3 />} className="text-base font-semibold">
          Rebalance your feed
        </PopoverTitle>
        <PopoverDescription>
          Steer what the next feed is made of.
        </PopoverDescription>
      </PopoverHeader>
      <MixDial onChanged={() => setChangedAt(feedId)} />
      <TopicWeights counts={picks} onChanged={() => setChangedAt(feedId)} />
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-4 gap-y-2",
          waiting && "border-t pt-4",
        )}
      >
        <p role="status" className="text-sm empty:sr-only">
          {waiting ? "Applies to the next feed." : null}
        </p>
        {waiting && (
          <RefreshFeedButton label="Rebuild today's feed" variant="secondary" />
        )}
      </div>
    </>
  );
}
