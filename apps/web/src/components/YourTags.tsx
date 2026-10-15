import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { EyeOff, Tag, type LucideIcon } from "lucide-react";

import {
  mutedTags,
  subscribedTags,
  type SidebarTag,
} from "#/lib/tag-subscriptions";
import { tagSubscriptionsQuery } from "#/server/tag-subscriptions";

/**
 * The tags you follow and the ones you muted, as links to their pages: the
 * part of Explore that used to sit in the guide. Following a tag boosts its
 * videos in the feed; muting one pushes them down.
 */
export function YourTags() {
  const { data, isPending, isError, refetch } = useQuery(tagSubscriptionsQuery);
  const subscribed = subscribedTags(data ?? []);
  const muted = mutedTags(data ?? []);

  return (
    <section
      aria-labelledby="your-tags-heading"
      className="flex flex-col gap-4"
    >
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline justify-between gap-4">
          <h2 id="your-tags-heading" className="text-lg font-semibold">
            Your tags
          </h2>
          <Link
            to="/subscriptions"
            search={{ tab: "tags" }}
            className="rounded-sm py-1 text-sm underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            Manage tags
          </Link>
        </div>
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          Following a tag boosts its videos in your feed; muting one pushes them
          down.
        </p>
      </div>
      {isError ? (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p>Couldn't load your tags. The API may be down.</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="underline"
          >
            Try again
          </button>
        </div>
      ) : isPending ? (
        <p className="text-sm text-muted-foreground">Loading your tags…</p>
      ) : subscribed.length === 0 && muted.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-muted-foreground">
          You haven't followed or muted any tags yet. Open a tag on a video to
          follow it, or choose Manage tags to browse them all.
        </p>
      ) : (
        <>
          <TagList
            heading="Subscribed"
            label="Subscribed tags"
            tags={subscribed}
            icon={Tag}
          />
          <TagList
            heading="Muted"
            label="Muted tags"
            tags={muted}
            icon={EyeOff}
          />
        </>
      )}
    </section>
  );
}

/** One group of tags: a heading with how many, and a wrapping row of links.
 * Nothing at all when the group is empty. */
function TagList({
  heading,
  label,
  tags,
  icon: Icon,
}: {
  heading: string;
  label: string;
  tags: SidebarTag[];
  icon: LucideIcon;
}) {
  if (tags.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium text-muted-foreground tabular-nums">
        {heading} ({tags.length})
      </h3>
      <ul aria-label={label} className="flex flex-wrap gap-2">
        {tags.map(({ slug, label }) => (
          <li key={slug} className="min-w-0">
            <Link
              to="/tags/$slug"
              params={{ slug }}
              className="flex h-9 max-w-full items-center gap-2 rounded-lg bg-secondary px-3 text-sm outline-none hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Icon aria-hidden="true" className="size-4 shrink-0" />
              <span className="min-w-0 truncate">{label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
