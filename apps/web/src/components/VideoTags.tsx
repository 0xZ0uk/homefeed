import { Combobox } from "@base-ui/react/combobox";
import type { VideoTagOut } from "@homefeed/api-client";
import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { EyeOff, Plus, Tag, X } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { formatWeight, tagWeights, weightEffect } from "#/lib/topics";
import { cn } from "#/lib/utils";
import {
  addTagToVideo,
  removeTagFromVideo,
  tagSuggestionsQuery,
  type TagEditResult,
} from "#/server/video-tags";
import { topicsQuery } from "#/server/topics";
import { videoQuery } from "#/server/videos";

interface TagOption {
  /** What to add: the tag's label, or the typed text for a new tag. */
  label: string;
  /** Shown in the list. */
  text: string;
  /** How many videos carry it; null for a tag that doesn't exist yet. */
  count: number | null;
}

/**
 * The video's tags (e.g. "rust", "woodworking") as chips linking to their
 * tag page, most confident first, each removable, with a combobox to add one: it suggests existing
 * tags and offers to create the typed one. Edits are saved at once and the
 * outcome announced.
 */
export function VideoTags({
  videoId,
  tags,
}: {
  videoId: string;
  tags: readonly VideoTagOut[];
}) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [message, setMessage] = useState<string | null>(null);
  // Plain chips until the topics load (or if they fail to).
  const { data: topics } = useQuery(topicsQuery);
  const weights = useMemo(() => tagWeights(topics ?? []), [topics]);

  const save = (result: TagEditResult) => {
    if (!result.ok) return setMessage(result.message);
    setMessage(null);
    queryClient.setQueryData(videoQuery(videoId).queryKey, (video) =>
      video ? { ...video, tags: result.tags } : video,
    );
  };
  const add = useMutation({
    mutationFn: (label: string) => addTagToVideo({ data: { videoId, label } }),
    onSuccess: save,
    onError: () => setMessage("Couldn't add that tag. Try again."),
    // A new tag changes what the combobox suggests.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["tag-suggestions"] }),
  });
  const remove = useMutation({
    mutationFn: (slug: string) =>
      removeTagFromVideo({ data: { videoId, slug } }),
    onSuccess: (result) => {
      save(result);
      // The chip with focus is gone; keep keyboard users in the tags.
      input.current?.focus();
    },
    onError: () => setMessage("Couldn't remove that tag. Try again."),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["tag-suggestions"] }),
  });

  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        {tags.length > 0 && (
          <ul aria-label="Tags" className="flex flex-wrap gap-2">
            {tags.map((tag) => {
              const weight = weights.get(tag.slug);
              const muted = weight !== undefined && weight < 0;
              const state = muted ? "Muted" : "Subscribed";
              const signed = weight === undefined ? "" : formatWeight(weight);
              const effect = weight === undefined ? "" : weightEffect(weight);
              const Icon = muted ? EyeOff : Tag;
              return (
                <li key={tag.slug}>
                  <Badge
                    // Subscribed: filled. Muted: dashed outline. Plain: gray.
                    variant={
                      weight === undefined
                        ? "secondary"
                        : muted
                          ? "outline"
                          : "default"
                    }
                    title={
                      weight === undefined
                        ? undefined
                        : `${state} · ${effect} ${signed}`
                    }
                    className={cn(
                      "h-7 gap-0.5 pl-3 text-sm font-normal",
                      weight !== undefined && "pl-2.5 font-medium",
                      muted && "border-dashed text-muted-foreground",
                    )}
                  >
                    <Link
                      to="/tags/$slug"
                      params={{ slug: tag.slug }}
                      className="inline-flex items-center gap-1 rounded-sm hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                    >
                      {weight !== undefined && (
                        <Icon
                          aria-hidden="true"
                          className="size-3.5 shrink-0"
                        />
                      )}
                      <span>{tag.label}</span>
                      {weight !== undefined && (
                        <>
                          <span
                            aria-hidden="true"
                            className={cn(
                              "ml-0.5 rounded-full px-1.5 text-xs leading-5 font-semibold tabular-nums",
                              muted
                                ? "bg-secondary text-secondary-foreground"
                                : "bg-primary-foreground/20",
                            )}
                          >
                            {signed}
                          </span>
                          <span className="sr-only">
                            , {state.toLowerCase()}, {effect.toLowerCase()}{" "}
                            {signed}
                          </span>
                        </>
                      )}
                    </Link>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      className={cn(
                        "size-6 rounded-full",
                        weight !== undefined &&
                          !muted &&
                          "text-primary-foreground hover:bg-primary-foreground/20 hover:text-primary-foreground",
                      )}
                      aria-label={`Remove tag ${tag.label}`}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(tag.slug)}
                    >
                      <X aria-hidden="true" />
                    </Button>
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
        <AddTag
          existing={tags}
          inputRef={input}
          pending={add.isPending}
          onAdd={(label) => add.mutate(label)}
        />
      </div>
      <p role="status" className="min-h-0 text-sm text-destructive">
        {message}
      </p>
    </div>
  );
}

function AddTag({
  existing,
  inputRef,
  pending,
  onAdd,
}: {
  existing: readonly VideoTagOut[];
  inputRef: React.Ref<HTMLInputElement>;
  pending: boolean;
  onAdd: (label: string) => void;
}) {
  const [value, setValue] = useState("");
  const typed = value.trim().replace(/^#/, "").trim();
  const { data: suggestions = [] } = useQuery({
    ...tagSuggestionsQuery(typed),
    placeholderData: keepPreviousData,
  });

  const taken = new Set(existing.map((tag) => tag.slug));
  const options: TagOption[] = suggestions
    .filter((tag) => !taken.has(tag.slug))
    .map((tag) => ({
      label: tag.label,
      text: tag.label,
      count: tag.video_count,
    }));
  const exact = [...suggestions, ...existing].some(
    (tag) => tag.label.toLowerCase() === typed.toLowerCase(),
  );
  // The typed text first, so Enter adds what was typed.
  if (typed !== "" && !exact) {
    options.unshift({ label: typed, text: `Add “${typed}”`, count: null });
  }

  return (
    <Combobox.Root<TagOption>
      items={options}
      // Suggestions are filtered by the API, not here.
      filter={null}
      value={null}
      inputValue={value}
      onInputValueChange={setValue}
      onValueChange={(option) => {
        if (option) {
          onAdd(option.label);
          setValue("");
        }
      }}
      itemToStringLabel={(option) => option.label}
      autoHighlight
    >
      <div className="relative">
        <Plus
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
        />
        <Combobox.Input
          ref={inputRef}
          aria-label="Add tag"
          placeholder="Add tag"
          disabled={pending}
          maxLength={50}
          render={<Input className="h-7 w-32 rounded-4xl pl-7 text-sm" />}
        />
      </div>
      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="z-50">
          <Combobox.Popup className="max-h-60 w-(--anchor-width) min-w-48 overflow-y-auto rounded-xl bg-popover p-1 text-sm text-popover-foreground shadow-lg ring-1 ring-foreground/10 empty:hidden">
            <Combobox.List>
              {(option: TagOption) => (
                <Combobox.Item
                  key={option.text}
                  value={option}
                  className="flex cursor-default items-center justify-between gap-3 rounded-lg px-2.5 py-1.5 outline-none select-none data-highlighted:bg-accent data-highlighted:text-accent-foreground"
                >
                  <span className="truncate">{option.text}</span>
                  {option.count !== null && (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {option.count}
                    </span>
                  )}
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
