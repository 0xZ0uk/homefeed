import {
  getUserSettings,
  updateUserSettings,
  type SettingsChanges,
  type SettingsOut,
  type UserSettingKey,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the settings page's feed, schedule, tagging and SponsorBlock sections. */

export type { SettingsChanges, SettingsOut, UserSettingKey };

export type SaveSettingsResult =
  { ok: true; settings: SettingsOut } | { ok: false; message: string };

const fetchSettings = createServerFn({ method: "GET" }).handler(
  async (): Promise<SettingsOut> => {
    const { data } = await getUserSettings({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

export const settingsQuery = queryOptions({
  queryKey: ["settings"],
  queryFn: () => fetchSettings(),
});

/** Change some settings (`set`) and put others back to their defaults (`reset`). */
export const saveSettings = createServerFn({ method: "POST" })
  .inputValidator(
    (data: { set?: SettingsChanges; reset?: UserSettingKey[] }) => {
      if (
        data.set !== undefined &&
        (typeof data.set !== "object" || !data.set)
      ) {
        throw new Error("set must be an object");
      }
      if (data.reset !== undefined && !Array.isArray(data.reset)) {
        throw new Error("reset must be a list");
      }
      return { set: data.set ?? {}, reset: data.reset ?? [] };
    },
  )
  .handler(async ({ data }): Promise<SaveSettingsResult> => {
    const { data: settings, error } = await updateUserSettings({
      client: apiClient(),
      body: data,
    });
    if (settings) return { ok: true, settings };
    return {
      ok: false,
      message: apiErrorMessage(
        error,
        "Couldn't save your settings. Try again later.",
      ),
    };
  });
