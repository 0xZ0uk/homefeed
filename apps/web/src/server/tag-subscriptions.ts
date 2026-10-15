import {
  listTagSubscriptions,
  muteTag,
  subscribeTag,
  unmuteTag,
  unsubscribeTag,
  updateTagSubscription,
  type TagSubscription,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { isTagSlug } from "#/lib/tags";
import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for subscribing to and muting tags. */

export type { TagSubscription };

export type SubscriptionResult =
  { ok: true; subscription: TagSubscription } | { ok: false; message: string };

function checkSlug(data: { slug: string }): { slug: string } {
  if (typeof data.slug !== "string" || !isTagSlug(data.slug)) {
    throw new Error("Not a tag slug");
  }
  return { slug: data.slug };
}

function failure(error: unknown): SubscriptionResult {
  return {
    ok: false,
    message: apiErrorMessage(error, "Couldn't save that change. Try again."),
  };
}

const getTagSubscriptions = createServerFn({ method: "GET" }).handler(
  async () => {
    const { data } = await listTagSubscriptions({
      client: apiClient(),
      throwOnError: true,
    });
    return data;
  },
);

/** Every subscribed and muted tag, for Explore's lists and the tag chips. */
export const tagSubscriptionsQuery = queryOptions({
  queryKey: ["tag-subscriptions"],
  queryFn: () => getTagSubscriptions(),
});

/** Subscribes to a tag (or returns its existing subscription or mute). */
export const subscribeToTag = createServerFn({ method: "POST" })
  .inputValidator(checkSlug)
  .handler(async ({ data }): Promise<SubscriptionResult> => {
    const { data: subscription, error } = await subscribeTag({
      client: apiClient(),
      path: { slug: data.slug },
    });
    return subscription ? { ok: true, subscription } : failure(error);
  });

export const unsubscribeFromTag = createServerFn({ method: "POST" })
  .inputValidator(checkSlug)
  .handler(async ({ data }) => {
    await unsubscribeTag({
      client: apiClient(),
      path: { slug: data.slug },
      throwOnError: true,
    });
  });

/** Mutes a tag: a negative weight (or an existing subscription is flipped). */
export const muteTagBySlug = createServerFn({ method: "POST" })
  .inputValidator(checkSlug)
  .handler(async ({ data }): Promise<SubscriptionResult> => {
    const { data: subscription, error } = await muteTag({
      client: apiClient(),
      path: { slug: data.slug },
    });
    return subscription ? { ok: true, subscription } : failure(error);
  });

export const unmuteTagBySlug = createServerFn({ method: "POST" })
  .inputValidator(checkSlug)
  .handler(async ({ data }) => {
    await unmuteTag({
      client: apiClient(),
      path: { slug: data.slug },
      throwOnError: true,
    });
  });

export interface SubscriptionUpdate {
  slug: string;
  weight?: number;
  hide?: boolean;
}

/** Changes a subscribed or muted tag's weight, or hides its videos (at -1). */
export const editTagSubscription = createServerFn({ method: "POST" })
  .inputValidator((data: SubscriptionUpdate) => {
    const { slug } = checkSlug(data);
    if (
      data.weight != null &&
      (typeof data.weight !== "number" ||
        !(data.weight >= -1 && data.weight <= 1))
    ) {
      throw new Error("weight must be a number between -1 and 1");
    }
    return {
      slug,
      weight: data.weight ?? undefined,
      hide: typeof data.hide === "boolean" ? data.hide : undefined,
    };
  })
  .handler(async ({ data: { slug, ...body } }): Promise<SubscriptionResult> => {
    const { data: subscription, error } = await updateTagSubscription({
      client: apiClient(),
      path: { slug },
      body,
    });
    return subscription ? { ok: true, subscription } : failure(error);
  });
