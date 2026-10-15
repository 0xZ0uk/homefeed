import type { SubscribedChannel } from "@homefeed/api-client";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { MONTH_MUTE_DAYS } from "#/lib/channels";
import {
  channelsQuery,
  endTrial,
  keepTrial,
  unsubscribe,
  updatePrefs,
  type ChannelPrefsUpdate,
} from "#/server/channels";

/** What the Channels tab tells the person about what they just did. */
export interface ChannelStatus {
  message: string;
  /** Unmute this channel again. */
  unmute?: { channelId: string; title: string };
  /** The channel's row is gone, so keyboard focus goes to the message. */
  moveFocus?: boolean;
}

export type PrefsChange = Omit<ChannelPrefsUpdate, "channelId">;

/** "Nov 11", for when a mute ends. */
export function formatMuteEnd(until: string): string {
  return new Date(until).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
  });
}

/**
 * Everything that can be done to one subscribed channel on the Channels tab:
 * change its preferences (preference, pin, mute), unsubscribe, and keep or end
 * a trial. Each reports what it did through `announce` and refreshes the
 * channels.
 */
export function useChannelActions(
  channel: SubscribedChannel,
  announce: (status: ChannelStatus) => void,
) {
  const queryClient = useQueryClient();
  const { channel_id: channelId, title } = channel;
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey });

  const update = useMutation({
    mutationFn: (prefs: PrefsChange) =>
      updatePrefs({ data: { channelId, ...prefs } }),
    onSuccess: (updated, prefs) => {
      // Preference and pin show their own new state; only a mute needs words.
      const unmute = { channelId, title };
      if (prefs.mute_days === MONTH_MUTE_DAYS && updated.muted_until) {
        announce({
          message: `Muted ${title} until ${formatMuteEnd(updated.muted_until)}.`,
          unmute,
        });
      } else if (prefs.muted === true) {
        announce({ message: `Muted ${title}.`, unmute });
      } else if (prefs.muted === false) {
        announce({ message: `Unmuted ${title}.` });
      }
    },
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: () => unsubscribe({ data: { channelId } }),
    onSuccess: () =>
      announce({ message: `Unsubscribed from ${title}.`, moveFocus: true }),
    onSettled: refresh,
  });
  const keep = useMutation({
    mutationFn: () => keepTrial({ data: { channelId } }),
    // Keeping takes the trial's buttons away, so the message gets the focus.
    onSuccess: () =>
      announce({
        message: `Kept ${title}. It's a regular subscription now.`,
        moveFocus: true,
      }),
    onSettled: refresh,
  });
  const end = useMutation({
    mutationFn: () => endTrial({ data: { channelId } }),
    onSuccess: () =>
      announce({
        message: `Ended the trial of ${title}. It won't be suggested again right away.`,
        moveFocus: true,
      }),
    onSettled: refresh,
  });

  return {
    update,
    remove,
    keep,
    end,
    busy:
      update.isPending || remove.isPending || keep.isPending || end.isPending,
    failed: update.isError || remove.isError || keep.isError || end.isError,
  };
}
