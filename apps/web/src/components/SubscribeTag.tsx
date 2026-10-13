import type { TagDetail } from "@homefeed/api-client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { HideTagCheckbox } from "#/components/HideTagCheckbox";
import { Button } from "#/components/ui/button";
import { WeightSlider } from "#/components/WeightSlider";
import { isMuted } from "#/lib/topics";
import {
  editTopic,
  muteTagBySlug,
  subscribeToTag,
  topicsQuery,
  unmuteTagBySlug,
  unsubscribeFromTag,
} from "#/server/topics";

/**
 * The tag page's relation to the tag, in three states. None: Subscribe (weight
 * +0.5) or Mute (weight -0.5). Subscribed: Unsubscribe, Mute and the weight
 * slider. Muted (a negative weight): Unmute, the slider and, at -1, an option
 * to hide the tag's videos from the feed. Videos with the tag rank higher or
 * lower in the home feed by the weight, more for confident tags.
 */
export function SubscribeTag({ detail }: { detail: TagDetail }) {
  const { tag, topic } = detail;
  const queryClient = useQueryClient();
  // The sidebar lists subscribed and muted tags from the topics, and this
  // page's tag from its own query.
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ["tag", tag.slug] }),
      queryClient.invalidateQueries({ queryKey: topicsQuery.queryKey }),
    ]);
  const subscribe = useMutation({
    mutationFn: () => subscribeToTag({ data: { slug: tag.slug } }),
    onSettled: refresh,
  });
  const unsubscribe = useMutation({
    mutationFn: () => unsubscribeFromTag({ data: { slug: tag.slug } }),
    onSettled: refresh,
  });
  const mute = useMutation({
    mutationFn: () => muteTagBySlug({ data: { slug: tag.slug } }),
    onSettled: refresh,
  });
  const unmute = useMutation({
    mutationFn: () => unmuteTagBySlug({ data: { slug: tag.slug } }),
    onSettled: refresh,
  });
  const update = useMutation({
    mutationFn: (changes: { weight?: number; hide?: boolean }) =>
      editTopic({ data: { id: topic?.id ?? 0, ...changes } }),
    onSettled: refresh,
  });
  // The slider's position while dragging; saved when let go.
  const [weight, setWeight] = useState(topic?.weight ?? 0);
  const [savedWeight, setSavedWeight] = useState(topic?.weight ?? 0);
  if ((topic?.weight ?? 0) !== savedWeight) {
    // The stored weight changed (saved here or elsewhere): follow it.
    setSavedWeight(topic?.weight ?? 0);
    setWeight(topic?.weight ?? 0);
  }
  const busy =
    subscribe.isPending ||
    unsubscribe.isPending ||
    mute.isPending ||
    unmute.isPending ||
    update.isPending;
  const failed =
    subscribe.isError ||
    unsubscribe.isError ||
    mute.isError ||
    unmute.isError ||
    update.isError ||
    subscribe.data?.ok === false ||
    mute.data?.ok === false ||
    update.data?.ok === false;
  const message =
    [subscribe.data, mute.data, update.data].find((r) => r?.ok === false)
      ?.message ?? "Couldn't save that change. Try again.";
  const muted = topic != null && isMuted(topic);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {topic ? (
          <>
            <p className="text-sm font-medium">
              {muted ? "Muted" : "Subscribed"}
            </p>
            <Button
              type="button"
              variant="secondary"
              size="lg"
              disabled={busy}
              onClick={() => (muted ? unmute.mutate() : unsubscribe.mutate())}
              className="rounded-full px-4"
            >
              {muted
                ? unmute.isPending
                  ? "Unmuting…"
                  : "Unmute"
                : unsubscribe.isPending
                  ? "Unsubscribing…"
                  : "Unsubscribe"}
            </Button>
            {!muted && (
              <Button
                type="button"
                variant="secondary"
                size="lg"
                disabled={busy}
                onClick={() => mute.mutate()}
                className="rounded-full px-4"
              >
                {mute.isPending ? "Muting…" : "Mute"}
              </Button>
            )}
            <WeightSlider
              id="tag-weight"
              label="Weight"
              value={weight}
              disabled={unsubscribe.isPending || unmute.isPending}
              onChange={setWeight}
              onCommit={(value) => {
                if (value !== topic.weight && !update.isPending) {
                  update.mutate({ weight: value });
                }
              }}
            />
          </>
        ) : (
          <>
            <Button
              type="button"
              size="lg"
              disabled={busy}
              onClick={() => subscribe.mutate()}
              className="rounded-full px-4"
            >
              {subscribe.isPending ? "Subscribing…" : "Subscribe"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="lg"
              disabled={busy}
              onClick={() => mute.mutate()}
              className="rounded-full px-4"
            >
              {mute.isPending ? "Muting…" : "Mute"}
            </Button>
          </>
        )}
      </div>
      {topic && muted && (
        <HideTagCheckbox
          id="tag-hide"
          weight={topic.weight}
          checked={topic.hide}
          disabled={busy}
          onChange={(hide) => update.mutate({ hide })}
        />
      )}
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      )}
    </div>
  );
}
