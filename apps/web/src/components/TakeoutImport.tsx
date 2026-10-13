import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { DEFAULT_SUBSCRIBE_MIN_WATCHES, summarizeImport } from "#/lib/takeout";
import { uploadTakeout } from "#/server/takeout";

/**
 * Upload a Google Takeout watch history to seed channels and candidates. Never
 * creates ratings: those stay one tap at a time on the watch page.
 */
export function TakeoutImport() {
  const [subscribe, setSubscribe] = useState(false);
  const mutation = useMutation({
    mutationFn: (form: FormData) => uploadTakeout({ data: form }),
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  }

  return (
    <section aria-labelledby="takeout-heading" className="flex flex-col gap-3">
      <h3 id="takeout-heading" className="text-lg font-semibold">
        Import watch history
      </h3>
      <p className="text-muted-foreground">
        Upload the YouTube watch history from Google Takeout (
        <code>watch-history.json</code> or <code>watch-history.html</code>). Its
        channels and your most recently watched videos are added as candidates,
        so they can show up in your feed for rating. Nothing is rated for you.
      </p>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="takeout-file" className="font-medium">
            Watch history file
          </label>
          <input
            id="takeout-file"
            name="file"
            type="file"
            accept=".json,.html,application/json,text/html"
            required
            aria-describedby="takeout-status"
            className="text-sm"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            id="takeout-subscribe"
            name="subscribe"
            type="checkbox"
            checked={subscribe}
            onChange={(event) => setSubscribe(event.target.checked)}
          />
          <label htmlFor="takeout-subscribe">
            Subscribe to channels I watched at least
          </label>
          <input
            id="takeout-min-watches"
            name="subscribe_min_watches"
            type="number"
            min={1}
            step={1}
            defaultValue={DEFAULT_SUBSCRIBE_MIN_WATCHES}
            disabled={!subscribe}
            aria-label="Minimum watches to subscribe"
            className="w-20 rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-2 py-1 disabled:opacity-50"
          />
          <span>times</span>
        </div>
        <div>
          <button
            type="submit"
            disabled={mutation.isPending}
            className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
          >
            {mutation.isPending ? "Importing…" : "Import"}
          </button>
        </div>
      </form>
      <div id="takeout-status" role="status" className="min-h-6">
        {mutation.isError && (
          <p className="text-destructive">
            Couldn't import that file. Try again later.
          </p>
        )}
        {result?.ok === false && (
          <p className="text-destructive">{result.message}</p>
        )}
        {result?.ok === true && (
          <ul className="flex flex-col gap-1">
            {summarizeImport(result.report).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
