import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";

import { ChangeFailed, useChanges } from "#/components/use-changes";
import { Button } from "#/components/ui/button";
import { WeightSlider } from "#/components/WeightSlider";
import type { ActionStatus } from "#/lib/card-actions";
import { formatPercent, plural } from "#/lib/insights";
import { SCORE_SCALE_HINT } from "#/lib/scores";
import {
  boostMessage,
  describeImbalance,
  describeMuted,
  describeTopic,
  followedTopics,
  imbalanceOf,
  mutedMessage,
  mutedTopics,
  restoredMessage,
  shareOfPicks,
  suggestionFor,
  unfollowedMessage,
  unmutedMessage,
  type TagTaste,
  type Taste,
} from "#/lib/taste";
import { tagAdminKey } from "#/server/tag-admin";
import {
  editTagSubscription,
  muteTagBySlug,
  subscribeToTag,
  tagSubscriptionsQuery,
  unmuteTagBySlug,
  unsubscribeFromTag,
} from "#/server/tag-subscriptions";
import { tasteQuery } from "#/server/taste";

/** What is being done to a topic, for the words on its button. */
type Action = "boost" | "mute" | "unfollow" | "unmute" | "restore";

/** Saves a topic's boost (and, for a muted one at -1, whether it hides). */
async function saveWeight(slug: string, weight: number, hide?: boolean) {
  const result = await editTagSubscription({ data: { slug, weight, hide } });
  if (!result.ok) throw new ChangeFailed(result.message);
}

/**
 * Everything that can be done to a topic on the Taste page: change its boost,
 * mute it, unfollow it, unmute it, and take each of those back. Each says what
 * it did, with an Undo that puts the boost (or the follow, or the mute) back as
 * it was, and refreshes everything that lists topics.
 */
function useTopicChanges(announce: (status: ActionStatus) => void) {
  const queryClient = useQueryClient();
  // The topics of this page, the lists in Explore and Subscriptions, and tag pages.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: tasteQuery.queryKey }),
      queryClient.invalidateQueries({
        queryKey: tagSubscriptionsQuery.queryKey,
      }),
      queryClient.invalidateQueries({ queryKey: tagAdminKey }),
      queryClient.invalidateQueries({ queryKey: ["tag"] }),
    ]);
  const { pending, perform } = useChanges<Action>(announce, refresh);

  /** Puts the boost back to what `tag` had. */
  const restoreBoost = (tag: TagTaste) =>
    perform(
      tag.slug,
      "restore",
      `Couldn't restore ${tag.label}. Try again.`,
      async () => {
        await saveWeight(tag.slug, tag.weight);
        return { ok: true, message: restoredMessage(tag.label) };
      },
    );

  /** Follows `tag` again at the boost it had. */
  const refollow = (tag: TagTaste) =>
    perform(
      tag.slug,
      "restore",
      `Couldn't restore ${tag.label}. Try again.`,
      async () => {
        const result = await subscribeToTag({ data: { slug: tag.slug } });
        if (!result.ok) throw new ChangeFailed(result.message);
        if (result.subscription.weight !== tag.weight) {
          await saveWeight(tag.slug, tag.weight);
        }
        return { ok: true, message: restoredMessage(tag.label) };
      },
    );

  /** Mutes `tag` again as it was muted, hiding included. */
  const remute = (tag: TagTaste) =>
    perform(
      tag.slug,
      "restore",
      `Couldn't restore ${tag.label}. Try again.`,
      async () => {
        const result = await muteTagBySlug({ data: { slug: tag.slug } });
        if (!result.ok) throw new ChangeFailed(result.message);
        if (result.subscription.weight !== tag.weight || tag.hide) {
          await saveWeight(tag.slug, tag.weight, tag.hide || undefined);
        }
        return { ok: true, message: restoredMessage(tag.label) };
      },
    );

  return {
    pending,
    /** Sets the boost; a negative one mutes the topic. */
    boost: (tag: TagTaste, weight: number) =>
      perform(
        tag.slug,
        "boost",
        `Couldn't save the boost of ${tag.label}. Try again.`,
        async () => {
          await saveWeight(tag.slug, weight);
          return {
            ok: true,
            message: boostMessage(tag.label, weight),
            undo: () => void restoreBoost(tag),
            focus: weight < 0,
          };
        },
      ),
    mute: (tag: TagTaste) =>
      perform(
        tag.slug,
        "mute",
        `Couldn't mute ${tag.label}. Try again.`,
        async () => {
          const result = await muteTagBySlug({ data: { slug: tag.slug } });
          if (!result.ok) throw new ChangeFailed(result.message);
          return {
            ok: true,
            message: mutedMessage(tag.label),
            undo: () => void restoreBoost(tag),
            focus: true,
          };
        },
      ),
    unfollow: (tag: TagTaste) =>
      perform(
        tag.slug,
        "unfollow",
        `Couldn't unfollow ${tag.label}. Try again.`,
        async () => {
          await unsubscribeFromTag({ data: { slug: tag.slug } });
          return {
            ok: true,
            message: unfollowedMessage(tag.label),
            undo: () => void refollow(tag),
            focus: true,
          };
        },
      ),
    unmute: (tag: TagTaste) =>
      perform(
        tag.slug,
        "unmute",
        `Couldn't unmute ${tag.label}. Try again.`,
        async () => {
          await unmuteTagBySlug({ data: { slug: tag.slug } });
          return {
            ok: true,
            message: unmutedMessage(tag.label),
            undo: () => void remute(tag),
            focus: true,
          };
        },
      ),
  };
}

