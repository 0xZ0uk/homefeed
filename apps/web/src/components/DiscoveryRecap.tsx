import type {
  DiscoveredChannelOut,
  DiscoveredTopicOut,
  DiscoveryRecapOut,
} from "@homefeed/api-client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Compass } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { ScoreFace } from "#/components/ScoreFace";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "#/components/ui/card";
import {
  RECAP_NOTE,
  channelStatusLabel,
  describeChannel,
  followUpReason,
  followUps,
  isFollowed,
  periodWords,
  recapHeadline,
  recapPeriod,
  recapStats,
  subscribedMessage,
  topicsNote,
  trialStartedMessage,
  unsubscribedMessage,
  type Change,
  type RecapStat,
} from "#/lib/discoveries";
import { channelUrl } from "#/lib/discover";
import { cn } from "#/lib/utils";
import { channelHidesQuery, hide, type HideKind } from "#/server/channel-hides";
import {
  channelsQuery,
  startTrial,
  subscribe,
  unsubscribe,
} from "#/server/channels";
import {
  discoveryVideosQuery,
  suggestedChannelsQuery,
} from "#/server/discover";
import { discoveryRecapQuery } from "#/server/insights";

/** Keyboard focus ring for links and buttons made of plain elements. */
const FOCUS_RING =
  "rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * The top of the Insights page: whether discovery is working. It sets the last
 * week against the week before: how many channels you watched for the first
 * time, how many of them you kept or rated highly, and what share of what you
 * watched came from channels new to you. Below that, the new channels with
 * where each stands now, the ones worth following (rated high, not followed)
 * with a way to subscribe or try them, and the topics that turned up for the
 * first time. A week without anything new says where to look.
 *
 * It sits apart from the rest of the page: if it can't load, it says so here
 * and the other sections still work (see the route's loader).
 */
export function DiscoveryRecap() {
  const recap = useQuery(discoveryRecapQuery);
  const { refetch } = recap;
  return (
    <section
      aria-labelledby="discoveries-heading"
      className="@container flex flex-col gap-4"
    >
      <h2 id="discoveries-heading" className="text-lg font-semibold">
        Discoveries
      </h2>
      {recap.data ? (
        <Recap recap={recap.data} asOf={new Date(recap.dataUpdatedAt)} />
      ) : recap.isError ? (
        <div role="alert" className="flex flex-col items-start gap-3">
          <p>Couldn&apos;t load your discoveries. The API may be down.</p>
          <Button variant="secondary" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <>
          <span className="sr-only">Loading discoveries…</span>
          <RecapSkeleton />
        </>
      )}
    </section>
  );
}

/**
 * The totals in a grid: two across, four where the section is wide enough for
 * a label to stay on one line.
 */
const TILES = "grid grid-cols-2 gap-3 @4xl:grid-cols-4";

/** Placeholders for the totals while the recap loads. */
export function RecapSkeleton() {
  return (
    <div aria-hidden="true" className="@container flex flex-col gap-4">
      <div className="h-5 w-96 max-w-full rounded bg-muted motion-safe:animate-pulse" />
      <div className={TILES}>
        {["tried", "kept", "liked", "share"].map((key) => (
          <Card key={key} className="gap-3 p-4">
            <div className="h-4 w-24 rounded bg-muted motion-safe:animate-pulse" />
            <div className="h-7 w-14 rounded bg-muted motion-safe:animate-pulse" />
            <div className="h-4 w-20 rounded bg-muted motion-safe:animate-pulse" />
          </Card>
        ))}
      </div>
    </div>
  );
}

/**
 * `asOf` is when the recap was fetched. The days left of a trial are counted
 * from then, not from the time of the render: a trial just started has all its
 * days, and the server and the browser word it the same.
 */
function Recap({ recap, asOf }: { recap: DiscoveryRecapOut; asOf: Date }) {
  const { current, previous, channels, topics } = recap;
  // With nothing watched in either window there is nothing to compare.
  const compared = current.videos_watched + previous.videos_watched > 0;
  const before = periodWords(recap.days).versus;

  return (
    <>
      <div className="flex flex-col gap-1">
        <p className="max-w-prose text-pretty">{recapHeadline(recap)}</p>
        <p className="text-sm text-muted-foreground">{recapPeriod(recap)}</p>
      </div>
      {compared && (
        <>
          <div className={TILES}>
            {recapStats(recap).map((stat) => (
              <StatTile key={stat.key} stat={stat} before={before} />
            ))}
          </div>
          <p className="max-w-prose text-sm text-pretty text-muted-foreground">
            {RECAP_NOTE}
          </p>
        </>
      )}
      {channels.length === 0 ? (
        <NothingNew />
      ) : (
        <>
          <NewChannels channels={channels} now={asOf} />
          <WorthFollowing
            channels={channels}
            threshold={recap.top_tier_threshold}
          />
        </>
      )}
      {topics.length > 0 && (
        <NewTopics topics={topics} total={current.new_topics} />
      )}
    </>
  );
}

/** One total with the week before beside it. */
function StatTile({ stat, before }: { stat: RecapStat; before: string }) {
  return (
    <Card className="gap-3 p-4">
      <dl className="flex flex-col gap-1.5">
        {/* Room for two lines on narrow screens, so the figures line up. */}
        <dt className="min-h-10 text-sm font-medium text-muted-foreground @lg:min-h-0">
          {stat.label}
        </dt>
        <dd className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <span
            className={cn(
              "text-3xl leading-tight font-semibold tracking-tight tabular-nums",
              stat.value === "–" && "text-muted-foreground",
            )}
          >
            {stat.value}
          </span>
          {stat.change && <ChangeBadge change={stat.change} before={before} />}
        </dd>
        <dd className="text-sm text-muted-foreground">{stat.detail}</dd>
      </dl>
    </Card>
  );
}

/**
 * How a total moved since the week before, in words and an arrow rather than
 * colour: a drop in the number of new channels isn't an error.
 */
function ChangeBadge({ change, before }: { change: Change; before: string }) {
  return (
    <Badge variant="outline" className="text-muted-foreground tabular-nums">
      {change.direction !== "same" && (
        <span aria-hidden="true">{change.direction === "up" ? "▲" : "▼"}</span>
      )}
      {change.label}
      <span className="sr-only"> compared with {before}</span>
    </Badge>
  );
}

/** A red dot beside a heading: what's new to you, as on the feed's cards. */
function NewMark() {
  return (
    <span
      aria-hidden="true"
      className="mr-2 inline-block size-2 rounded-full bg-brand align-middle forced-colors:bg-[CanvasText]"
    />
  );
}

/** Nothing new this week: where to find something. */
function NothingNew() {
  return (
    <Card className="items-center gap-2 py-8 text-center">
      <Compass aria-hidden="true" className="size-8 text-muted-foreground/60" />
      <p className="max-w-prose px-6 text-sm text-pretty text-muted-foreground">
        Find channels to try in{" "}
        <Link
          to="/discover"
          className={cn(
            "underline underline-offset-2 hover:text-foreground",
            FOCUS_RING,
          )}
        >
          Discover
        </Link>
        , or open{" "}
        <Link
          to="/"
          className={cn(
            "underline underline-offset-2 hover:text-foreground",
            FOCUS_RING,
          )}
        >
          Today
        </Link>{" "}
        and look for the videos marked “New to you”.
      </p>
    </Card>
  );
}

function NewChannels({
  channels,
  now,
}: {
  channels: DiscoveredChannelOut[];
  now: Date;
}) {
  const headingId = useId();
  return (
    <Card>
      <CardHeader>
        <CardTitle render={<h3 id={headingId} />} className="text-base">
          <NewMark />
          New channels
        </CardTitle>
        <CardDescription>
          Channels you watched for the first time, the best rated first, and
          where each stands now.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul aria-labelledby={headingId} className="flex flex-col divide-y">
          {channels.map((channel) => (
            <NewChannelRow
              key={channel.channel_id}
              channel={channel}
              now={now}
            />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function NewChannelRow({
  channel,
  now,
}: {
  channel: DiscoveredChannelOut;
  now: Date;
}) {
  return (
    <li className="grid grid-cols-[2.5rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[2.5rem_minmax(0,1fr)_auto]">
      <ChannelAvatar
        url={channel.thumbnail_url}
        title={channel.title}
        className="row-span-2 self-start sm:row-span-1 sm:self-center"
      />
      <div className="flex min-w-0 flex-col">
        <p className="font-medium break-words">
          <ChannelLink channel={channel} />
        </p>
        <p className="text-sm text-muted-foreground">
          {describeChannel(channel)}
        </p>
      </div>
      <Badge
        variant={isFollowed(channel) ? "secondary" : "outline"}
        className="col-start-2 justify-self-start sm:col-start-3 sm:justify-self-end"
      >
        {channelStatusLabel(channel, now)}
      </Badge>
    </li>
  );
}

function ChannelLink({ channel }: { channel: DiscoveredChannelOut }) {
  return (
    <Link
      to="/channels/$channelId"
      params={{ channelId: channel.channel_id }}
      className={cn("hover:underline", FOCUS_RING)}
    >
      {channel.title}
    </Link>
  );
}

function NewTopics({
  topics,
  total,
}: {
  topics: DiscoveredTopicOut[];
  total: number;
}) {
  const headingId = useId();
  const note = topicsNote(topics.length, total);
  return (
    <Card>
      <CardHeader>
        <CardTitle render={<h3 id={headingId} />} className="text-base">
          <NewMark />
          New topics
        </CardTitle>
        <CardDescription>
          Topics that first turned up in the videos you watched or rated.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ul aria-labelledby={headingId} className="flex flex-wrap gap-2">
          {topics.map((topic) => (
            <li key={topic.slug} className="max-w-full">
              <Link
                to="/tags/$slug"
                params={{ slug: topic.slug }}
                className="inline-flex min-h-7 max-w-full items-center rounded-full border border-transparent bg-secondary px-3 py-1 text-sm leading-tight text-secondary-foreground outline-none hover:bg-accent focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="break-words">{topic.label}</span>
              </Link>
            </li>
          ))}
        </ul>
        {note && <p className="text-sm text-muted-foreground">{note}</p>}
      </CardContent>
    </Card>
  );
}

/** What Undo does: unsubscribe again, putting back the hide the channel had. */
interface Undo {
  channelId: string;
  title: string;
  restoreHide: HideKind | null;
}

interface Status {
  message: string;
  undo?: Undo;
  /** Offer a way to the subscriptions, where a new trial is kept or ended. */
  seeSubscriptions?: boolean;
  /** The row that was acted on is gone, so keyboard focus goes to the message. */
  moveFocus?: boolean;
}

/**
 * The channels that are new this week and got a high rating but aren't
 * followed, each with the two ways to follow: subscribe, or try for two weeks.
 * What was done is said in a status line with an Undo. The card stays when the
 * last one is dealt with, so that the line does too.
 */
function WorthFollowing({
  channels,
  threshold,
}: {
  channels: DiscoveredChannelOut[];
  threshold: number;
}) {
  const queryClient = useQueryClient();
  const headingId = useId();
  const [status, setStatus] = useState<Status | null>(null);
  const statusRef = useRef<HTMLParagraphElement>(null);
  const worth = followUps(channels);

  // Whoever acted on a row has nothing left to focus once it's gone.
  useEffect(() => {
    if (status?.moveFocus) statusRef.current?.focus();
  }, [status]);

  // A subscription changes the statuses here, and what Discover and Today's
  // Discovery carousel suggest.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: discoveryRecapQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelHidesQuery.queryKey }),
      queryClient.invalidateQueries({
        queryKey: suggestedChannelsQuery.queryKey,
      }),
      queryClient.invalidateQueries({
        queryKey: discoveryVideosQuery.queryKey,
      }),
    ]);

  const undo = useMutation({
    mutationFn: async ({ channelId, restoreHide }: Undo) => {
      await unsubscribe({ data: { channelId } });
      if (restoreHide) await hide({ data: { channelId, kind: restoreHide } });
    },
    onSuccess: async (_result, { title }) => {
      setStatus({ message: unsubscribedMessage(title), moveFocus: true });
      await refresh();
    },
    onError: () =>
      setStatus({
        message: "Couldn't undo. You can unsubscribe in Subscriptions.",
        seeSubscriptions: true,
      }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle render={<h3 id={headingId} />} className="text-base">
          Worth following
        </CardTitle>
        <CardDescription>
          New channels with a video you rated {threshold} or higher, that you
          don&apos;t follow yet.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p
          ref={statusRef}
          role="status"
          tabIndex={-1}
          className={cn(
            "flex flex-wrap items-center gap-x-3 gap-y-1 text-sm empty:sr-only",
            FOCUS_RING,
          )}
        >
          {status?.message}
          {status?.undo && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={undo.isPending}
              onClick={() => status.undo && undo.mutate(status.undo)}
            >
              Undo
            </Button>
          )}
          {status?.seeSubscriptions && (
            <Link
              to="/subscriptions"
              className={cn("underline underline-offset-2", FOCUS_RING)}
            >
              Open Subscriptions
            </Link>
          )}
        </p>
        {worth.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing to follow up right now. A new channel you don&apos;t follow
            shows up here once you rate one of its videos {threshold} or higher.
          </p>
        ) : (
          <ul aria-labelledby={headingId} className="flex flex-col divide-y">
            {worth.map((channel) => (
              <FollowUpRow
                key={channel.channel_id}
                channel={channel}
                onStatus={setStatus}
                refresh={refresh}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function FollowUpRow({
  channel,
  onStatus,
  refresh,
}: {
  channel: DiscoveredChannelOut;
  onStatus: (status: Status) => void;
  refresh: () => Promise<unknown>;
}) {
  const { channel_id: channelId, title } = channel;
  const reason = followUpReason(channel);
  const undo: Undo = { channelId, title, restoreHide: channel.hide_kind };
  const subscribing = useMutation({
    mutationFn: () => subscribe({ data: { url: channelUrl(channelId) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      onStatus({
        message: subscribedMessage(title, result.created),
        undo: result.created ? undo : undefined,
        moveFocus: true,
      });
      await refresh();
    },
  });
  const trying = useMutation({
    mutationFn: () => startTrial({ data: { channelId } }),
    onSuccess: async ({ created }) => {
      onStatus({
        message: trialStartedMessage(title, created),
        undo: created ? undo : undefined,
        seeSubscriptions: created,
        moveFocus: true,
      });
      await refresh();
    },
  });
  const busy = subscribing.isPending || trying.isPending;
  const subscribeFailed =
    subscribing.isError ||
    (subscribing.data !== undefined && !subscribing.data.ok);

  return (
    <li className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-1 basis-56 items-center gap-3">
          <ChannelAvatar url={channel.thumbnail_url} title={title} />
          <div className="flex min-w-0 flex-col">
            <p className="font-medium break-words">
              <ChannelLink channel={channel} />
            </p>
            {reason && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                {channel.top_score !== null && (
                  <ScoreFace
                    score={channel.top_score}
                    filled
                    className="size-4"
                  />
                )}
                {reason}
              </p>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Named for the channel, as on Discover's cards; while the press
              is being handled the visible words are the name. */}
          <Button
            variant="outline"
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={
              subscribing.isPending ? undefined : `Subscribe to ${title}`
            }
            onClick={() => subscribing.mutate()}
          >
            {subscribing.isPending ? "Subscribing…" : "Subscribe"}
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="px-4"
            disabled={busy}
            aria-label={
              trying.isPending ? undefined : `Try for 2 weeks: ${title}`
            }
            onClick={() => trying.mutate()}
          >
            {trying.isPending ? "Starting…" : "Try for 2 weeks"}
          </Button>
        </div>
      </div>
      {subscribeFailed && (
        <p role="alert" className="text-sm text-destructive">
          {subscribing.data && !subscribing.data.ok
            ? subscribing.data.message
            : `Couldn't subscribe to ${title}. Try again.`}
        </p>
      )}
      {trying.isError && (
        <p role="alert" className="text-sm text-destructive">
          Couldn&apos;t start the trial of {title}. Try again.
        </p>
      )}
    </li>
  );
}
