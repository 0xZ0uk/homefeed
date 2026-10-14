import {
  listTagsAdmin,
  mergeTag,
  renameTag,
  splitTagAlias,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { TAG_FILTERS, type TagFilter } from "#/lib/tag-subscriptions";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the Subscriptions page's tags tab. */

export type TagResult = { ok: true } | { ok: false; message: string };

function checkId(id: unknown): number {
  if (!Number.isInteger(id)) throw new Error("id must be an integer");
  return id as number;
}

const getTagAdmin = createServerFn({ method: "GET" })
  .inputValidator((data: { q: string; filter?: TagFilter }) => ({
    q: typeof data.q === "string" ? data.q.trim().slice(0, 100) : "",
    filter: TAG_FILTERS.find((f) => f.id === data.filter)?.id ?? "all",
  }))
  .handler(async ({ data }) => {
    const { data: tags } = await listTagsAdmin({
      client: apiClient(),
      query: {
        q: data.q || undefined,
        subscription: data.filter === "all" ? undefined : data.filter,
      },
      throwOnError: true,
    });
    return tags;
  });

/** The tags matching `q`, all of them or only the subscribed or muted ones. */
export const tagAdminQuery = (q: string, filter: TagFilter = "all") =>
  queryOptions({
    queryKey: ["tag-admin", q, filter],
    queryFn: () => getTagAdmin({ data: { q, filter } }),
  });

/** Prefix of every tag-admin query, to invalidate them all. */
export const tagAdminKey = ["tag-admin"] as const;

export const renameTagLabel = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; label: string }) => ({
    id: checkId(data.id),
    label: typeof data.label === "string" ? data.label.trim() : "",
  }))
  .handler(async ({ data }): Promise<TagResult> => {
    const { error } = await renameTag({
      client: apiClient(),
      path: { tag_id: data.id },
      body: { label: data.label },
    });
    if (!error) return { ok: true };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Enter a label with letters or digits, up to 50 characters.",
      ),
    };
  });

export const mergeTagInto = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number; targetId: number }) => ({
    id: checkId(data.id),
    targetId: checkId(data.targetId),
  }))
  .handler(async ({ data }): Promise<TagResult> => {
    const { error } = await mergeTag({
      client: apiClient(),
      path: { tag_id: data.id },
      body: { target_id: data.targetId },
    });
    if (!error) return { ok: true };
    return {
      ok: false,
      message: apiErrorMessage(error, "Couldn't merge the tags. Try again."),
    };
  });

export const splitAlias = createServerFn({ method: "POST" })
  .inputValidator((data: { alias: string }) => {
    if (typeof data.alias !== "string" || !data.alias) {
      throw new Error("alias must be a string");
    }
    return { alias: data.alias };
  })
  .handler(async ({ data }): Promise<TagResult> => {
    const { error } = await splitTagAlias({
      client: apiClient(),
      path: { alias: data.alias },
    });
    if (!error) return { ok: true };
    return {
      ok: false,
      message: apiErrorMessage(error, "Couldn't split the alias. Try again."),
    };
  });
