import type { ScoreBreakdownOut } from "@homefeed/api-client";
import { Link } from "@tanstack/react-router";
import {
  CircleCheck,
  Compass,
  CornerDownRight,
  EyeOff,
  Globe,
  Hash,
  Layers,
  Link2,
  Network,
  Pin,
  Rss,
  Search,
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
  /** How its score was made, for the reason's details. */
  breakdown?: ScoreBreakdownOut;
  /** The candidate source that found it, for the reason's icon. */
  source?: string | null;
  /** Picked to explore a channel I hardly know. */
  is_exploration?: boolean;
  /** From a channel I pinned. */
  is_pinned?: boolean;
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

/** Icons of the sources a reason can start from; others get an arrow. */
const SOURCE_ICONS: Record<string, LucideIcon> = {
  subscription: Rss,
  related: Link2,
  saved_search: Search,
  channel_graph: Network,
  tag: Hash,
  external: Globe,
};

/**
 * A label over the thumbnail, as the length is: white on a dark plate, so it
 * reads on any picture.
 */
export const MEDIA_BADGE =
  "inline-flex max-w-full items-center gap-1 rounded bg-black/80 px-1.5 py-px text-xs font-medium text-white";

/**
 * One video: its topic tags, then its thumbnail (or, when it has none, a
 * placeholder in the channel's colour) with its length, what it is (watched,
 * new to me, a deep dive, likely clickbait) and an (i) button that opens why
 * it's here with its score breakdown; then the channel's avatar beside title,
 * channel and stats, a menu of actions, and a row of quick actions. The title
 * is the card's one link, stretched over the whole card; the controls and
 * links above it are raised over that.
 *
 * A watched video keeps its text at full strength: its thumbnail is greyed
 * out, with a bar along the bottom for how far I got, and a "Watched" label
 * says so in words. A dismissed one (shown on past feeds) says "Dismissed".
 * Where the page around the card already says the channel is new to me (the
 * "New to you" lane, Discovery), `markNew={false}` leaves that label off.
 */
export function VideoCard({
  video: item,
  now,
  overlay,
  menu,
  rate,
  actions,
  markNew = true,
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
  /** Shown at the bottom: the card's quick actions. */
  actions?: ReactNode;
  /** Label a video from a channel I don't follow "New to you". */
  markNew?: boolean;
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
  const isNew = markNew && item.channel_subscribed === false;
  const hasBadges =
    item.watched || !!item.dismissed_at || isNew || flags.length > 0;

  return (
    // Four rows, always (tags, thumbnail, title, actions), shared with the
    // cards beside it through the list's grid, so thumbnails and action rows
    // line up across a row however many lines each card's tags and title take.
    <li
      className={cn(
        "group/card relative row-span-4 grid grid-rows-subgrid gap-y-3",
        className,
      )}
    >
      <div className="-mb-1 flex flex-wrap content-end gap-x-3">
        {tags.map((tag) => (
          <Link
            key={tag.slug}
            to="/tags/$slug"
            params={{ slug: tag.slug }}
            className="relative z-10 -mx-1 inline-block rounded-md px-1 text-[0.8125rem] leading-6 break-words text-muted-foreground outline-none hover:text-foreground hover:underline focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span aria-hidden="true">#</span>
            {tag.label}
          </Link>
        ))}
      </div>
      <div
        className="relative aspect-video overflow-hidden rounded-xl bg-secondary"
        style={thumbnail ? undefined : { backgroundColor: color }}
      >
        {thumbnail ? (
          <img
            src={thumbnail}
            alt=""
            loading="lazy"
            className={cn(
              "size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10",
              item.watched && "grayscale",
            )}
          />
        ) : (
          <span
            aria-hidden="true"
            className={cn(
              "flex size-full items-center justify-center bg-linear-to-br from-white/10 to-black/30 text-7xl font-bold text-white/25",
              item.watched && "grayscale",
            )}
          >
            {initial(item.channel_title)}
          </span>
        )}
        {hasBadges && (
          <div
            className={cn(
              "absolute start-1.5 top-1.5 flex flex-wrap items-start gap-1",
              // Clear of the (i) button in the other corner.
              item.explanation ? "end-10" : "end-1.5",
            )}
          >
            {item.watched && (
              <span className={MEDIA_BADGE}>
                <CircleCheck aria-hidden="true" className="size-3.5 shrink-0" />
                Watched
                {progress !== null && (
                  <span className="sr-only">, {progress}% of it</span>
                )}
              </span>
            )}
            {item.watched && rate}
            {item.dismissed_at && (
              <span className={MEDIA_BADGE}>
                <EyeOff aria-hidden="true" className="size-3.5 shrink-0" />
                {dismissedLabel(item.dismiss_reason)}
              </span>
            )}
            {isNew && (
              <span className={MEDIA_BADGE}>
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-full bg-brand forced-colors:bg-[CanvasText]"
                />
                New to you
              </span>
            )}
            {flags.map((flag) => {
              const Icon = FLAG_ICONS[flag];
              return (
                <span key={flag} className={MEDIA_BADGE}>
                  <Icon
                    aria-hidden="true"
                    className={cn(
                      "size-3.5 shrink-0",
                      flag === "clickbait" && "text-overlay-warning",
                    )}
                  />
                  {CARD_FLAG_LABELS[flag]}
                </span>
              );
            })}
          </div>
        )}
        {item.explanation && (
          <WhyThisPopover
            title={item.title}
            explanation={item.explanation}
            breakdown={item.breakdown}
            className="absolute end-1.5 top-1.5"
          >
            <Reason video={item} explanation={item.explanation} />
          </WhyThisPopover>
        )}
        {duration && (
          <span
            className={cn(
              MEDIA_BADGE,
              "absolute end-1.5 bottom-1.5 px-1 tabular-nums",
            )}
          >
            {/* The clock reading for the eye, the length in words for a
                screen reader. */}
            <span aria-hidden={length ? true : undefined}>{duration}</span>
            {length && <span className="sr-only">{length}</span>}
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
          {/* Channel, views and age on one line. Each part starts with its
              dot, and the row is pulled back by a dot's width and clipped,
              so a part that wraps to a new line doesn't start with one. */}
          <p className="mt-1 overflow-hidden text-sm text-muted-foreground">
            <span className="-ms-3 flex flex-wrap">
              {[
                <span key="channel" className="truncate">
                  {item.channel_title}
                </span>,
                views && (
                  <span key="views" className="tabular-nums">
                    {views}
                  </span>
                ),
                age && item.published_at && (
                  <time
                    key="age"
                    dateTime={item.published_at}
                    suppressHydrationWarning
                    className="tabular-nums"
                  >
                    {age}
                  </time>
                ),
              ]
                .filter(Boolean)
                .map((part, index) => (
                  <span key={index} className="flex max-w-full min-w-0">
                    <span
                      aria-hidden="true"
                      className="w-3 shrink-0 text-center"
                    >
                      ·
                    </span>
                    {part}
                  </span>
                ))}
            </span>
          </p>
        </div>
        {menu}
      </div>
      <div className="ps-12">{actions}</div>
    </li>
  );
}

/**
 * A card's reason: an icon for where the video came from (a compass, in the
 * brand colour, for a channel being explored), then the reason with its first
 * part, the source, in medium weight.
 */
function Reason({
  video,
  explanation,
}: {
  video: CardVideo;
  explanation: string;
}) {
  const Icon = video.is_exploration
    ? Compass
    : video.is_pinned
      ? Pin
      : ((video.source ? SOURCE_ICONS[video.source] : undefined) ??
        CornerDownRight);
  const [lead, ...rest] = explanation.split(" · ");
  return (
    <>
      <Icon
        aria-hidden="true"
        className={cn(
          "mt-px size-4 shrink-0",
          video.is_exploration ? "text-brand" : "text-muted-foreground",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="font-medium">{lead}</span>
        {rest.length > 0 && ` · ${rest.join(" · ")}`}
      </span>
    </>
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
