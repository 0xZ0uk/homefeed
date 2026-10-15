import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";

import { WeightSlider } from "#/components/WeightSlider";
import { followedTags } from "#/lib/feed-mix";
import { tagAdminKey } from "#/server/tag-admin";
import {
  editTagSubscription,
  tagSubscriptionsQuery,
  type TagSubscription,
} from "#/server/tag-subscriptions";

/**
 * The tags I follow, each with the slider of its boost (from Suppress to
 * Boost, as on the tag's own page), the ones with the most picks in today's
 * feed first. A slider saves when it's let go, and `onChanged` tells the
 * caller, since a new weight only counts from the next feed.
 *
 * The list is the tags followed when it first loaded: one moved to zero or
 * below isn't followed any more, but stays here, so it can be moved back.
 * `counts` holds how many of today's picks carry each tag, by slug.
 */
export function TopicWeights({
  counts,
  onChanged,
}: {
  counts: ReadonlyMap<string, number>;
  onChanged: () => void;
}) {
  const { data, isError, refetch } = useQuery(tagSubscriptionsQuery);
  const [slugs, setSlugs] = useState<string[] | null>(null);
  if (slugs === null && data) {
    setSlugs(followedTags(data, counts).map(({ slug }) => slug));
  }

  if (!data || slugs === null) {
    return isError ? (
      <div role="alert" className="flex flex-col items-start gap-1 text-sm">
        <p>Couldn't load your tags. The API may be down.</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="rounded-sm underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          Try again
        </button>
      </div>
    ) : (
      <p className="text-sm text-muted-foreground">Loading your tags…</p>
    );
  }

  const listed = slugs.flatMap((slug) => {
    const subscription = data.find((s) => s.slug === slug);
    return subscription ? [subscription] : [];
  });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h4 className="text-sm font-medium">Followed topics</h4>
        <p className="text-xs text-muted-foreground">
          Boost a topic to see more of it, or suppress it to see less.
        </p>
      </div>
      {listed.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          You don't follow any topics yet. Follow a tag on a video's page to
          boost it, or{" "}
          <Link
            to="/explore"
            className="rounded-sm underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            browse your tags in Explore
          </Link>
          .
        </p>
      ) : (
        <ul aria-label="Followed topics" className="flex flex-col gap-4">
          {listed.map((subscription) => (
            <TopicWeight
              key={subscription.slug}
              subscription={subscription}
              count={counts.get(subscription.slug) ?? 0}
              onChanged={onChanged}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One followed tag: its slider, saved when let go. */
function TopicWeight({
  subscription,
  count,
  onChanged,
}: {
  subscription: TagSubscription;
  count: number;
  onChanged: () => void;
}) {
  const id = useId();
  const queryClient = useQueryClient();
  // The slider's position while dragging; saved when let go.
  const [weight, setWeight] = useState(subscription.weight);
  const [savedWeight, setSavedWeight] = useState(subscription.weight);
  if (subscription.weight !== savedWeight) {
    // The stored weight changed (saved here or elsewhere): follow it.
    setSavedWeight(subscription.weight);
    setWeight(subscription.weight);
  }
  const update = useMutation({
    mutationFn: (value: number) =>
      editTagSubscription({
        data: { slug: subscription.slug, weight: value },
      }),
    onSuccess: (result) => {
      if (result.ok) onChanged();
      else setWeight(savedWeight);
    },
    onError: () => setWeight(savedWeight),
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: tagSubscriptionsQuery.queryKey,
        }),
        queryClient.invalidateQueries({ queryKey: ["tag", subscription.slug] }),
        queryClient.invalidateQueries({ queryKey: tagAdminKey }),
      ]),
  });
  const failed = update.isError || (update.data && !update.data.ok);

  return (
    <li className="flex flex-col gap-1">
      <WeightSlider
        id={id}
        label={
          count > 0
            ? `${subscription.label} · ${count} today`
            : subscription.label
        }
        value={weight}
        stacked
        onChange={setWeight}
        onCommit={(value) => {
          if (value !== subscription.weight && !update.isPending) {
            update.mutate(value);
          }
        }}
      />
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          Couldn't save the weight of {subscription.label}. Try again.
        </p>
      )}
    </li>
  );
}
