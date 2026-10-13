import {
  addPlaylistItem,
  createPlaylist,
  deletePlaylist,
  getPlaylist,
  listPlaylists,
  movePlaylistItem,
  removePlaylistItem,
  updatePlaylist,
  type Playlist,
  type PlaylistDetail,
  type PlaylistItem,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isVideoId } from "#/lib/ids";
import {
  checkPlaylistDescription,
  checkPlaylistId,
  checkPlaylistName,
  checkPosition,
} from "#/lib/playlists";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for local playlists (the playlist pages and the watch
 * page's "Save to playlist" control). */

export type { Playlist, PlaylistDetail, PlaylistItem };

export type PlaylistResult =
  { ok: true; playlist: Playlist } | { ok: false; message: string };

function checkVideoId(value: unknown): string {
  if (typeof value !== "string" || !isVideoId(value)) {
    throw new Error("Not a video id");
  }
  return value;
}

function nameInput(value: unknown): string {
  const checked = checkPlaylistName(value);
  if (!checked.ok) throw new Error(checked.message);
  return checked.name;
}

/** Every playlist; with a video id, each says whether it contains the video. */
const fetchPlaylists = createServerFn({ method: "GET" })
  .inputValidator((data: { videoId?: string }) => ({
    videoId:
      data.videoId === undefined ? undefined : checkVideoId(data.videoId),
  }))
  .handler(async ({ data }) => {
    const { data: playlists } = await listPlaylists({
      client: apiClient(),
      query: data.videoId ? { video_id: data.videoId } : undefined,
      throwOnError: true,
    });
    return playlists;
  });

export const playlistsQuery = queryOptions({
  queryKey: ["playlists"],
  queryFn: () => fetchPlaylists({ data: {} }),
});

/** Playlists with `contains_video` filled in for `videoId`. */
export const playlistsForVideoQuery = (videoId: string) =>
  queryOptions({
    queryKey: ["playlists", "for-video", videoId],
    queryFn: () => fetchPlaylists({ data: { videoId } }),
  });

/** A playlist and its videos, or null when there is no such playlist. */
const fetchPlaylist = createServerFn({ method: "GET" })
  .inputValidator((data: { id: number }) => ({ id: checkPlaylistId(data.id) }))
  .handler(async ({ data }): Promise<PlaylistDetail | null> => {
    const {
      data: detail,
      error,
      response,
    } = await getPlaylist({
      client: apiClient(),
      path: { playlist_id: data.id },
    });
    if (detail) return detail;
    if (response?.status === 404) return null;
    throw new Error(
      apiErrorMessage(
        error,
        `Couldn't load the playlist (${response?.status})`,
      ),
    );
  });

export const playlistQuery = (id: number) =>
  queryOptions({
    queryKey: ["playlists", "detail", id],
    queryFn: () => fetchPlaylist({ data: { id } }),
  });

export const newPlaylist = createServerFn({ method: "POST" })
  .inputValidator((data: { name: string; description?: string }) => ({
    name: nameInput(data.name),
    description: checkPlaylistDescription(data.description ?? ""),
  }))
  .handler(async ({ data }): Promise<PlaylistResult> => {
    const { data: playlist, error } = await createPlaylist({
      client: apiClient(),
      body: data,
    });
    if (playlist) return { ok: true, playlist };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't create the playlist. Try again later.",
      ),
    };
  });

/** Rename a playlist and/or change its description. */
export const editPlaylist = createServerFn({ method: "POST" })
  .inputValidator(
    (data: { id: number; name?: string; description?: string }) => ({
      id: checkPlaylistId(data.id),
      name: data.name === undefined ? undefined : nameInput(data.name),
      description:
        data.description === undefined
          ? undefined
          : checkPlaylistDescription(data.description),
    }),
  )
  .handler(async ({ data }): Promise<PlaylistResult> => {
    const { data: playlist, error } = await updatePlaylist({
      client: apiClient(),
      path: { playlist_id: data.id },
      body: { name: data.name, description: data.description },
    });
    if (playlist) return { ok: true, playlist };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't save the playlist. Try again later.",
      ),
    };
  });

export const removePlaylist = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkPlaylistId(data.id) }))
  .handler(async ({ data }) => {
    await deletePlaylist({
      client: apiClient(),
      path: { playlist_id: data.id },
      throwOnError: true,
    });
  });

export const addToPlaylist = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; videoId: string }) => ({
    id: checkPlaylistId(data.id),
    videoId: checkVideoId(data.videoId),
  }))
  .handler(async ({ data }): Promise<PlaylistItem> => {
    const { data: item } = await addPlaylistItem({
      client: apiClient(),
      path: { playlist_id: data.id, video_id: data.videoId },
      throwOnError: true,
    });
    return item;
  });

/** Move a playlist's video to `position` (0-based). */
export const moveInPlaylist = createServerFn({ method: "POST" })
  .inputValidator(
    (data: { id: number; videoId: string; position: number }) => ({
      id: checkPlaylistId(data.id),
      videoId: checkVideoId(data.videoId),
      position: checkPosition(data.position),
    }),
  )
  .handler(async ({ data }): Promise<PlaylistItem> => {
    const { data: item } = await movePlaylistItem({
      client: apiClient(),
      path: { playlist_id: data.id, video_id: data.videoId },
      body: { position: data.position },
      throwOnError: true,
    });
    return item;
  });

export const removeFromPlaylist = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; videoId: string }) => ({
    id: checkPlaylistId(data.id),
    videoId: checkVideoId(data.videoId),
  }))
  .handler(async ({ data }) => {
    await removePlaylistItem({
      client: apiClient(),
      path: { playlist_id: data.id, video_id: data.videoId },
      throwOnError: true,
    });
  });
