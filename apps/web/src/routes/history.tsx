import {
  useQuery,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { ScoreFace } from "#/components/ScoreFace";
import { ScoreScale } from "#/components/ScoreScale";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { formatAge, formatDuration } from "#/lib/format";
import {
  HISTORY_QUERY_MAX_LENGTH,
  afterRating,
  describeProgress,
  describeRated,
  isHistoryPageKey,
  neighbourOf,
  paramsWith,
  parseHistoryParams,
  progressFraction,
  type HistoryParams,
} from "#/lib/history";
import { SCORE_SCALE_HINT, scoreLabel, scoreText } from "#/lib/scores";
import { cn } from "#/lib/utils";
import {
  historyQuery,
  historySummaryQuery,
  type HistoryEntry,
  type HistoryOutcome,
} from "#/server/history";
import { saveRating } from "#/server/ratings";

/**
 * What I've watched, most recent first, searchable by title and channel. Each
 * video links back to the watch page, which resumes where I left off. The
 * "Unrated" filter lists what I watched but never rated, each with a scale to
 * rate it in place: rating drops it from the list, so several can be rated in
 * a row.
 */
export const Route = createFileRoute("/history")({
  validateSearch: (search: Record<string, unknown>): HistoryParams =>
    parseHistoryParams(search),
  head: () => ({ meta: [{ title: "History · Homefeed" }] }),
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    await Promise.all([
      context.queryClient.ensureQueryData(historyQuery(deps)),
      // The filter's count is a nicety: its failure must not fail the page.
      context.queryClient.prefetchQuery(historySummaryQuery),
    ]);
  },
  component: History,
});

function History() {
  const params = Route.useSearch();

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-xl font-semibold">History</h1>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Remount when the URL changes so the field shows the current search. */}
        <HistorySearch key={params.q ?? ""} params={params} />
        <UnratedFilter params={params} />
      </div>
      {/* Remount too, so a message about one list isn't left over in another. */}
      <Entries key={JSON.stringify(params)} params={params} />
    </AppShell>
  );
}

function HistorySearch({ params }: { params: HistoryParams }) {
  const navigate = useNavigate({ from: "/history" });
  const [q, setQ] = useState(params.q ?? "");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void navigate({ search: paramsWith(params, { q }) });
  }

  return (
    <form
      onSubmit={onSubmit}
      role="search"
      className="flex min-w-64 flex-1 gap-2"
    >
      <label htmlFor="history-query" className="sr-only">
        Search your history
      </label>
      <Input
        id="history-query"
        type="search"
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="Search by title or channel"
        maxLength={HISTORY_QUERY_MAX_LENGTH}
        className="h-10 flex-1 px-3"
      />
      <Button type="submit" size="lg" className="h-10 px-4">
        Search
      </Button>
    </form>
  );
}

/**
 * The chip that narrows the history to the videos still to rate, with how
 * many there are. Its state is in the URL; pressing it again shows everything.
 */
function UnratedFilter({ params }: { params: HistoryParams }) {
  const navigate = useNavigate({ from: "/history" });
  const { data: summary } = useQuery(historySummaryQuery);
  const active = Boolean(params.unrated);

  return (
    <Button
      type="button"
      variant="secondary"
      aria-pressed={active}
      onClick={() =>
        void navigate({ search: paramsWith(params, { unrated: !active }) })
      }
      className="h-10 shrink-0 gap-2 rounded-lg px-3 aria-pressed:bg-primary aria-pressed:text-primary-foreground"
    >
      {active && <Check aria-hidden="true" />}
      Unrated
      {summary && (
        <span className="rounded-full bg-current/15 px-1.5 text-xs tabular-nums">
          {summary.unrated}
        </span>
      )}
    </Button>
  );
}

/** The scale of a row of the unrated list, and what its owner does about a rating. */
interface RowRating {
  /** Hands over the face of the row's scale that takes focus (null when it goes). */
  scaleRef: (face: HTMLButtonElement | null) => void;
  /** The video was rated `score`; `byKeyboard` when the keyboard picked it. */
  onRated: (score: number, byKeyboard: boolean) => void;
}

