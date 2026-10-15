import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "#/components/ui/button";
import { formatDuration } from "#/lib/format";
import { cn } from "#/lib/utils";
import {
  PREVIEW_UPLOADS,
  channelPreviewQuery,
  type UploadOut,
} from "#/server/discover";

/**
 * A "Preview" disclosure for sampling a channel before subscribing: opening it
 * loads the channel's latest uploads (kept for a few minutes) and shows them as
 * small linked thumbnails with title and length. Nothing is fetched until it is
 * opened.
 */
export function ChannelPreview({
  channelId,
  title,
}: {
  channelId: string;
  title: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const uploads = useQuery({
    ...channelPreviewQuery(channelId),
    enabled: open,
  });

  // Rendered empty from the start, so what it says once the preview is opened is announced.
  const announcement = !open
    ? ""
    : uploads.isPending
      ? `Loading the latest uploads of ${title}.`
      : uploads.isSuccess
        ? `Showing the latest uploads of ${title}.`
        : "";

  return (
    <div className="flex flex-col gap-3">
      <Button
        type="button"
        variant="ghost"
        size="lg"
        className="-ml-2 self-start px-3"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Preview ${title}`}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        Preview
        <ChevronDown
          className={cn(
            "transition-transform duration-150 motion-reduce:transition-none",
            open && "rotate-180",
          )}
        />
      </Button>
      <div id={panelId} hidden={!open}>
        {open && (
          <PreviewBody
            title={title}
            uploads={uploads.data}
            pending={uploads.isPending}
            failed={uploads.isError}
            retry={() => void uploads.refetch()}
          />
        )}
      </div>
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </div>
  );
}

function PreviewBody({
  title,
  uploads,
  pending,
  failed,
  retry,
}: {
  title: string;
  uploads: UploadOut[] | undefined;
  pending: boolean;
  failed: boolean;
  retry: () => void;
}) {
  if (failed) {
    return (
      <div
        role="alert"
        className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm"
      >
        <p className="text-destructive">
          Couldn't load the latest uploads of {title}.
        </p>
        <button
          type="button"
          onClick={retry}
          className="rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          Try again
        </button>
      </div>
    );
  }
  if (pending) {
    return (
      <ul aria-hidden="true" className="grid gap-3 sm:grid-cols-3">
        {Array.from({ length: PREVIEW_UPLOADS }, (_, index) => (
          <li key={index} className="flex gap-3 sm:flex-col">
            <span className="block aspect-video w-28 shrink-0 animate-pulse rounded-lg bg-secondary motion-reduce:animate-none sm:w-full" />
            <span className="block h-4 w-full animate-pulse rounded bg-secondary motion-reduce:animate-none" />
          </li>
        ))}
      </ul>
    );
  }
  if (!uploads || uploads.length === 0) {
    return <p className="text-sm text-muted-foreground">No uploads to show.</p>;
  }
  return (
    <ul
      aria-label={`Latest uploads of ${title}`}
      className="grid gap-3 sm:grid-cols-3"
    >
      {uploads.map((video) => (
        <li key={video.id}>
          <PreviewVideo video={video} />
        </li>
      ))}
    </ul>
  );
}

function PreviewVideo({ video }: { video: UploadOut }) {
  const length = formatDuration(video.duration_seconds);

  return (
    <Link
      to="/watch/$videoId"
      params={{ videoId: video.id }}
      className="group flex gap-3 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50 sm:flex-col"
    >
      <span className="relative block aspect-video w-28 shrink-0 overflow-hidden rounded-lg bg-secondary sm:w-full">
        {video.thumbnail_url && (
          <img
            src={video.thumbnail_url}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            className="size-full object-cover"
          />
        )}
        {length && (
          <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 py-px text-xs font-medium text-white tabular-nums">
            {length}
          </span>
        )}
      </span>
      <span className="line-clamp-2 text-sm leading-snug font-medium break-words group-hover:underline">
        {video.title}
      </span>
    </Link>
  );
}