type TopicChanges = ReturnType<typeof useTopicChanges>;

const EMPTY_NOTE = "rounded-xl border border-dashed p-6 text-muted-foreground";
const LINK =
  "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * The topics (tags) you follow, each with its boost on a slider, how often it
 * showed up in your picks lately and what you made of those, with a word where
 * a topic takes too much of the picks or hardly shows up and a click to move its
 * boost. Mute or unfollow a topic from its row; muted topics are listed apart,
 * to unmute. Every change says what it did and can be undone.
 */
export function TasteTopics({
  taste,
  announce,
}: {
  taste: Taste;
  announce: (status: ActionStatus) => void;
}) {
  const changes = useTopicChanges(announce);
  const followed = followedTopics(taste.tags);
  const muted = mutedTopics(taste.tags);

  return (
    <section aria-labelledby="topics-heading" className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id="topics-heading" className="text-lg font-semibold">
          Topics
        </h2>
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          A boost lifts the videos that carry a topic in your feed, and a
          negative one pushes them down. Picks are the videos Homefeed put in
          your feeds in the last {taste.days} days:{" "}
          {taste.total_picks > 0
            ? plural(taste.total_picks, "video")
            : "none yet"}
          . Averages are of your ratings ({SCORE_SCALE_HINT}).
        </p>
      </div>
      {followed.length === 0 && muted.length === 0 ? (
        <p className={EMPTY_NOTE}>
          You don't follow any topics yet. Open a tag on a video to follow it,
          or{" "}
          <Link to="/subscriptions" search={{ tab: "tags" }} className={LINK}>
            browse all the tags
          </Link>
          . Followed topics show up here with how often they make it into your
          picks.
        </p>
      ) : (
        <>
          {followed.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium text-muted-foreground tabular-nums">
                Followed ({followed.length})
              </h3>
              <ul aria-label="Followed topics" className="flex flex-col gap-3">
                {followed.map((tag) => (
                  <TopicRow
                    key={tag.slug}
                    tag={tag}
                    taste={taste}
                    changes={changes}
                  />
                ))}
              </ul>
            </div>
          )}
          {muted.length > 0 && (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium text-muted-foreground tabular-nums">
                Muted ({muted.length})
              </h3>
              <ul aria-label="Muted topics" className="flex flex-col gap-3">
                {muted.map((tag) => (
                  <MutedRow
                    key={tag.slug}
                    tag={tag}
                    days={taste.days}
                    changes={changes}
                  />
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** A followed topic: its numbers, boost, what is off about it, what to do. */
function TopicRow({
  tag,
  taste,
  changes,
}: {
  tag: TagTaste;
  taste: Taste;
  changes: TopicChanges;
}) {
  const { pending } = changes;
  const doing = (action: Action) =>
    pending?.key === tag.slug && pending.action === action;
  // The slider's position while it is moved, the boost last sent to be saved
  // and the boost as the page last got it. A boost is saved when the slider is
  // let go, and moving it again meanwhile queues the next save, so the page
  // only follows the stored boost (saved here and fetched, undone, or changed
  // elsewhere) once nothing is being saved, or it would jump back.
  const [weight, setWeight] = useState(tag.weight);
  const [sent, setSent] = useState(tag.weight);
  const [stored, setStored] = useState(tag.weight);
  if (tag.weight !== stored && pending === null) {
    setStored(tag.weight);
    setSent(tag.weight);
    setWeight(tag.weight);
  }

  const share = shareOfPicks(tag.picks, taste.total_picks);
  const imbalance = imbalanceOf(tag, taste.total_picks);
  const suggestion = imbalance && suggestionFor(tag, imbalance);
  const Icon = imbalance?.kind === "rare" ? TrendingDown : TrendingUp;

  async function commit(value: number) {
    if (value === sent) return;
    setSent(value);
    const saved = await changes.boost(tag, value);
    // A change that wasn't saved leaves the slider where the boost is.
    if (!saved) {
      setSent(tag.weight);
      setWeight(tag.weight);
    }
  }

  return (
    <li className="flex flex-col gap-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1.5">
          <p className="font-medium break-words">
            <Link
              to="/tags/$slug"
              params={{ slug: tag.slug }}
              className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {tag.label}
            </Link>
          </p>
          <p className="text-sm text-muted-foreground">
            {taste.total_picks > 0 && (
              <>
                <span className="tabular-nums">{formatPercent(share)}</span> of
                your picks ·{" "}
              </>
            )}
            {describeTopic(tag, taste.days)}
          </p>
          {taste.total_picks > 0 && (
            <span
              aria-hidden="true"
              className="block h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-muted"
            >
              <span
                className="block h-full rounded-full bg-chart-1 forced-colors:bg-[Highlight]"
                style={{ width: `${share * 100}%` }}
              />
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="px-4"
            disabled={pending !== null}
            aria-label={`${doing("mute") ? "Muting" : "Mute"} ${tag.label}`}
            onClick={() => void changes.mute(tag)}
          >
            {doing("mute") ? "Muting…" : "Mute"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="px-4"
            disabled={pending !== null}
            aria-label={`${doing("unfollow") ? "Unfollowing" : "Unfollow"} ${tag.label}`}
            onClick={() => void changes.unfollow(tag)}
          >
            {doing("unfollow") ? "Unfollowing…" : "Unfollow"}
          </Button>
        </div>
      </div>
      <WeightSlider
        id={`boost-${tag.slug}`}
        label={`Boost for ${tag.label}`}
        hideLabel
        value={weight}
        onChange={setWeight}
        onCommit={(value) => void commit(value)}
      />
      {imbalance && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg bg-secondary px-3 py-2">
          <p className="flex items-center gap-2 text-sm font-medium">
            <Icon aria-hidden="true" className="size-4 shrink-0" />
            {describeImbalance(imbalance, taste.days)}.
          </p>
          {suggestion && (
            <Button
              type="button"
              variant="outline"
              size="lg"
              className="px-4"
              disabled={pending !== null}
              aria-label={`${suggestion.label} for ${tag.label}`}
              onClick={() => void changes.boost(tag, suggestion.weight)}
            >
              {suggestion.label}
            </Button>
          )}
        </div>
      )}
    </li>
  );
}

/** A muted topic: what the mute does, and a way to lift it. */
function MutedRow({
  tag,
  days,
  changes,
}: {
  tag: TagTaste;
  days: number;
  changes: TopicChanges;
}) {
  const { pending } = changes;
  const unmuting = pending?.key === tag.slug && pending.action === "unmute";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-xl border p-4">
      <div className="flex min-w-0 flex-col gap-0.5">
        <p className="font-medium break-words">
          <Link
            to="/tags/$slug"
            params={{ slug: tag.slug }}
            className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {tag.label}
          </Link>
        </p>
        <p className="text-sm text-muted-foreground">
          {describeMuted(tag, days)}
        </p>
      </div>
      <Button
        type="button"
        variant="outline"
        size="lg"
        className="px-4"
        disabled={pending !== null}
        aria-label={`${unmuting ? "Unmuting" : "Unmute"} ${tag.label}`}
        onClick={() => void changes.unmute(tag)}
      >
        {unmuting ? "Unmuting…" : "Unmute"}
      </Button>
    </li>
  );
}
