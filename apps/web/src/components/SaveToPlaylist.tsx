import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ListPlus } from "lucide-react";
import { useId, useState, type FormEvent } from "react";

import { Button, buttonVariants } from "#/components/ui/button";
import { cn } from "#/lib/utils";
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
      className="relative text-sm"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary
        className={cn(
          buttonVariants({ variant: "secondary", size: "lg" }),
          "cursor-pointer list-none px-4 [&::-webkit-details-marker]:hidden",
        )}
      >
        <ListPlus className="size-4" />
        Save to playlist
      </summary>
      {open && <PlaylistChoices videoId={videoId} />}
    </details>
  );
}

function PlaylistChoices({ videoId }: { videoId: string }) {
  const query = useQuery(playlistsForVideoQuery(videoId));

  return (
    <div className="absolute right-0 z-20 mt-2 flex w-72 max-w-[calc(100vw-2rem)] flex-col gap-3 rounded-xl bg-popover p-4 text-popover-foreground shadow-lg ring-1 ring-foreground/10 border border-transparent">
      {query.isPending ? (
        <p className="text-muted-foreground">Loading playlists…</p>
      ) : query.isError ? (
        <p role="alert" className="text-destructive">
          Couldn't load your playlists. Try again later.
        </p>
      ) : query.data.length === 0 ? (
        <p className="text-muted-foreground">
          No playlists yet. Create one below.
        </p>
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
        <p role="alert" className="text-destructive">
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
          className="min-w-0 flex-1 rounded-lg border border-input bg-transparent px-2 py-1.5 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        />
        <Button
          type="submit"
          size="lg"
          disabled={create.isPending}
          className="px-4"
        >
          {create.isPending ? "Creating…" : "Create and add"}
        </Button>
      </div>
      {problem && (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      )}
    </form>
  );
}
