import {
  addTopic,
  deleteTopic,
  listTopics,
  reaffirmTopic,
  updateTopic,
  type Topic,
  type TopicUpdateInput,
} from "@homefeed/api-client";
import { queryOptions } from "@tanstack/react-query";
import { createServerFn } from "@tanstack/react-start";

import { apiClient, apiErrorMessage } from "#/server/api";

/** Server functions for the curation page's topics tab. */

export interface NewTopic {
  name: string;
  description: string;
  weight: number;
  decay: boolean;
}

export interface TopicUpdate extends TopicUpdateInput {
  id: number;
}

export type TopicResult =
  { ok: true; topic: Topic } | { ok: false; message: string };

function checkWeight(weight: unknown): number {
  if (typeof weight !== "number" || !(weight >= -1 && weight <= 1)) {
    throw new Error("weight must be a number between -1 and 1");
  }
  return weight;
}

function checkId(id: unknown): number {
  if (!Number.isInteger(id)) throw new Error("id must be an integer");
  return id as number;
}

function topicError(error: unknown, status: number | undefined): string {
  return apiErrorMessage(
    error,
    status === 422
      ? "Enter a name of up to 60 characters and a description of up to 500."
      : "Couldn't save the topic. Try again later.",
  );
}

const getTopics = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await listTopics({
    client: apiClient(),
    throwOnError: true,
  });
  return data;
});

export const topicsQuery = queryOptions({
  queryKey: ["topics"],
  queryFn: () => getTopics(),
});

export const createTopic = createServerFn({ method: "POST" })
  .inputValidator((data: NewTopic): NewTopic => {
    if (typeof data.name !== "string" || typeof data.description !== "string") {
      throw new Error("name and description must be strings");
    }
    return {
      name: data.name.trim(),
      description: data.description.trim(),
      weight: checkWeight(data.weight),
      decay: data.decay === true,
    };
  })
  .handler(async ({ data }): Promise<TopicResult> => {
    const {
      data: topic,
      error,
      response,
    } = await addTopic({ client: apiClient(), body: data });
    if (topic) return { ok: true, topic };
    return { ok: false, message: topicError(error, response?.status) };
  });

export const editTopic = createServerFn({ method: "POST" })
  .inputValidator((data: TopicUpdate) => ({
    id: checkId(data.id),
    name: typeof data.name === "string" ? data.name.trim() : undefined,
    description:
      typeof data.description === "string"
        ? data.description.trim()
        : undefined,
    weight: data.weight == null ? undefined : checkWeight(data.weight),
    decay: typeof data.decay === "boolean" ? data.decay : undefined,
  }))
  .handler(async ({ data: { id, ...body } }): Promise<TopicResult> => {
    const {
      data: topic,
      error,
      response,
    } = await updateTopic({
      client: apiClient(),
      path: { topic_id: id },
      body,
    });
    if (topic) return { ok: true, topic };
    return { ok: false, message: topicError(error, response?.status) };
  });

export const reaffirm = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkId(data.id) }))
  .handler(async ({ data }) => {
    const { data: topic } = await reaffirmTopic({
      client: apiClient(),
      path: { topic_id: data.id },
      throwOnError: true,
    });
    return topic;
  });

export const removeTopic = createServerFn({ method: "POST" })
  .inputValidator((data: { id: number }) => ({ id: checkId(data.id) }))
  .handler(async ({ data }) => {
    await deleteTopic({
      client: apiClient(),
      path: { topic_id: data.id },
      throwOnError: true,
    });
  });
