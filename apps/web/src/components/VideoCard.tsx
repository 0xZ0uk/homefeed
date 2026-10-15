import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { Link } from "@tanstack/react-router";
import {
  CircleCheck,
  CornerDownRight,
  EyeOff,
  Layers,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "#/components/ui/avatar";
import { WhyThisPopover } from "#/components/WhyThisPopover";
import {
  CARD_FLAG_LABELS,
  cardFlags,
  dismissedLabel,
  formatLength,
  progressPercent,
  type CardFlag,
  type LlmScores,
} from "#/lib/card";
import { channelColor } from "#/lib/feed-grid";
import { formatAge, formatDuration, formatViews } from "#/lib/format";
import { cn } from "#/lib/utils";

/**
 * What a video card shows. Tag-page and channel-page videos have the first
 * part; feed and Discovery videos have the rest too, which a card shows when
 * it's there.
 */
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
  /** Why it's here: the card's reason line. */
  explanation?: string;
  /** How its score was made, for the reason's "Details". */
  breakdown?: ScoreBreakdownOut;
  /** False for a channel I don't subscribe to; unknown shows nothing. */
  channel_subscribed?: boolean;
  /** Up to three topic tags, each linking to its page. */
  tags?: { slug: string; label: string }[];
  llm?: LlmScores | null;
  /** How far through it I got, 0 to 1: the bar along the thumbnail. */
  watched_fraction?: number | null;
  /** Set when dismissed: a past feed shows dismissed items, labelled. */
  dismissed_at?: string | null;
  dismiss_reason?: string | null;
}

/** Icons of the flags a card shows next to their words. */
const FLAG_ICONS: Record<CardFlag, LucideIcon> = {
  "deep-dive": Layers,
  clickbait: TriangleAlert,
};

/**
 * A small rounded label on a card, one line high however long its text (which is
 * cut short, as a tag's can be long). A transparent border lets a link take a
 * visible one for its focus ring, as buttons do.
 */
const CHIP =
  "inline-flex h-6 max-w-full items-center gap-1.5 rounded-full border border-transparent bg-secondary px-2.5 text-[0.8125rem] whitespace-nowrap text-secondary-foreground";

/**
 * One video: its thumbnail (or, when it has none, a placeholder in the
 * channel's colour), then the channel's avatar beside title, channel with
 * length, stats and a menu of actions. Below that come what helps decide:
 * the reason it's here with a "Details" button, chips (new to me, topic tags,
 * deep dive, likely clickbait) and a row of quick actions. The title is the
 * card's one link, stretched over the whole card; the controls and links
 * above it are raised over that.
 *
 * A watched video keeps its text at full strength: its thumbnail is greyed
 * out, with a bar along the bottom for how far I got, and a "Watched" label
 * says so in words. A dismissed one (shown on past feeds) says "Dismissed".
 */
export function VideoCard({
  video: item,
  now,
  overlay,
  menu,
  rate,
  actions,
  className,
}: {
  video: CardVideo;
  now: Date;
  /** Shown over the thumbnail. */
  overlay?: ReactNode;
  /** Shown at the end of the title row. */
  menu?: ReactNode;
  /** Shown with the "Watched" label: the button to rate the video. */
  rate?: ReactNode;
  /** Shown under the chips: the card's quick actions. */
  actions?: ReactNode;
  className?: string;
}) {
  const duration = formatDuration(item.duration_seconds);
  const length = formatLength(item.duration_seconds);
  const age = formatAge(item.published_at, now);
  const views = formatViews(item.view_count);
  const thumbnail = item.thumbnail_url;
  const color = channelColor(item.channel_id);
  const progress = progressPercent(item.watched_fraction);
  const flags = cardFlags(item.llm);
  const tags = item.tags ?? [];
  const isNew = item.channel_subscribed === false;

  return (
    <li className={cn("group/card relative flex flex-col gap-3", className)}>
      <div
        className={cn(
          "relative aspect-video overflow-hidden rounded-xl bg-secondary",
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
        {progress !== null && (
          <div
            aria-hidden="true"
            className="absolute inset-x-0 bottom-0 h-1 bg-black/70"
          >
            <div
              className="h-full bg-white forced-colors:bg-[Highlight]"
              style={{ width: `${progress}%` }}
            />
          </div>
        )}
        {overlay}
      </div>
      <div className="flex gap-3">
        <Avatar aria-hidden="true" className="size-9">
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
          <p className="mt-1 flex gap-x-1 text-sm text-muted-foreground">
            <span className="truncate">{item.channel_title}</span>{" "}
            {length && <span className="shrink-0">· {length}</span>}
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
          {(item.watched || item.dismissed_at) && (
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              {item.watched && (
                <span className="inline-flex items-center gap-1">
                  <CircleCheck aria-hidden="true" className="size-4" />
                  Watched
                  {progress !== null && (
                    <span className="sr-only">, {progress}% of it</span>
                  )}
                </span>
              )}
              {item.watched && rate}
              {item.dismissed_at && (
                <span className="inline-flex items-center gap-1">
                  <EyeOff aria-hidden="true" className="size-4" />
                  {dismissedLabel(item.dismiss_reason)}
                </span>
              )}
            </p>
          )}
        </div>
        {menu}
      </div>
      {item.explanation && (
        <div className="flex items-baseline gap-x-1">
          <p className="line-clamp-2 min-w-0 text-sm leading-snug">
            <CornerDownRight
              aria-hidden="true"
              className="mr-1 inline size-4 align-text-bottom text-muted-foreground"
            />
            {item.explanation}
          </p>
          {item.breakdown && (
            <WhyThisPopover
              title={item.title}
              explanation={item.explanation}
              breakdown={item.breakdown}
            />
          )}
        </div>
      )}
      {(isNew || tags.length > 0 || flags.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {isNew && (
            <span className={CHIP}>
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-full bg-brand forced-colors:bg-[CanvasText]"
              />
              New to you
            </span>
          )}
          {tags.map((tag) => (
            <Link
              key={tag.slug}
              to="/tags/$slug"
              params={{ slug: tag.slug }}
              className={cn(
                CHIP,
                "relative z-10 outline-none hover:bg-accent focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
              )}
            >
              <span className="truncate">{tag.label}</span>
            </Link>
          ))}
          {flags.map((flag) => {
            const Icon = FLAG_ICONS[flag];
            return (
              <span key={flag} className={CHIP}>
                <Icon aria-hidden="true" className="size-3.5 shrink-0" />
                {CARD_FLAG_LABELS[flag]}
              </span>
            );
          })}
        </div>
      )}
      {actions}
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
