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
} from "@tanstack/react-router";
import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { AppShell } from "#/components/AppShell";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "#/components/ui/alert-dialog";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
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
  addToPlaylist,
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
  const [removed, setRemoved] = useState<PlaylistItem | null>(null);
  if (!detail) return null; // the loader already threw notFound

  return (
    <Shell>
      <BackToPlaylists />
      <PlaylistHeading playlist={detail.playlist} />
      <RemovedNotice
        playlistId={id}
        item={removed}
        onDone={() => setRemoved(null)}
      />
      {detail.items.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-muted-foreground">
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
              onRemoved={setRemoved}
            />
          ))}
        </ol>
      )}
    </Shell>
  );
}

/** The id of a row's title link, so focus can land on a row by video. */
function itemTitleId(videoId: string) {
  return `playlist-item-${videoId}`;
}

/**
 * "Removed …. Undo" after a video leaves the playlist. Undo adds it back and
 * returns it to its old position. The status region stays mounted so screen
 * readers announce each removal.
 */
function RemovedNotice({
  playlistId,
  item,
  onDone,
}: {
  playlistId: number;
  item: PlaylistItem | null;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const undoRef = useRef<HTMLButtonElement>(null);
  const undo = useMutation({
    mutationFn: async (removed: PlaylistItem) => {
      await addToPlaylist({
        data: { id: playlistId, videoId: removed.video_id },
      });
      await moveInPlaylist({
        data: {
          id: playlistId,
          videoId: removed.video_id,
          position: removed.position,
        },
      });
    },
    onSuccess: async (_, restored) => {
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      onDone();
      // The row is back once the refetch renders; put focus on its title.
      requestAnimationFrame(() =>
        document.getElementById(itemTitleId(restored.video_id))?.focus(),
      );
    },
  });

  // The Remove button that had focus is gone; Undo is the natural next stop.
  useEffect(() => {
    if (item) undoRef.current?.focus();
  }, [item]);

  return (
    <div role="status" className="empty:hidden">
      {item && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-muted px-3 py-2 text-sm">
          <span className="min-w-0 break-words">
            Removed “{item.title ?? `Video ${item.video_id}`}”.
          </span>
          <Button
            ref={undoRef}
            type="button"
            variant="outline"
            size="sm"
            aria-disabled={undo.isPending || undefined}
            onClick={() => !undo.isPending && undo.mutate(item)}
            className="aria-disabled:opacity-50"
          >
            {undo.isPending ? "Undoing…" : "Undo"}
          </Button>
          {undo.isError && (
            <span className="text-destructive">
              Couldn't put it back. Try again.
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function PlaylistHeading({ playlist }: { playlist: Playlist }) {
  const [editing, setEditing] = useState(false);
  const editRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  // Leaving the form unmounts it; send focus back to the Edit button.
  useEffect(() => {
    if (!editing && returnFocus.current) {
      returnFocus.current = false;
      editRef.current?.focus();
    }
  }, [editing]);

  if (editing) {
    return (
      <EditForm
        playlist={playlist}
        onDone={() => {
          returnFocus.current = true;
          setEditing(false);
        }}
      />
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h2 className="text-xl font-semibold break-words">{playlist.name}</h2>
        <div className="flex items-center gap-2">
          <Button
            ref={editRef}
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setEditing(true)}
          >
            Edit
          </Button>
          <DeletePlaylist playlist={playlist} />
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        {describeItemCount(playlist.item_count)}
      </p>
      {playlist.description && (
        <p className="whitespace-pre-line break-words text-foreground">
          {playlist.description}
        </p>
      )}
    </div>
  );
}

function DeletePlaylist({ playlist }: { playlist: Playlist }) {
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
  const count = playlist.item_count;

  return (
    <AlertDialog onOpenChange={(open) => !open && remove.reset()}>
      <AlertDialogTrigger
        render={<Button type="button" variant="destructive" size="sm" />}
      >
        Delete playlist
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="break-words">
            Delete “{playlist.name}”?
          </AlertDialogTitle>
          <AlertDialogDescription>
            {count === 0
              ? "The playlist is empty. Deleting it can't be undone."
              : `Its list of ${describeItemCount(count).toLowerCase()} is lost for good. The videos themselves stay in your history.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {remove.isError && (
          <p role="alert" className="text-sm text-destructive">
            Couldn't delete the playlist. Try again.
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            aria-disabled={remove.isPending || undefined}
            onClick={() => !remove.isPending && remove.mutate()}
            className="aria-disabled:opacity-50"
          >
            {remove.isPending ? "Deleting…" : "Delete playlist"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
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
  const nameRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState(playlist.name);
  const [description, setDescription] = useState(playlist.description);
  const [problem, setProblem] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (data: { name: string; description: string }) =>
      editPlaylist({ data: { id: playlist.id, ...data } }),
    onSuccess: async (result) => {
      if (!result.ok) {
        fail(result.message);
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ["playlists"] });
      onDone();
    },
    onError: () => fail("Couldn't save the playlist. Try again."),
  });

  /** Show `message` under the name field and put the cursor back in it. */
  function fail(message: string) {
    setProblem(message);
    nameRef.current?.focus();
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending) return;
    const checked = checkPlaylistName(name);
    if (!checked.ok) {
      fail(checked.message);
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
        <Input
          ref={nameRef}
          id="edit-playlist-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={PLAYLIST_NAME_MAX_LENGTH}
          required
          autoFocus
          aria-invalid={problem ? true : undefined}
          aria-describedby={problem ? "edit-playlist-name-problem" : undefined}
          className="h-10 px-3"
        />
        {problem && (
          <p
            id="edit-playlist-name-problem"
            className="text-sm text-destructive"
          >
            {problem}
          </p>
        )}
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
          className="rounded-lg border border-input bg-transparent px-3 py-2 text-base outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:bg-input/30"
        />
      </div>
      <div className="flex items-center gap-2">
        {/* aria-disabled, not disabled, so the button keeps keyboard focus. */}
        <Button
          type="submit"
          size="lg"
          aria-disabled={save.isPending || undefined}
          className="px-4 aria-disabled:opacity-50"
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ItemRow({
  playlistId,
  item,
  count,
  onRemoved,
}: {
  playlistId: number;
  item: PlaylistItem;
  count: number;
  onRemoved: (item: PlaylistItem) => void;
}) {
  const queryClient = useQueryClient();
  const queryKey = playlistQuery(playlistId).queryKey;
  const upRef = useRef<HTMLButtonElement>(null);
  const downRef = useRef<HTMLButtonElement>(null);
  const refocus = useRef<HTMLButtonElement | null>(null);
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
    onSuccess: () => onRemoved(item),
    onSettled: invalidate,
  });
  const title = item.title ?? `Video ${item.video_id}`;
  const duration = formatDuration(item.duration_seconds);
  const up = stepPosition(item.position, "up", count);
  const down = stepPosition(item.position, "down", count);
  const busy = move.isPending || remove.isPending;

  // Reordering moves this row's DOM node, which drops focus; put it back on
  // the button that was pressed.
  useEffect(() => {
    if (refocus.current && document.activeElement !== refocus.current) {
      refocus.current.focus();
    }
    refocus.current = null;
  }, [item.position]);

  function step(position: number | null, button: HTMLButtonElement | null) {
    if (busy || position === null) return;
    refocus.current = button;
    move.mutate(position);
  }

  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-2 py-3 sm:flex-nowrap sm:gap-x-4">
      <span className="w-6 shrink-0 pt-0.5 text-right text-sm text-muted-foreground tabular-nums">
        {item.position + 1}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="font-medium break-words">
          <Link
            id={itemTitleId(item.video_id)}
            to="/watch/$videoId"
            params={{ videoId: item.video_id }}
            className="hover:underline"
          >
            {title}
          </Link>
        </h3>
        {(item.channel_title || duration) && (
          <p className="flex flex-wrap gap-x-2 text-sm text-muted-foreground">
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
          <p role="alert" className="text-sm text-destructive">
            {remove.isError
              ? "Couldn't remove that video. Try again."
              : "Couldn't move that video. Try again."}
          </p>
        )}
      </div>
      {/* Below sm the controls wrap under the title, aligned with it. aria-
          disabled, not disabled, keeps focus on a button while it works. */}
      <div className="flex basis-full items-center gap-1 ps-9 sm:basis-auto sm:shrink-0 sm:ps-0">
        <Button
          ref={upRef}
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={busy || up === null || undefined}
          onClick={() => step(up, upRef.current)}
          aria-label={`Move ${title} up`}
          className="aria-disabled:opacity-40"
        >
          Up
        </Button>
        <Button
          ref={downRef}
          type="button"
          variant="ghost"
          size="sm"
          aria-disabled={busy || down === null || undefined}
          onClick={() => step(down, downRef.current)}
          aria-label={`Move ${title} down`}
          className="aria-disabled:opacity-40"
        >
          Down
        </Button>
        <Button
          type="button"
          variant="destructive"
          size="sm"
          aria-disabled={busy || undefined}
          onClick={() => !busy && remove.mutate()}
          aria-label={`Remove ${title} from the playlist`}
          className="aria-disabled:opacity-50"
        >
          Remove
        </Button>
      </div>
    </li>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">{children}</AppShell>
  );
}

function BackToPlaylists() {
  return (
    <Link to="/playlists" className="self-start text-sm underline">
      All playlists
    </Link>
  );
}

function PlaylistError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <Shell>
      <div role="alert" className="flex flex-col items-start gap-3">
        <p>Couldn't load this playlist. The API may be down.</p>
        <Button
          type="button"
          variant="outline"
          onClick={() => void router.invalidate()}
        >
          Try again
        </Button>
        <BackToPlaylists />
      </div>
    </Shell>
  );
}
