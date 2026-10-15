import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useMemo } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { Button } from "#/components/ui/button";
import { ChangeFailed, useChanges } from "#/components/use-changes";
import type { ActionStatus } from "#/lib/card-actions";
import { PRIORS, PRIOR_LABELS } from "#/lib/channels";
import { channelUrl } from "#/lib/discover";
import {
  describeRatings,
  neutralNudge,
  RATED_WELL,
  subscribedMessage,
  topRatedChannels,
  totalChannels,
  trialMessage,
  unsubscribedMessage,
  type RatedChannel,
  type Taste,
} from "#/lib/taste";
import {
  channelHealthQuery,
  channelsQuery,
  startTrial,
  subscribe,
  unsubscribe,
} from "#/server/channels";
import { tasteQuery } from "#/server/taste";

/** What is being done to a channel, for the words on its button. */
type Action = "subscribe" | "trial" | "restore";

/**
 * What can be done to a channel you rate well and don't follow: subscribe,
 * try it for two weeks, and take either back. Each says what it did, with an
 * Undo, and refreshes this page and the channels.
 */
function useChannelChanges(announce: (status: ActionStatus) => void) {
  const queryClient = useQueryClient();
  // The channels' key covers their health numbers too.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: tasteQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
    ]);
  const { pending, perform } = useChanges<Action>(announce, refresh);

  /** Unsubscribes: what taking either back comes to. */
  const leave = (channel: RatedChannel) =>
    perform(
      channel.channel_id,
      "restore",
      `Couldn't unsubscribe from ${channel.title}. Try again.`,
      async () => {
        await unsubscribe({ data: { channelId: channel.channel_id } });
        return {
          ok: true,
          message: unsubscribedMessage(channel.title),
          focus: true,
        };
      },
    );

  return {
    pending,
    subscribe: (channel: RatedChannel) =>
      perform(
        channel.channel_id,
        "subscribe",
        `Couldn't subscribe to ${channel.title}. Try again.`,
        async () => {
          const result = await subscribe({
            data: { url: channelUrl(channel.channel_id) },
          });
          if (!result.ok) throw new ChangeFailed(result.message);
          return {
            ok: true,
            message: subscribedMessage(result.channel.title),
            undo: () => void leave(channel),
            focus: true,
          };
        },
      ),
    trial: (channel: RatedChannel) =>
      perform(
        channel.channel_id,
        "trial",
        `Couldn't start the trial of ${channel.title}. Try again.`,
        async () => {
          const { created } = await startTrial({
            data: { channelId: channel.channel_id },
          });
          return {
            ok: true,
            message: trialMessage(channel.title, created),
            undo: created ? () => void leave(channel) : undefined,
            focus: true,
          };
        },
      ),
  };
}

const EMPTY_NOTE = "rounded-xl border border-dashed p-6 text-muted-foreground";
const LINK =
  "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";
const TITLE_LINK =
  "rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * Your channels as the app sees them: how many hold each preference (with a
 * nudge when most are still on the default), the ones you follow whose videos
 * you rated best, and the ones you rated well without following, to subscribe
 * to or try for two weeks.
 */
