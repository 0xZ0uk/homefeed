import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  Bookmark,
  EllipsisVertical,
  ListMinus,
  ListPlus,
  Search as SearchIcon,
  SlidersHorizontal,
} from "lucide-react";
import { useState, type FormEvent } from "react";

import { AppShell } from "#/components/AppShell";
import { QueueStatus, useQueueToggle } from "#/components/QueueButton";
import { Avatar, AvatarFallback } from "#/components/ui/avatar";
import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import { Input } from "#/components/ui/input";
import { channelColor } from "#/lib/feed-grid";
import { formatDuration, formatViews } from "#/lib/format";
import {
  DURATIONS,
  QUERY_MAX_LENGTH,
  SCHEDULES,
  SORTS,
  UPLOAD_DATES,
  parseSearchParams,
  type Schedule,
  type SearchParams,
} from "#/lib/search";
import { cn } from "#/lib/utils";
import { saveSearch, savedSearchesQuery } from "#/server/saved-searches";
import { searchQuery, type SearchResult } from "#/server/search";

/**
 * Search YouTube, after YouTube's results page: the query lives in the
 * masthead's search box, chips narrow by length and a menu holds the other
 * filters. Saving a search makes its results flow into the candidates on a
 * schedule. Results are one fixed page: no "load more".
 */
export const Route = createFileRoute("/search")({
  validateSearch: (search: Record<string, unknown>): SearchParams =>
    parseSearchParams(search),
  head: () => ({ meta: [{ title: "Search · Homefeed" }] }),
  loaderDeps: ({ search }) => search,
  loader: async ({ context, deps }) => {
    await Promise.all([
      deps.q ? context.queryClient.ensureQueryData(searchQuery(deps)) : null,
    ]);
  },
  component: Search,
});

function Search() {
  const params = Route.useSearch();

  return (
    <AppShell className="flex max-w-5xl flex-col gap-4">
      {/* The masthead's search box is hidden on narrow screens. */}
      <MobileSearchForm key={params.q} query={params.q ?? ""} />
      {params.q ? (
        <>
          <h2 className="sr-only">Results for “{params.q}”</h2>
          <Toolbar params={params} />
          <Results params={params} />
        </>
      ) : (
        <div className="flex flex-col gap-2 py-16 text-center">
          <h2 className="text-xl font-semibold">Search YouTube</h2>
          <p className="mx-auto max-w-prose text-pretty text-muted-foreground">
            Find videos on YouTube. Save a search to have its newest videos
            considered for your daily feed.
          </p>
        </div>
      )}
    </AppShell>
  );
}

function MobileSearchForm({ query }: { query: string }) {
  const navigate = useNavigate({ from: "/search" });
  const [q, setQ] = useState(query);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void navigate({ search: parseSearchParams({ q }) });
  }

  return (
    <form role="search" onSubmit={onSubmit} className="flex gap-2 sm:hidden">
      <Input
        type="search"
        value={q}
        onChange={(event) => setQ(event.target.value)}
        placeholder="hand plane restoration"
        aria-label="Search YouTube"
        maxLength={QUERY_MAX_LENGTH}
        required
        className="h-10 rounded-full pl-4 text-base"
      />
      <Button
        type="submit"
        variant="secondary"
        size="icon-lg"
        aria-label="Search"
        className="size-10"
      >
        <SearchIcon className="size-5" />
      </Button>
    </form>
  );
}

const LENGTH_CHIPS = [{ value: undefined, label: "All" }, ...DURATIONS];

/**
 * Chips for the length, then the other filters and saving the search. Every
 * change applies at once, as a new URL.
 */
function Toolbar({ params }: { params: SearchParams }) {
  const navigate = useNavigate({ from: "/search" });
  const save = useSaveSearch(params);
  // From the latest URL, not `params`: those are stale while the previous
  // change's results still load.
  const apply = (change: Partial<SearchParams>) =>
    navigate({
      search: (latest) => parseSearchParams({ ...latest, ...change }),
    });

  return (
    <>
      <div className="sticky top-14 z-30 -mx-1 flex items-center gap-3 bg-background px-1 py-3">
        <div
          role="group"
          aria-label="Filter by length"
          className="flex min-w-0 flex-1 gap-3 overflow-x-auto"
        >
          {LENGTH_CHIPS.map(({ value, label }) => (
            <Button
              key={label}
              type="button"
              variant="secondary"
              aria-pressed={params.duration === value}
              onClick={() => void apply({ duration: value })}
              className="shrink-0 rounded-lg px-3 aria-pressed:bg-primary aria-pressed:text-primary-foreground"
            >
              {label}
            </Button>
          ))}
        </div>
        <FiltersMenu params={params} onChange={apply} />
        <SaveSearchMenu save={save} />
      </div>
      <SaveSearchStatus save={save} />
    </>
  );
}

