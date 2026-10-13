import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";

import { PLAYLIST_NAME_MAX_LENGTH, checkPlaylistName } from "#/lib/playlists";
import {
  addToPlaylist,
  newPlaylist,
  playlistsForVideoQuery,
  removeFromPlaylist,
  type Playlist,
} from "#/server/playlists";

/**
 * "Save to playlist" for one video: a disclosure listing the local playlists
 * with a checkbox each (checked when the video is in it), plus a field to
 * create a playlist with the video in it. Loads only once opened.
 */
export function SaveToPlaylist({ videoId }: { videoId: string }) {
  const [open, setOpen] = useState(false);

  return (
    <details
      className="text-sm"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer underline">Save to playlist</summary>
      {open && <PlaylistChoices videoId={videoId} />}
    </details>
  );
}

function PlaylistChoices({ videoId }: { videoId: string }) {
  const query = useQuery(playlistsForVideoQuery(videoId));

  return (
    <div className="mt-2 flex flex-col gap-3 rounded border p-3">
      {query.isPending ? (
        <p className="text-gray-600">Loading playlists…</p>
      ) : query.isError ? (
        <p role="alert" className="text-red-600">
          Couldn't load your playlists. Try again later.
        </p>
      ) : query.data.length === 0 ? (
        <p className="text-gray-600">No playlists yet. Create one below.</p>
      ) : (
        <ul className="flex flex-col gap-1" aria-label="Playlists">
          {query.data.map((playlist) => (
            <PlaylistChoice
              key={playlist.id}
              playlist={playlist}
              videoId={videoId}
            />
          ))}
        </ul>
      )}
      <NewPlaylistWithVideo videoId={videoId} />
      <Link to="/playlists" className="self-start underline">
        Manage playlists
      </Link>
    </div>
  );
}

function PlaylistChoice({
  playlist,
  videoId,
}: {
  playlist: Playlist;
  videoId: string;
}) {
  const queryClient = useQueryClient();
  const toggle = useMutation({
    mutationFn: async (add: boolean) => {
      const data = { id: playlist.id, videoId };
      if (add) await addToPlaylist({ data });
      else await removeFromPlaylist({ data });
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["playlists"] }),
  });
  const checked = toggle.isPending
    ? toggle.variables
    : Boolean(playlist.contains_video);

  return (
    <li className="flex flex-col">
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={checked}
          disabled={toggle.isPending}
          onChange={(event) => toggle.mutate(event.target.checked)}
        />
        <span className="break-words">{playlist.name}</span>
      </label>
      {toggle.isError && (
        <p role="alert" className="text-red-600">
          Couldn't update “{playlist.name}”. Try again.
        </p>
      )}
    </li>
  );
}

function NewPlaylistWithVideo({ videoId }: { videoId: string }) {
  const inputId = useId();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: async (playlistName: string) => {
      const result = await newPlaylist({ data: { name: playlistName } });
      if (result.ok) {
        await addToPlaylist({ data: { id: result.playlist.id, videoId } });
      }
      return result;
    },
    onSuccess: (result) => {
      if (result.ok) {
        setName("");
        setProblem(null);
      } else {
        setProblem(result.message);
      }
    },
    onError: () => setProblem("Couldn't create the playlist. Try again."),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["playlists"] }),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const checked = checkPlaylistName(name);
    if (!checked.ok) {
      setProblem(checked.message);
      return;
    }
    create.mutate(checked.name);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-1">
      <label htmlFor={inputId} className="font-medium">
        New playlist
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <input
          id={inputId}
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={PLAYLIST_NAME_MAX_LENGTH}
          className="rounded border px-2 py-1"
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-black px-2 py-1 font-medium text-white disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Create and add"}
        </button>
      </div>
      {problem && (
        <p role="alert" className="text-red-600">
          {problem}
        </p>
      )}
    </form>
  );
}
