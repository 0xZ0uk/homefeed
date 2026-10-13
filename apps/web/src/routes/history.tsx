import { useSuspenseQuery } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { AppHeader } from "#/components/AppHeader";
import { showsThumbnails, type DisplayPrefs } from "#/lib/display";
import { formatAge, formatDuration } from "#/lib/format";
import {
  HISTORY_QUERY_MAX_LENGTH,
  describeProgress,
  parseHistoryParams,
  progressFraction,
  type HistoryParams,
} from "#/lib/history";
import { displayPrefsQuery } from "#/server/display";
import { historyQuery, type HistoryEntry } from "#/server/history";

/**
 * What I've watched, most recent first, searchable by title and channel. Each
 * video links back to the watch page, which resumes where I left off.
 */
export const Route = createFileRoute("/history")({
  validateSearch: (search: Record<string, unknown>): HistoryParams =>
    parseHistoryParams(search),
  head: () => ({ meta: [{ title: "History · Homefeed" }] }),
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    await Promise.all([
      context.queryClient.ensureQueryData(displayPrefsQuery),
      context.queryClient.ensureQueryData(historyQuery(deps)),
    ]);
  },
  component: History,
});

function History() {
  const params = Route.useSearch();

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <h2 className="text-xl font-semibold">History</h2>
      {/* Remount when the URL changes so the field shows the current search. */}
      <HistorySearch key={params.q ?? ""} query={params.q ?? ""} />
      <Entries params={params} />
    </main>
  );
}

function HistorySearch({ query }: { query: string }) {
  const navigate = useNavigate({ from: "/history" });
  const [q, setQ] = useState(query);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void navigate({ search: parseHistoryParams({ q }) });
  }

  return (
    <form onSubmit={onSubmit} role="search" className="flex gap-2">
      <label htmlFor="history-query" className="sr-only">
        Search your history
      </label>
      <input
        id="history-query"
        type="search"
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="Search by title or channel"
        maxLength={HISTORY_QUERY_MAX_LENGTH}
        className="min-w-0 flex-1 rounded border px-3 py-2"
      />
      <button
        type="submit"
        className="rounded bg-black px-3 py-2 font-medium text-white"
      >
        Search
      </button>
    </form>
  );
}

function Entries({ params }: { params: HistoryParams }) {
  const { data: outcome } = useSuspenseQuery(historyQuery(params));
  const { data: display } = useSuspenseQuery(displayPrefsQuery);
  const page = params.page ?? 1;

  if (!outcome.ok) {
    return (
      <p role="alert" className="text-red-600">
        {outcome.message}
      </p>
    );
  }
  if (outcome.entries.length === 0) {
    return (
      <p className="text-gray-600">
        {params.q
          ? "Nothing you've watched matches. Try fewer words."
          : page > 1
            ? "No older videos."
            : "Nothing here yet. Videos you play show up here."}
      </p>
    );
  }
  return (
    <>
      <ol className="flex flex-col divide-y" aria-label="Watched videos">
        {outcome.entries.map((entry) => (
          <EntryRow key={entry.video_id} entry={entry} display={display} />
        ))}
      </ol>
      {(page > 1 || outcome.hasMore) && (
        <nav aria-label="History pages" className="flex gap-4">
          {page > 1 && (
            <Link
              to="/history"
              search={parseHistoryParams({ q: params.q, page: page - 1 })}
              className="underline"
            >
              Newer
            </Link>
          )}
          {outcome.hasMore && (
            <Link
              to="/history"
              search={parseHistoryParams({ q: params.q, page: page + 1 })}
              className="underline"
            >
              Older
            </Link>
          )}
        </nav>
      )}
    </>
  );
}

function EntryRow({
  entry,
  display,
}: {
  entry: HistoryEntry;
  display: DisplayPrefs;
}) {
  const duration = formatDuration(entry.duration);
  const thumbnails = showsThumbnails(display);
  const progress = describeProgress(entry);
  const fraction = progressFraction(entry);
  const params = { videoId: entry.video_id };

  return (
    <li className="flex gap-4 py-3">
      {thumbnails && (
        // Mouse-only; the title link is the one in the tab order.
        <Link
          to="/watch/$videoId"
          params={params}
          tabIndex={-1}
          aria-hidden="true"
          className="relative aspect-video w-40 shrink-0 overflow-hidden rounded bg-gray-200"
        >
          {entry.thumbnail_url && (
            <img
              src={entry.thumbnail_url}
              alt=""
              loading="lazy"
              className="size-full object-cover"
            />
          )}
          {duration && (
            <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-xs text-white tabular-nums">
              {duration}
            </span>
          )}
          {fraction !== null && (
            <span
              className="absolute bottom-0 left-0 h-1 bg-red-600"
              style={{ width: `${fraction * 100}%` }}
            />
          )}
        </Link>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="font-medium">
          <Link
            to="/watch/$videoId"
            params={params}
            className="hover:underline"
          >
            {entry.title ?? `Video ${entry.video_id}`}
          </Link>
        </h3>
        <p className="flex flex-wrap gap-x-2 text-sm text-gray-600">
          {entry.channel_title && <span>{entry.channel_title}</span>}
          {duration && !thumbnails && (
            <span className="tabular-nums">· {duration}</span>
          )}
          {entry.grade && <span>· Rated {entry.grade}</span>}
        </p>
        <p className="flex flex-wrap gap-x-2 text-sm text-gray-500">
          <span>
            Watched{" "}
            <time dateTime={entry.last_watched_at}>
              {formatAge(entry.last_watched_at) ?? "some time ago"}
            </time>
          </span>
          {progress && <span>· {progress}</span>}
        </p>
      </div>
    </li>
  );
}