/** Upload date and sort, the filters that don't fit the chips. */
function FiltersMenu({
  params,
  onChange,
}: {
  params: SearchParams;
  onChange: (change: Partial<SearchParams>) => void;
}) {
  const applied = [params.upload_date, params.sort].filter(Boolean).length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" className="shrink-0 rounded-lg px-3" />}
        aria-label={applied ? `Filters, ${applied} applied` : "Filters"}
      >
        <SlidersHorizontal aria-hidden="true" />
        <span className="hidden sm:inline">Filters</span>
        {applied > 0 && (
          <span
            aria-hidden="true"
            className="flex size-5 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground tabular-nums"
          >
            {applied}
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52 py-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3">Upload date</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={params.upload_date ?? ""}
            onValueChange={(value) =>
              onChange({
                upload_date: UPLOAD_DATES.find((d) => d.value === value)?.value,
              })
            }
          >
            {[{ value: "", label: "Any time" }, ...UPLOAD_DATES].map(
              ({ value, label }) => (
                <DropdownMenuRadioItem
                  key={label}
                  value={value}
                  className="px-3 py-2"
                >
                  {label}
                </DropdownMenuRadioItem>
              ),
            )}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator className="my-2" />
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3">Sort by</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={params.sort ?? "relevance"}
            onValueChange={(value) =>
              onChange({ sort: SORTS.find((s) => s.value === value)?.value })
            }
          >
            {SORTS.map(({ value, label }) => (
              <DropdownMenuRadioItem
                key={value}
                value={value}
                className="px-3 py-2"
              >
                {label}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Saving a search, filters included, to run daily or weekly. */
function useSaveSearch(params: SearchParams) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (schedule: Schedule) =>
      saveSearch({ data: { params, schedule } }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: savedSearchesQuery.queryKey,
      }),
  });
}

type SaveSearch = ReturnType<typeof useSaveSearch>;

const SAVE_SCHEDULES = SCHEDULES.filter((s) => s.value !== "paused");

/**
 * Save this search to be checked daily or weekly; its newest results become
 * candidates for the feed.
 */
function SaveSearchMenu({ save }: { save: SaveSearch }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            disabled={save.isPending}
            className="shrink-0 rounded-lg px-3"
          />
        }
      >
        <Bookmark
          aria-hidden="true"
          className={cn(save.data?.ok && "fill-current")}
        />
        <span className="max-sm:sr-only">
          {save.isPending ? "Saving…" : "Save search"}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60 py-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3">
            Check it for new videos
          </DropdownMenuLabel>
          {SAVE_SCHEDULES.map(({ value, label }) => (
            <DropdownMenuItem
              key={value}
              onClick={() => save.mutate(value)}
              className="px-3 py-2"
            >
              {label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** How saving the search went, announced politely below the toolbar. */
function SaveSearchStatus({ save }: { save: SaveSearch }) {
  const result = save.data;
  return (
    <p role="status" className="-mt-3 text-sm empty:hidden">
      {save.isError && (
        <span className="text-destructive">
          Couldn't save the search. Try again later.
        </span>
      )}
      {result?.ok === false && (
        <span className="text-destructive">{result.message}</span>
      )}
      {result?.ok === true && (
        <span className="text-muted-foreground">
          {result.created
            ? "Saved. Its newest videos will be considered for your feed. "
            : "This search is already saved. "}
          <Link
            to="/curation"
            search={{ tab: "searches" }}
            className="underline"
          >
            Manage saved searches
          </Link>
        </span>
      )}
    </p>
  );
}

function Results({ params }: { params: SearchParams }) {
  const navigate = useNavigate({ from: "/search" });
  const { data: outcome } = useSuspenseQuery(searchQuery(params));
  const filtered = Boolean(
    params.duration || params.upload_date || params.sort,
  );

  if (!outcome.ok) {
    return (
      <p role="alert" className="py-16 text-center text-destructive">
        {outcome.message}
      </p>
    );
  }
  if (outcome.results.length === 0) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="font-medium">No results for “{params.q}”</p>
        <p className="text-muted-foreground">
          {filtered
            ? "Try fewer words, or clear the filters."
            : "Try fewer or different words."}
        </p>
        {filtered && (
          <Button
            variant="secondary"
            onClick={() =>
              void navigate({ search: parseSearchParams({ q: params.q }) })
            }
          >
            Clear filters
          </Button>
        )}
      </div>
    );
  }
  return (
    <ol className="flex flex-col gap-4" aria-label="Search results">
      {outcome.results.map((result) => (
        <ResultRow key={result.id} result={result} />
      ))}
    </ol>
  );
}

/**
 * One result: a large thumbnail beside its title, views, channel and the start
 * of its description, with a menu to queue it. The title is the row's one
 * link, stretched over the whole row; the menu sits above it.
 */
function ResultRow({ result }: { result: SearchResult }) {
  const queue = useQueueToggle(result.id);
  const duration = formatDuration(result.duration_seconds);
  const views = formatViews(result.view_count);
  const color = channelColor(result.channel_id);
  const live = result.live_status === "is_live";
  const upcoming = result.live_status === "is_upcoming";

  return (
    <li className="group/row relative flex flex-col gap-3 sm:flex-row sm:gap-4">
      <div
        className="relative aspect-video w-full shrink-0 overflow-hidden rounded-xl bg-secondary sm:w-64 md:w-80 lg:w-[22.5rem]"
        style={result.thumbnail_url ? undefined : { backgroundColor: color }}
      >
        {result.thumbnail_url && (
          <img
            src={result.thumbnail_url}
            alt=""
            loading="lazy"
            className="size-full rounded-[inherit] object-cover outline outline-1 -outline-offset-1 outline-black/10 dark:outline-white/10"
          />
        )}
        {(live || duration) && (
          <span className="absolute right-1.5 bottom-1.5 flex items-center gap-1 rounded bg-black/80 px-1 py-px text-xs font-medium text-white tabular-nums">
            {live ? (
              <>
                <span
                  aria-hidden="true"
                  className="size-1.5 rounded-full bg-brand"
                />
                Live
              </>
            ) : (
              duration
            )}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-1 gap-2">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h3 className="line-clamp-2 text-lg leading-snug break-words">
            <Link
              to="/watch/$videoId"
              params={{ videoId: result.id }}
              className="outline-none before:absolute before:-inset-2 before:rounded-2xl focus-visible:before:ring-3 focus-visible:before:ring-ring/50"
            >
              {result.title}
            </Link>
          </h3>
          {(views || upcoming) && (
            <p className="text-xs text-muted-foreground tabular-nums">
              {[views, upcoming && "Upcoming"].filter(Boolean).join(" • ")}
            </p>
          )}
          <p className="flex min-w-0 items-center gap-2 py-2 text-xs text-muted-foreground">
            <Avatar aria-hidden="true" className="size-6">
              <AvatarFallback
                className="text-[0.625rem] font-medium text-white"
                style={{ backgroundColor: color }}
              >
                {result.channel_title.trim().charAt(0).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <span className="truncate">{result.channel_title}</span>
          </p>
          {result.description && (
            <p className="line-clamp-2 text-xs leading-normal text-muted-foreground">
              {result.description}
            </p>
          )}
          <QueueStatus message={queue.message} className="text-xs" />
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="ghost"
                size="icon"
                className="relative z-10 -mt-1 [@media(hover:hover)]:opacity-0 [@media(hover:hover)]:group-hover/row:opacity-100 [@media(hover:hover)]:focus-visible:opacity-100 [@media(hover:hover)]:data-popup-open:opacity-100"
              />
            }
            aria-label={`More actions for ${result.title}`}
          >
            <EllipsisVertical className="size-5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56 py-2">
            <DropdownMenuItem
              disabled={!queue.ready}
              onClick={queue.toggle}
              className="px-3 py-2"
            >
              {queue.queued ? <ListMinus /> : <ListPlus />}
              {queue.queued ? "Remove from queue" : "Add to queue"}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  );
}
