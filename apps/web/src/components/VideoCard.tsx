import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "#/components/ui/avatar";
import { channelColor } from "#/lib/feed-grid";
import { formatAge, formatDuration, formatViews } from "#/lib/format";
import { cn } from "#/lib/utils";

/** What a video card shows; feed items and tag-page videos both have it. */
export interface CardVideo {
  video_id: string;
  title: string;
  duration_seconds?: number | null;
  published_at?: string | null;
  thumbnail_url?: string | null;
  view_count?: number | null;
  channel_id: string;
  channel_title: string;
  channel_thumbnail_url?: string | null;
  watched: boolean;
}

/**
 * One video: whatever the caller puts above it, its thumbnail (or, when it
 * has none, a placeholder in the channel's colour), then the channel's avatar
 * beside title, channel and stats, and a menu of actions. The title is the
 * card's one link, stretched over the whole card; the controls sit above it.
 * A watched video's card is faded and its pictures greyed out, so the ones
 * still to watch stand out.
 */
export function VideoCard({
  video: item,
  now,
  faded = false,
  top,
  overlay,
  menu,
}: {
  video: CardVideo;
  now: Date;
  /** Fade the card for a reason of the caller's (watched videos always are). */
  faded?: boolean;
  /** Shown above the thumbnail. */
  top?: ReactNode;
  /** Shown over the thumbnail. */
  overlay?: ReactNode;
  /** Shown at the end of the title row. */
  menu?: ReactNode;
}) {
  const duration = formatDuration(item.duration_seconds);
  const age = formatAge(item.published_at, now);
  const views = formatViews(item.view_count);
  const thumbnail = item.thumbnail_url;
  const color = channelColor(item.channel_id);

  return (
    <li
      className={cn(
        "group/card relative flex flex-col gap-3",
        (faded || item.watched) && "opacity-60",
      )}
    >
      {top}
      <div
        className={cn(
          "relative aspect-video overflow-hidden rounded-xl bg-secondary transition-[border-radius] group-hover/card:rounded-none",
          item.watched && "grayscale",
        )}
        style={thumbnail ? undefined : { backgroundColor: color }}
      >
        {thumbnail ? (
          <img
            src={thumbnail}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        ) : (
          <span
            aria-hidden="true"
            className="flex size-full items-center justify-center bg-linear-to-br from-white/10 to-black/30 text-7xl font-bold text-white/25"
          >
            {initial(item.channel_title)}
          </span>
        )}
        {duration && (
          <span className="absolute right-1.5 bottom-1.5 rounded bg-black/80 px-1 py-px text-xs font-medium text-white tabular-nums">
            {duration}
          </span>
        )}
        {overlay}
      </div>
      <div className="flex gap-3">
        <Avatar
          aria-hidden="true"
          className={cn("size-9", item.watched && "grayscale")}
        >
          {item.channel_thumbnail_url && (
            <AvatarImage
              src={avatarUrl(item.channel_thumbnail_url)}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          )}
          <AvatarFallback
            className="font-medium text-white"
            style={{ backgroundColor: color }}
          >
            {initial(item.channel_title)}
          </AvatarFallback>
        </Avatar>
        <div className="flex min-w-0 flex-1 flex-col">
          <h3 className="line-clamp-2 leading-snug font-medium">
            <Link
              to="/watch/$videoId"
              params={{ videoId: item.video_id }}
              className="outline-none before:absolute before:-inset-2 before:rounded-2xl focus-visible:before:ring-3 focus-visible:before:ring-ring/50"
            >
              {item.title}
            </Link>
          </h3>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {item.channel_title}
          </p>
          <p className="flex flex-wrap gap-x-1 text-sm text-muted-foreground">
            {[
              views,
              age && item.published_at && (
                <time dateTime={item.published_at} suppressHydrationWarning>
                  {age}
                </time>
              ),
            ]
              .filter(Boolean)
              .map((part, index) => (
                <span key={index} className="tabular-nums">
                  {index > 0 && "• "}
                  {part}
                </span>
              ))}
          </p>
        </div>
        {menu}
      </div>
    </li>
  );
}

/**
 * YouTube channel avatars come at full size (`=s0`); ask for one sized for
 * the card instead (2x its 36px).
 */
function avatarUrl(url: string): string {
  return url.replace(/=s\d+[^/]*$/, "=s72");
}

function initial(name: string): string {
  return name.trim().charAt(0).toUpperCase();
}
