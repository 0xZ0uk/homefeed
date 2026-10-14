import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { SettingsCard } from "#/components/SettingsCard";
import { Button } from "#/components/ui/button";
import { CardContent, CardFooter } from "#/components/ui/card";
import { Input } from "#/components/ui/input";
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
    <SettingsCard
      id="takeout-heading"
      title="Import watch history"
      description={
        <>
          Upload the YouTube watch history from Google Takeout (
          <code>watch-history.json</code> or <code>watch-history.html</code>).
          Its channels and your most recently watched videos are added as
          candidates, so they can show up in your feed for rating. Nothing is
          rated for you.
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-6">
        <CardContent className="flex flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="takeout-file" className="text-sm font-medium">
              Watch history file
            </label>
            <Input
              id="takeout-file"
              name="file"
              type="file"
              accept=".json,.html,application/json,text/html"
              required
              aria-describedby="takeout-status"
              className="max-w-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm">
            <label className="flex items-center gap-2">
              <input
                name="subscribe"
                type="checkbox"
                checked={subscribe}
                onChange={(event) => setSubscribe(event.target.checked)}
              />
              Subscribe to channels I watched at least
            </label>
            <span className="flex items-center gap-2">
              <Input
                id="takeout-min-watches"
                name="subscribe_min_watches"
                type="number"
                inputMode="numeric"
                min={1}
                step={1}
                defaultValue={DEFAULT_SUBSCRIBE_MIN_WATCHES}
                disabled={!subscribe}
                aria-label="Minimum watches to subscribe"
                className="w-20"
              />
              times
            </span>
          </div>
        </CardContent>
        <CardFooter className="flex-wrap items-start gap-3">
          <Button
            type="submit"
            size="lg"
            className="px-4"
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Importing…" : "Import"}
          </Button>
          <div
            id="takeout-status"
            role="status"
            className="min-w-0 flex-1 basis-60 text-sm"
          >
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
        </CardFooter>
      </form>
    </SettingsCard>
  );
}
