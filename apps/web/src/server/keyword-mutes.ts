import {
  addKeywordMute,
  deleteKeywordMute,
  listKeywordMutes,
  type KeywordMute,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the curation page's mutes tab. */

export type MuteResult =
  | { ok: true; mute: KeywordMute; created: boolean }
  | { ok: false; message: string };

const getKeywordMutes = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listKeywordMutes({
    client: apiClient(),
    throwOnError: true,
  });
  return data;
});

export const keywordMutesQuery = queryOptions({
  queryKey: ["keyword-mutes"],
  queryFn: () => getKeywordMutes(),
});

export const muteKeyword = createServerFn({ method: "POST" })
  .inputValidator((data: { keyword: string }) => {
    if (typeof data.keyword !== "string") {
      throw new Error("keyword must be a string");
    }
    return { keyword: data.keyword.trim() };
  })
  .handler(async ({ data }): Promise<MuteResult> => {
    const {
      data: mute,
      error,
      response,
    } = await addKeywordMute({
      client: apiClient(),
      body: { keyword: data.keyword },
    });
    if (mute) {
      return { ok: true, mute, created: response?.status === 201 };
    }
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        response?.status === 422
          ? "Enter a word or phrase of up to 100 characters."
          : "Couldn't mute that. Try again later.",
      ),
    };
  });

export const unmuteKeyword = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => {
    if (!Number.isInteger(data.id)) throw new Error("id must be an integer");
    return { id: data.id };
  })
  .handler(async ({ data }) => {
    await deleteKeywordMute({
      client: apiClient(),
      path: { mute_id: data.id },
      throwOnError: true,
    });
  });
