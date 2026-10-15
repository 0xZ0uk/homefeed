import type { ExternalSource } from "@homefeed/api-client";
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ConfirmButton } from "#/components/ConfirmButton";
import {
  KIND_LABELS,
  KIND_PLACEHOLDERS,
  SCHEDULE_LABELS,
  SOURCE_KINDS,
  SOURCE_SCHEDULES,
  sourceStatus,
  type SourceKind,
  type SourceSchedule,
} from "#/lib/external-sources";
import {
  createSource,
  externalSourcesQuery,
  removeSource,
  setSourceSchedule,
  type NewSource,
} from "#/server/external-sources";

/** Subreddits, RSS feeds and link pages whose YouTube links become candidates. */
export function SourcesTab() {
  const { data: sources } = useSuspenseQuery(externalSourcesQuery);

  return (
    <div className="flex flex-col gap-6">
      <SourceForm />
      {sources.length === 0 ? (
        <p className="text-muted-foreground">
          No sources yet. Add a subreddit, feed or page above, and the YouTube
          videos it links to will be considered for your feed.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="External sources">
          {sources.map((source) => (
            <SourceRow key={source.id} source={source} />
          ))}
        </ul>
      )}
    </div>
  );
}

function useInvalidateSources() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: externalSourcesQuery.queryKey });
}

function SourceForm() {
  const invalidate = useInvalidateSources();
  const [kind, setKind] = useState<SourceKind>("subreddit");
  const [url, setUrl] = useState("");
  const [schedule, setSchedule] = useState<SourceSchedule>("daily");
  const mutation = useMutation({
    mutationFn: (source: NewSource) => createSource({ data: source }),
    onSuccess: async (result) => {
      if (result.ok) {
        setUrl("");
        await invalidate();
      }
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (url.trim()) mutation.mutate({ kind, url, schedule });
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-2"
      aria-labelledby="source-form-title"
    >
      <h2 id="source-form-title" className="font-medium">
        Add a source
      </h2>
      <p id="source-hint" className="text-sm text-muted-foreground">
        Homefeed checks it on the schedule you pick and adds the YouTube videos
        it links to as candidates.
      </p>
      <div className="flex flex-wrap gap-2">
        <label className="sr-only" htmlFor="source-kind">
          Kind
        </label>
        <select
          id="source-kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as SourceKind)}
          className="rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-2 py-2"
        >
          {SOURCE_KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABELS[k]}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="source-url">
          {kind === "subreddit" ? "Subreddit" : "Address"}
        </label>
        <input
          id="source-url"
          type="text"
          inputMode={kind === "subreddit" ? "text" : "url"}
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder={KIND_PLACEHOLDERS[kind]}
          maxLength={2000}
          required
          aria-invalid={result?.ok === false}
          aria-describedby="source-hint source-status"
          className="min-w-48 flex-1 rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-3 py-2"
        />
        <label className="sr-only" htmlFor="source-schedule">
          How often to check
        </label>
        <select
          id="source-schedule"
          value={schedule}
          onChange={(event) =>
            setSchedule(event.target.value as SourceSchedule)
          }
          className="rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-2 py-2"
        >
          {SOURCE_SCHEDULES.map((s) => (
            <option key={s} value={s}>
              {SCHEDULE_LABELS[s]}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
        >
          {mutation.isPending ? "Adding…" : "Add source"}
        </button>
      </div>
      <p id="source-status" role="status" className="min-h-6">
        {mutation.isError && (
          <span className="text-destructive">
            Couldn't add that source. Try again later.
          </span>
        )}
        {result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
        {result?.ok === true &&
          (result.created
            ? `Added ${result.source.label}.`
            : `${result.source.label} is already a source.`)}
      </p>
    </form>
  );
}

function SourceRow({ source }: { source: ExternalSource }) {
  const invalidate = useInvalidateSources();
  const update = useMutation({
    mutationFn: (schedule: SourceSchedule) =>
      setSourceSchedule({ data: { id: source.id, schedule } }),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => removeSource({ data: { id: source.id } }),
    onSettled: invalidate,
  });
  const busy = update.isPending || remove.isPending;
  const scheduleId = `source-schedule-${source.id}`;
  const failing = source.consecutive_failures > 0;

  return (
    <li className="flex flex-wrap items-center gap-x-6 gap-y-2 py-3">
      <div className="min-w-48 flex-1">
        <p className="break-words font-medium">
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            className="hover:underline"
          >
            {source.label}
          </a>
        </p>
        <p className="text-sm text-muted-foreground">
          {KIND_LABELS[source.kind]} ·{" "}
          <span className={failing ? "text-destructive" : undefined}>
            {sourceStatus(source)}
          </span>
        </p>
      </div>
      <div className="flex items-center gap-2">
        <label htmlFor={scheduleId} className="text-sm">
          Check
        </label>
        <select
          id={scheduleId}
          value={source.schedule}
          disabled={busy}
          onChange={(event) =>
            update.mutate(event.target.value as SourceSchedule)
          }
          className="rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-2 py-1"
        >
          {SOURCE_SCHEDULES.map((s) => (
            <option key={s} value={s}>
              {SCHEDULE_LABELS[s]}
            </option>
          ))}
        </select>
      </div>
      <ConfirmButton
        disabled={busy}
        aria-label={`Remove ${source.label}`}
        title={`Remove ${source.label}?`}
        description="Homefeed stops checking it. The videos it already found stay among your candidates."
        confirmLabel="Remove"
        onConfirm={() => remove.mutate()}
      >
        Remove
      </ConfirmButton>
      {(update.isError || remove.isError) && (
        <p role="alert" className="w-full text-sm text-destructive">
          Couldn't save that change. Try again.
        </p>
      )}
    </li>
  );
}
