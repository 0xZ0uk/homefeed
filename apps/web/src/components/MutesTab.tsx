import type { KeywordMute } from "@homefeed/api-client";
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  keywordMutesQuery,
  muteKeyword,
  unmuteKeyword,
} from "#/server/keyword-mutes";

/** Mute keywords: videos whose title or description contain one are left out of the feed. */
export function MutesTab() {
  const { data: mutes } = useSuspenseQuery(keywordMutesQuery);

  return (
    <div className="flex flex-col gap-6">
      <MuteForm />
      {mutes.length === 0 ? (
        <p className="text-muted-foreground">
          No muted keywords yet. Add a word or phrase above to keep matching
          videos out of your feed.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Muted keywords">
          {mutes.map((mute) => (
            <MuteRow key={mute.id} mute={mute} />
          ))}
        </ul>
      )}
    </div>
  );
}

function useInvalidateMutes() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: keywordMutesQuery.queryKey });
}

function MuteForm() {
  const invalidate = useInvalidateMutes();
  const [keyword, setKeyword] = useState("");
  const mutation = useMutation({
    mutationFn: (keyword: string) => muteKeyword({ data: { keyword } }),
    onSuccess: async (result) => {
      if (result.ok) {
        setKeyword("");
        await invalidate();
      }
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (keyword.trim()) mutation.mutate(keyword);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor="mute-keyword" className="font-medium">
        Mute a keyword
      </label>
      <p id="mute-keyword-hint" className="text-sm text-muted-foreground">
        Videos whose title or description contain it, as a whole word or phrase,
        never appear in your feed. Case doesn't matter.
      </p>
      <div className="flex gap-2">
        <input
          id="mute-keyword"
          type="text"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="e.g. reaction video"
          maxLength={100}
          required
          aria-invalid={result?.ok === false}
          aria-describedby="mute-keyword-hint mute-status"
          className="min-w-0 flex-1 rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-3 py-2"
        />
        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85 disabled:opacity-50"
        >
          {mutation.isPending ? "Muting…" : "Mute"}
        </button>
      </div>
      <p id="mute-status" role="status" className="min-h-6">
        {mutation.isError && (
          <span className="text-destructive">
            Couldn't mute that. Try again later.
          </span>
        )}
        {result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
        {result?.ok === true &&
          (result.created
            ? `Muted “${result.mute.keyword}”.`
            : `“${result.mute.keyword}” is already muted.`)}
      </p>
    </form>
  );
}

function MuteRow({ mute }: { mute: KeywordMute }) {
  const invalidate = useInvalidateMutes();
  const remove = useMutation({
    mutationFn: () => unmuteKeyword({ data: { id: mute.id } }),
    onSettled: invalidate,
  });

  return (
    <li className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 py-3">
      <span className="min-w-0 break-words font-medium">{mute.keyword}</span>
      <button
        type="button"
        disabled={remove.isPending}
        onClick={() => remove.mutate()}
        aria-label={`Unmute ${mute.keyword}`}
        className="text-sm text-destructive underline disabled:opacity-50"
      >
        Unmute
      </button>
      {remove.isError && (
        <p role="alert" className="w-full text-sm text-destructive">
          Couldn't unmute that. Try again.
        </p>
      )}
    </li>
  );
}
