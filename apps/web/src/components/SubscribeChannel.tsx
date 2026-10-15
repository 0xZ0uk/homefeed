import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "#/components/ui/button";
import { channelUrl } from "#/lib/discover";
import { channelsQuery, subscribe } from "#/server/channels";
import { suggestedChannelsQuery } from "#/server/discover";

/**
 * Subscribe to a video's channel from the watch page. Shows a disabled
 * "Subscribed" once it is one (managing subscriptions lives on their page).
 */
export function SubscribeChannel({ channelId }: { channelId: string }) {
  const queryClient = useQueryClient();
  const { data: channels } = useQuery(channelsQuery);
  const mutation = useMutation({
    mutationFn: () => subscribe({ data: { url: channelUrl(channelId) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey }),
        queryClient.invalidateQueries({
          queryKey: suggestedChannelsQuery.queryKey,
        }),
      ]);
    },
  });

  // Hidden until the list loads, so a subscribed channel never flashes "Subscribe".
  if (!channels) return null;
  const subscribed =
    channels.some((channel) => channel.channel_id === channelId) ||
    mutation.data?.ok === true;
  const failed =
    mutation.isError || (mutation.data !== undefined && !mutation.data.ok);

  return (
    <div className="flex items-center gap-2">
      {subscribed ? (
        <Button variant="secondary" size="lg" className="px-4" disabled>
          Subscribed
        </Button>
      ) : (
        <Button
          size="lg"
          className="px-4"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </Button>
      )}
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {mutation.data && !mutation.data.ok
            ? mutation.data.message
            : "Couldn't subscribe. Try again later."}
        </p>
      )}
    </div>
  );
}
