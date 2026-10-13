import {
  useMutation,
  useQueryClient,
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import {
  Link,
  createFileRoute,
  notFound,
  useNavigate,
  useRouter,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { AppHeader } from "#/components/AppHeader";
import { formatDuration } from "#/lib/format";
import {
  PLAYLIST_DESCRIPTION_MAX_LENGTH,
  PLAYLIST_NAME_MAX_LENGTH,
  checkPlaylistName,
  describeItemCount,
  moveItem,
  parsePlaylistId,
  stepPosition,
} from "#/lib/playlists";
import {
  editPlaylist,
  moveInPlaylist,
  playlistQuery,
  playlistsQuery,
  removeFromPlaylist,
  removePlaylist,
  type Playlist,
  type PlaylistDetail,
  type PlaylistItem,
} from "#/server/playlists";

/** One playlist: its videos in order, to watch, reorder or remove. */
export const Route = createFileRoute("/playlists/$playlistId")({
  loader: async ({ params, context: { queryClient } }) => {
    const id = parsePlaylistId(params.playlistId);
    if (id === null) throw notFound();
    const detail = await queryClient.ensureQueryData(playlistQuery(id));
    if (!detail) throw notFound();
    return { name: detail.playlist.name };
  },
  head: ({ loaderData }) => ({
    meta: [
      {
        title: loaderData
          ? `${loaderData.name} · Playlists · Homefeed`
          : "Playlist · Homefeed",
      },
    ],
  }),
  component: PlaylistPage,
  errorComponent: PlaylistError,
  notFoundComponent: () => (
    <Shell>
      <p>
        There's no such playlist. <BackToPlaylists />
      </p>
    </Shell>
  ),
});

function PlaylistPage() {
  const { playlistId } = Route.useParams();
  const id = parsePlaylistId(playlistId) ?? 0;
  const { data: detail } = useSuspenseQuery(playlistQuery(id));
  if (!detail) return null; // the loader already threw notFound

  return (
    <Shell>
      <BackToPlaylists />
      <PlaylistHeading playlist={detail.playlist} />
      {detail.items.length === 0 ? (
        <p className="rounded border border-dashed p-6 text-gray-600">
          This playlist is empty. Use “Save to playlist” on a video's watch page
          to add it here.
        </p>
      ) : (
        <ol className="flex flex-col divide-y" aria-label="Videos">
          {detail.items.map((item) => (
            <ItemRow
              key={item.video_id}
              playlistId={id}
              item={item}
              count={detail.items.length}
            />
          ))}
        </ol>
      )}
    </Shell>
  );
}

function PlaylistHeading({ playlist }: { playlist: Playlist }) {
  const [editing, setEditing] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => removePlaylist({ data: { id: playlist.id } }),
    onSuccess: async () => {
      // Refresh the list before leaving, and drop this page's data after, so
      // neither page shows the deleted playlist.
      await queryClient.invalidateQueries({
        queryKey: playlistsQuery.queryKey,
        exact: true,
      });
      await navigate({ to: "/playlists" });
      queryClient.removeQueries({
        queryKey: playlistQuery(playlist.id).queryKey,
      });
      await queryClient.invalidateQueries({
        queryKey: ["playlists", "for-video"],
      });
    },
  });

  if (editing) {
    return <EditForm playlist={playlist} onDone={() => setEditing(false)} />;
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-xl font-semibold break-words">{playlist.name}</h2>
        <div className="flex items-center gap-4 text-sm">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="underline"
          >
            Edit
          </button>
          <button
            type="button"
            disabled={remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete the playlist “${playlist.name}”?`)) {
                remove.mutate();
              }
            }}
            className="text-red-700 underline disabled:opacity-50"
          >
            Delete playlist
          </button>
        </div>
      </div>
      <p className="text-sm text-gray-600">
        {describeItemCount(playlist.item_count)}
      </p>
      {playlist.description && (
        <p className="whitespace-pre-line break-words text-gray-800">
          {playlist.description}
        </p>
      )}
      {remove.isError && (
        <p role="alert" className="text-sm text-red-600">
          Couldn't delete the playlist. Try again.
        </p>
      )}
    </div>
  );
}

function EditForm({
  playlist,
  onDone,
}: {
  playlist: Playlist;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(playlist.name);
  const [description, setDescription] = useState(playlist.description);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (data: { name: string; description: string }) =>
      editPlaylist({ data: { id: playlist.id, ...data } }),
    onSuccess: async (result) => {
      if (!result.ok) {
        setProblem(result.message);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      onDone();
    },
    onError: () => setProblem("Couldn't save the playlist. Try again."),
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const checked = checkPlaylistName(name);
    if (!checked.ok) {
      setProblem(checked.message);
      return;
    }
    save.mutate({ name: checked.name, description });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="edit-playlist-name" className="text-sm font-medium">
          Name
        </label>
        <input
          id="edit-playlist-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={PLAYLIST_NAME_MAX_LENGTH}
          required
          className="rounded border px-3 py-2"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label
          htmlFor="edit-playlist-description"
          className="text-sm font-medium"
        >
          Description
        </label>
        <textarea
          id="edit-playlist-description"
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
          disabled={save.isPending}
          className="rounded bg-black px-3 py-2 font-medium text-white disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={onDone} className="underline">
          Cancel
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

function ItemRow({
  playlistId,
  item,
  count,
}: {
  playlistId: number;
  item: PlaylistItem;
  count: number;
}) {
  const queryClient = useQueryClient();
  const queryKey = playlistQuery(playlistId).queryKey;
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["playlists"] });
  const move = useMutation({
    mutationFn: (position: number) =>
      moveInPlaylist({
        data: { id: playlistId, videoId: item.video_id, position },
      }),
    onMutate: async (position) => {
      await queryClient.cancelQueries({ queryKey });
      queryClient.setQueryData(
        queryKey,
        (detail: PlaylistDetail | null | undefined) =>
          detail && {
            ...detail,
            items: moveItem(detail.items, item.position, position).map(
              (moved, index) => ({ ...moved, position: index }),
            ),
          },
      );
    },
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () =>
      removeFromPlaylist({ data: { id: playlistId, videoId: item.video_id } }),
    onSettled: invalidate,
  });
  const title = item.title ?? `Video ${item.video_id}`;
  const duration = formatDuration(item.duration_seconds);
  const up = stepPosition(item.position, "up", count);
  const down = stepPosition(item.position, "down", count);
  const busy = move.isPending || remove.isPending;

  return (
    <li className="flex items-start gap-4 py-3">
      <span className="w-6 shrink-0 text-right text-sm text-gray-500 tabular-nums">
        {item.position + 1}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="font-medium break-words">
          <Link
            to="/watch/$videoId"
            params={{ videoId: item.video_id }}
            className="hover:underline"
          >
            {title}
          </Link>
        </h3>
        {(item.channel_title || duration) && (
          <p className="flex flex-wrap gap-x-2 text-sm text-gray-600">
            {item.channel_title && <span>{item.channel_title}</span>}
            {duration && (
              <span className="tabular-nums">
                {item.channel_title && "· "}
                {duration}
              </span>
            )}
          </p>
        )}
        {(move.isError || remove.isError) && (
          <p role="alert" className="text-sm text-red-600">
            {remove.isError
              ? "Couldn't remove that video. Try again."
              : "Couldn't move that video. Try again."}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-3 text-sm">
        <button
          type="button"
          disabled={busy || up === null}
          onClick={() => up !== null && move.mutate(up)}
          aria-label={`Move ${title} up`}
          className="underline disabled:no-underline disabled:opacity-40"
        >
          Up
        </button>
        <button
          type="button"
          disabled={busy || down === null}
          onClick={() => down !== null && move.mutate(down)}
          aria-label={`Move ${title} down`}
          className="underline disabled:no-underline disabled:opacity-40"
        >
          Down
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => remove.mutate()}
          aria-label={`Remove ${title} from the playlist`}
          className="text-red-700 underline disabled:opacity-50"
        >
          Remove
        </button>
      </div>
    </li>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      {children}
    </main>
  );
}

function BackToPlaylists() {
  return (
    <Link to="/playlists" className="self-start text-sm underline">
      All playlists
    </Link>
  );
}

function PlaylistError({ error }: ErrorComponentProps) {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <Shell>
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>
          Couldn't load this playlist
          {error instanceof Error && error.message ? `: ${error.message}` : ""}.
        </p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
        <BackToPlaylists />
      </div>
    </Shell>
  );
}
