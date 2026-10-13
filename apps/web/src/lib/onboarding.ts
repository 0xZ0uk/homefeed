/** First-run setup: turning video search results into channels to subscribe to. Pure. */

/** Channels to show for a channel search. */
export const CHANNEL_HITS_LIMIT = 8;
/** Below this many channels the first feed is thin; the finish step says so. */
export const THIN_FEED_CHANNELS = 3;

export interface ChannelHit {
  channel_id: string;
  title: string;
  handle: string | null;
  /** A video of the channel from the results, to recognize it by. */
  sample_video: string;
}

/**
 * The distinct channels of a video search, in the order they first appear. The
 * search only lists videos, so a channel is found by its videos.
 */
export function channelHits(
  results: readonly {
    channel_id: string;
    channel_title: string;
    channel_handle?: string | null;
    title: string;
  }[],
  limit = CHANNEL_HITS_LIMIT,
): ChannelHit[] {
  const hits = new Map<string, ChannelHit>();
  for (const result of results) {
    if (hits.has(result.channel_id)) continue;
    hits.set(result.channel_id, {
      channel_id: result.channel_id,
      title: result.channel_title,
      handle: result.channel_handle ?? null,
      sample_video: result.title,
    });
    if (hits.size >= limit) break;
  }
  return [...hits.values()];
}

/** "3 channels", "1 channel". */
export function channelCount(count: number): string {
  return `${count} ${count === 1 ? "channel" : "channels"}`;
}
