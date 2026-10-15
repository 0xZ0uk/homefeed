import {
  useMutation,
  useQueryClient,
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { AppShell } from "#/components/AppShell";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import {
  PLAYLIST_DESCRIPTION_MAX_LENGTH,
  PLAYLIST_NAME_MAX_LENGTH,
  checkPlaylistName,
  describeItemCount,
} from "#/lib/playlists";
import { newPlaylist, playlistsQuery } from "#/server/playlists";

/** Local playlists: create one, or open one to watch and reorder it. */
export const Route = createFileRoute("/playlists/")({
  head: () => ({ meta: [{ title: "Playlists · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(playlistsQuery),
  component: Playlists,
  errorComponent: PlaylistsError,
});

function Playlists() {
  const { data: playlists } = useSuspenseQuery(playlistsQuery);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-xl font-semibold">Playlists</h1>
      <NewPlaylistForm />
      {playlists.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-muted-foreground">
          No playlists yet. Create one above, then add videos to it from their
          watch pages.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Playlists">
          {playlists.map((playlist) => (
            <li key={playlist.id} className="flex flex-col gap-1 py-3">
              <Link
                to="/playlists/$playlistId"
                params={{ playlistId: String(playlist.id) }}
                className="font-medium break-words hover:underline"
              >
                {playlist.name}
              </Link>
              <p className="text-sm text-muted-foreground">
                {describeItemCount(playlist.item_count)}
                {playlist.description && <> · {playlist.description}</>}
              </p>
            </li>
          ))}
        </ul>
      )}
    </AppShell>
  );
}

function NewPlaylistForm() {
  const queryClient = useQueryClient();
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (data: { name: string; description: string }) =>
      newPlaylist({ data }),
    onSuccess: async (result) => {
      if (result.ok) {
        setName("");
        setDescription("");
        setProblem(null);
        await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      } else {
        fail(result.message);
      }
    },
    onError: () => fail("Couldn't create the playlist. Try again."),
  });

  /** Show `message` under the name field and put the cursor back in it. */
  function fail(message: string) {
    setProblem(message);
    nameRef.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const checked = checkPlaylistName(name);
    if (!checked.ok) {
      fail(checked.message);
      return;
    }
    mutation.mutate({ name: checked.name, description });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="playlist-name" className="text-sm font-medium">
          New playlist
        </label>
        <Input
          ref={nameRef}
          id="playlist-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Weekend woodworking"
          maxLength={PLAYLIST_NAME_MAX_LENGTH}
          required
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? "playlist-name-problem" : undefined}
          className="h-10 px-3"
        />
        {problem && (
          <p id="playlist-name-problem" className="text-sm text-destructive">
            {problem}
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="playlist-description" className="text-sm font-medium">
          Description{" "}
          <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <textarea
          id="playlist-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={PLAYLIST_DESCRIPTION_MAX_LENGTH}
          rows={2}
          className="rounded-lg border border-input bg-transparent px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:bg-input/30"
        />
      </div>
      {/* aria-disabled, not disabled, so the button keeps keyboard focus. */}
      <Button
        type="submit"
        size="lg"
        aria-disabled={mutation.isPending || undefined}
        className="self-start px-4 aria-disabled:opacity-50"
      >
        {mutation.isPending ? "Creating…" : "Create playlist"}
      </Button>
    </form>
  );
}

function PlaylistsError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load your playlists. The API may be down.</p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void router.invalidate()}
        >
          Try again
        </Button>
      </div>
    </AppShell>
  );
}
