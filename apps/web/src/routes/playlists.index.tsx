import {
  useMutation,
  useQueryClient,
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";

import { AppHeader } from "#/components/AppHeader";
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
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <h2 className="text-xl font-semibold">Playlists</h2>
      <NewPlaylistForm />
      {playlists.length === 0 ? (
        <p className="rounded border border-dashed p-6 text-gray-600">
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
              <p className="text-sm text-gray-600">
                {describeItemCount(playlist.item_count)}
                {playlist.description && <> · {playlist.description}</>}
              </p>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function NewPlaylistForm() {
  const queryClient = useQueryClient();
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
        setProblem(result.message);
      }
    },
    onError: () => setProblem("Couldn't create the playlist. Try again."),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const checked = checkPlaylistName(name);
    if (!checked.ok) {
      setProblem(checked.message);
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
        <input
          id="playlist-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Weekend woodworking"
          maxLength={PLAYLIST_NAME_MAX_LENGTH}
          required
          className="rounded border px-3 py-2"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="playlist-description" className="text-sm font-medium">
          Description{" "}
          <span className="font-normal text-gray-500">(optional)</span>
        </label>
        <textarea
          id="playlist-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          maxLength={PLAYLIST_DESCRIPTION_MAX_LENGTH}
          rows={2}
          className="rounded border px-3 py-2"
        />
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded bg-black px-3 py-2 font-medium text-white disabled:opacity-50"
        >
          {mutation.isPending ? "Creating…" : "Create playlist"}
        </button>
        {problem && (
          <p role="alert" className="text-sm text-red-600">
            {problem}
          </p>
        )}
      </div>
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
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load your playlists. The API may be down.</p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