function Entries({ params }: { params: HistoryParams }) {
  const queryClient = useQueryClient();
  const { data: outcome } = useSuspenseQuery(historyQuery(params));
  const statusRef = useRef<HTMLParagraphElement>(null);
  const [status, setStatus] = useState<string | null>(null);
  // The face of each row's scale that takes focus, by video, to move focus on.
  const faces = useRef(new Map<string, HTMLButtonElement>());
  const unrated = Boolean(params.unrated);
  const page = params.page ?? 1;

  /**
   * A video of the unrated list was rated and saved: leave it out of the list
   * and the count, say so, and keep a keyboard user's place. The cache is
   * updated by hand rather than refetched, which also settles any fetch
   * already under way before it can bring the video back.
   */
  function rated(entry: HistoryEntry, score: number, byKeyboard: boolean) {
    const listKey = historyQuery(params).queryKey;
    const current = queryClient.getQueryData(listKey);
    if (byKeyboard && current?.ok) {
      // The row is about to go: carry the keyboard to the next one, if any.
      const next = neighbourOf(current.entries, entry.video_id);
      const face = next && faces.current.get(next.video_id);
      if (face) face.focus();
      else statusRef.current?.focus();
    }
    const summary = queryClient.getQueryData(historySummaryQuery.queryKey);
    const remaining = summary ? Math.max(0, summary.unrated - 1) : null;
    setStatus(
      describeRated(entry.title ?? `Video ${entry.video_id}`, score, remaining),
    );
    void queryClient.cancelQueries({ queryKey: ["history"] }).then(() => {
      // Every cached page: the unrated lose the video, the rest show its rating.
      for (const unratedOnly of [true, false]) {
        queryClient.setQueriesData<HistoryOutcome>(
          {
            queryKey: ["history"],
            predicate: (query) => isHistoryPageKey(query.queryKey, unratedOnly),
          },
          (old): HistoryOutcome | undefined =>
            old?.ok
              ? {
                  ...old,
                  entries: afterRating(
                    old.entries,
                    entry.video_id,
                    score,
                    unratedOnly,
                  ),
                }
              : old,
        );
      }
      queryClient.setQueryData(historySummaryQuery.queryKey, (old) =>
        old ? { ...old, unrated: Math.max(0, old.unrated - 1) } : old,
      );
      // Refetch whatever is shown next, in case something else changed.
      void queryClient.invalidateQueries({
        queryKey: ["history"],
        refetchType: "none",
      });
    });
  }

  let results: ReactNode;
  if (!outcome.ok) {
    results = (
      <p role="alert" className="text-destructive">
        {outcome.message}
      </p>
    );
  } else if (outcome.entries.length === 0) {
    results = <NoEntries params={params} />;
  } else {
    results = (
      <>
        <div className="flex flex-col gap-3">
          {unrated && (
            <p className="text-sm text-muted-foreground">
              Pick a face to rate each video. {SCORE_SCALE_HINT}
            </p>
          )}
          <ol className="flex flex-col divide-y" aria-label="Watched videos">
            {outcome.entries.map((entry) => (
              <EntryRow
                key={entry.video_id}
                entry={entry}
                rating={
                  unrated
                    ? {
                        scaleRef: (face) => {
                          if (face) faces.current.set(entry.video_id, face);
                          else faces.current.delete(entry.video_id);
                        },
                        onRated: (score, byKeyboard) =>
                          rated(entry, score, byKeyboard),
                      }
                    : undefined
                }
              />
            ))}
          </ol>
        </div>
        {(page > 1 || outcome.hasMore) && (
          <nav aria-label="History pages" className="flex gap-4">
            {page > 1 && (
              <Link
                to="/history"
                search={paramsWith(params, { page: page - 1 })}
                className="underline"
              >
                Newer
              </Link>
            )}
            {outcome.hasMore && (
              <Link
                to="/history"
                search={paramsWith(params, { page: page + 1 })}
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

  return (
    <>
      {/*
        Focus moves here when the last video to rate leaves the list. It is
        there from the start, only out of sight until it has something to say,
        so that screen readers are listening when it does.
      */}
      <p
        ref={statusRef}
        role="status"
        tabIndex={-1}
        className={cn(
          "text-sm text-muted-foreground focus:outline-none",
          status ? "-mt-3" : "sr-only",
        )}
      >
        {status}
      </p>
      {results}
    </>
  );
}

/** Why a page of the history is empty, and how to get out of it. */
function NoEntries({ params }: { params: HistoryParams }) {
  const page = params.page ?? 1;
  if (params.q) {
    return (
      <p className="text-muted-foreground">
        {params.unrated ? "No unrated videos match" : "No watched videos match"}{" "}
        “{params.q}”.{" "}
        <Link
          to="/history"
          search={paramsWith(params, { q: "" })}
          className="text-foreground underline"
        >
          Clear search
        </Link>
      </p>
    );
  }
  if (params.unrated) {
    return (
      <p className="text-muted-foreground">
        {page > 1
          ? "No more unrated videos."
          : "You've rated everything you watched."}{" "}
        <Link
          to="/history"
          search={paramsWith(params, { unrated: false })}
          className="text-foreground underline"
        >
          Show all history
        </Link>
      </p>
    );
  }
  return (
    <p className="text-muted-foreground">
      {page > 1
        ? "No older videos."
        : "Nothing here yet. Videos you play show up here."}
    </p>
  );
}

/**
 * One watched video. With `rating`, a scale under its details rates it: beside
 * the thumbnail on wider screens, the row's full width on narrow ones.
 */
function EntryRow({
  entry,
  rating,
}: {
  entry: HistoryEntry;
  rating?: RowRating;
}) {
  const duration = formatDuration(entry.duration);
  const progress = describeProgress(entry);
  const fraction = progressFraction(entry);
  const linkParams = { videoId: entry.video_id };
  const title = entry.title ?? `Video ${entry.video_id}`;

  return (
    <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-2 py-3 sm:gap-x-4">
      {/* Mouse-only; the title link is the one in the tab order. */}
      <Link
        to="/watch/$videoId"
        params={linkParams}
        tabIndex={-1}
        aria-hidden="true"
        className="relative aspect-video w-32 overflow-hidden rounded-lg bg-secondary sm:w-40"
      >
        {entry.thumbnail_url && (
          <img
            src={entry.thumbnail_url}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        )}
        {duration && (
          <span className="absolute right-1 bottom-1 rounded bg-black/80 px-1 text-xs text-white tabular-nums">
            {duration}
          </span>
        )}
        {fraction !== null && (
          <span
            className="absolute bottom-0 left-0 h-1 bg-brand"
            style={{ width: `${fraction * 100}%` }}
          />
        )}
      </Link>
      <div className="flex min-w-0 flex-col gap-1">
        <h2 className="font-medium break-words">
          <Link
            to="/watch/$videoId"
            params={linkParams}
            className="hover:underline"
          >
            {title}
          </Link>
        </h2>
        <p className="flex flex-wrap gap-x-2 text-sm text-muted-foreground">
          {entry.channel_title && <span>{entry.channel_title}</span>}
          {entry.score != null && (
            <span className="inline-flex items-center gap-1">
              · Rated
              <ScoreFace score={entry.score} filled className="size-4" />
              <span aria-hidden="true">{scoreLabel(entry.score)}</span>
              <span className="sr-only">{scoreText(entry.score)}</span>
            </span>
          )}
        </p>
        <p className="flex flex-wrap gap-x-2 text-sm text-muted-foreground">
          <span>
            Watched{" "}
            <time dateTime={entry.last_watched_at}>
              {formatAge(entry.last_watched_at) ?? "some time ago"}
            </time>
          </span>
          {progress && <span>· {progress}</span>}
        </p>
      </div>
      {rating && (
        <div className="col-span-2 min-w-0 sm:col-span-1 sm:col-start-2">
          <RateEntry
            entry={entry}
            title={title}
            scaleRef={rating.scaleRef}
            onRated={rating.onRated}
          />
        </div>
      )}
    </li>
  );
}

/**
 * A compact scale that rates a watched video where it is listed. Picking a
 * face saves it at once and tells the list, which drops the row. While it
 * saves the scale is disabled; if that fails, the row says so and the face
 * can be picked again.
 */
function RateEntry({
  entry,
  title,
  scaleRef,
  onRated,
}: {
  entry: HistoryEntry;
  title: string;
  scaleRef: (face: HTMLButtonElement | null) => void;
  onRated: (score: number, byKeyboard: boolean) => void;
}) {
  const wrapper = useRef<HTMLDivElement>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pick(score: number) {
    if (saving) return;
    // Asked before the scale is disabled: only the keyboard shows a focus ring.
    const byKeyboard = wrapper.current?.querySelector(":focus-visible") != null;
    setPicked(score);
    setSaving(true);
    setError(null);
    try {
      await saveRating({ data: { videoId: entry.video_id, score } });
    } catch {
      setError("Couldn't save the rating. Try again.");
      setPicked(null);
      setSaving(false);
      return;
    }
    onRated(score, byKeyboard);
  }

  return (
    <div ref={wrapper} className="flex flex-col gap-1">
      <ScoreScale
        compact
        value={picked}
        onPick={(score) => void pick(score)}
        label={`Rate “${title}”`}
        disabled={saving}
        buttonRef={scaleRef}
        className="w-full max-w-md"
      />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