export function TasteChannels({
  taste,
  announce,
}: {
  taste: Taste;
  announce: (status: ActionStatus) => void;
}) {
  const channels = useQuery(channelsQuery);
  const healthList = useQuery(channelHealthQuery);
  const changes = useChannelChanges(announce);
  const health = useMemo(
    () =>
      healthList.data &&
      new Map(healthList.data.map((stats) => [stats.channel_id, stats])),
    [healthList.data],
  );
  const topRated = useMemo(
    () =>
      channels.data && health ? topRatedChannels(channels.data, health) : null,
    [channels.data, health],
  );
  const total = totalChannels(taste.channel_priors);
  const nudge = neutralNudge(taste.channel_priors);

  return (
    <section aria-labelledby="channels-heading" className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 id="channels-heading" className="text-lg font-semibold">
          Channels
        </h2>
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          A preference is where a channel's score starts, before your ratings of
          its videos weigh in.
        </p>
      </div>

      {total === 0 ? (
        <p className={EMPTY_NOTE}>
          You don't follow any channels yet. Find some on{" "}
          <Link to="/discover" className={LINK}>
            Discover
          </Link>
          , or paste a channel link in{" "}
          <Link to="/subscriptions" className={LINK}>
            Subscriptions
          </Link>
          .
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-medium text-muted-foreground">
            Preferences
          </h3>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {PRIORS.map((prior) => (
              <div
                key={prior}
                className="flex flex-col gap-0.5 rounded-xl border p-4"
              >
                <dt className="text-sm text-muted-foreground">
                  {PRIOR_LABELS[prior]}
                </dt>
                <dd className="text-2xl font-semibold tabular-nums">
                  {taste.channel_priors[prior]}
                </dd>
              </div>
            ))}
          </dl>
          {nudge && <p className="max-w-prose text-sm text-pretty">{nudge}</p>}
          <p className="text-sm">
            <Link to="/subscriptions" className={LINK}>
              Open Subscriptions
            </Link>{" "}
            to set a channel's preference.
          </p>
        </div>
      )}

      {total > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium text-muted-foreground">
            Your highest-rated channels
          </h3>
          {channels.isError || healthList.isError ? (
            <div
              role="alert"
              className="flex flex-col items-start gap-2 text-sm"
            >
              <p>Couldn't load your channels' ratings. The API may be down.</p>
              <button
                type="button"
                onClick={() => {
                  void channels.refetch();
                  void healthList.refetch();
                }}
                className={LINK}
              >
                Try again
              </button>
            </div>
          ) : topRated === null ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : topRated.length === 0 ? (
            <p className={EMPTY_NOTE}>
              Channels you follow show up here once you rate their videos{" "}
              {RATED_WELL}.
            </p>
          ) : (
            <ul
              aria-label="Your highest-rated channels"
              className="flex flex-col gap-3"
            >
              {topRated.map(({ channel, rating_count, average_score }) => (
                <li
                  key={channel.channel_id}
                  className="flex items-center gap-3 rounded-xl border p-3"
                >
                  <ChannelAvatar
                    url={channel.thumbnail_url}
                    title={channel.title}
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p className="font-medium break-words">
                      <Link
                        to="/channels/$channelId"
                        params={{ channelId: channel.channel_id }}
                        className={TITLE_LINK}
                      >
                        {channel.title}
                      </Link>
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {describeRatings(rating_count, average_score)} ·
                      Preference: {PRIOR_LABELS[channel.prior]}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">
          Rated well, not followed
        </h3>
        {taste.unfollowed_channels.length === 0 ? (
          <p className={EMPTY_NOTE}>
            Channels you don't follow show up here once you rate their videos{" "}
            {RATED_WELL}, with a way to subscribe to them or try them for two
            weeks.
          </p>
        ) : (
          <ul
            aria-label="Channels rated well, not followed"
            className="flex flex-col gap-3"
          >
            {taste.unfollowed_channels.map((channel) => (
              <UnfollowedRow
                key={channel.channel_id}
                channel={channel}
                changes={changes}
              />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

type ChannelChanges = ReturnType<typeof useChannelChanges>;

/** A channel you rate well and don't follow, with what to do about it. */
function UnfollowedRow({
  channel,
  changes,
}: {
  channel: RatedChannel;
  changes: ChannelChanges;
}) {
  const { pending } = changes;
  const doing = (action: Action) =>
    pending?.key === channel.channel_id && pending.action === action;
  const subscribing = doing("subscribe");
  const trying = doing("trial");

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border p-3">
      <div className="flex min-w-60 flex-1 items-center gap-3">
        <ChannelAvatar url={channel.thumbnail_url} title={channel.title} />
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="font-medium break-words">
            <Link
              to="/channels/$channelId"
              params={{ channelId: channel.channel_id }}
              className={TITLE_LINK}
            >
              {channel.title}
            </Link>
          </p>
          <p className="text-sm text-muted-foreground">
            {describeRatings(channel.rating_count, channel.average_score)}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-4"
          disabled={pending !== null}
          aria-label={`${subscribing ? "Subscribing" : "Subscribe"} to ${channel.title}`}
          onClick={() => void changes.subscribe(channel)}
        >
          {subscribing ? "Subscribing…" : "Subscribe"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="lg"
          className="px-4"
          disabled={pending !== null}
          aria-label={`${trying ? "Starting" : "Try for 2 weeks"}: ${channel.title}`}
          onClick={() => void changes.trial(channel)}
        >
          {trying ? "Starting…" : "Try for 2 weeks"}
        </Button>
      </div>
    </li>
  );
}
