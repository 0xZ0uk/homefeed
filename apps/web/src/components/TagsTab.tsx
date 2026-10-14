import type { AdminTag } from "@homefeed/api-client";
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, EyeOff } from "lucide-react";
import { useDeferredValue, useState, type FormEvent } from "react";

import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { mergeSummary, videoCount } from "#/lib/tag-admin";
import {
  TAG_FILTERS,
  formatWeight,
  tagState,
  weightEffect,
  type TagFilter,
} from "#/lib/tag-subscriptions";
import {
  mergeTagInto,
  renameTagLabel,
  splitAlias,
  tagAdminKey,
  tagAdminQuery,
  type TagResult,
} from "#/server/tag-admin";
import {
  subscribeToTag,
  tagSubscriptionsQuery,
  unmuteTagBySlug,
  unsubscribeFromTag,
} from "#/server/tag-subscriptions";

/**
 * Tags: the vocabulary the tagger picks from. Subscribe to a tag in one click
 * (its videos rank higher), or unsubscribe or unmute it; the tag's page sets the
 * weight. Rename a tag, merge one into another (its spellings become aliases and
 * its videos move), or split an alias back out into its own tag. Hand-made merges
 * and splits win over the automatic embedding match.
 */
export function TagsTab() {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<TagFilter>("all");
  const q = useDeferredValue(search.trim());
  const { data: tags, isError } = useQuery({
    ...tagAdminQuery(q, filter),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="tag-search" className="text-sm font-medium">
            Search tags
          </label>
          <Input
            id="tag-search"
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Label, slug or alias"
            maxLength={100}
          />
        </div>
        <div
          role="group"
          aria-label="Show tags"
          className="flex flex-wrap gap-2"
        >
          {TAG_FILTERS.map((option) => (
            <Button
              key={option.id}
              type="button"
              size="sm"
              variant={option.id === filter ? "default" : "secondary"}
              aria-pressed={option.id === filter}
              onClick={() => setFilter(option.id)}
              className="px-3"
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>
      {isError ? (
        <p role="alert" className="text-destructive">
          Couldn't load the tags. Try again later.
        </p>
      ) : tags === undefined ? (
        <p className="text-muted-foreground">Loading tags…</p>
      ) : tags.length === 0 ? (
        <p className="text-muted-foreground">{emptyMessage(q, filter)}</p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Tags">
          {tags.map((tag) => (
            <TagRow key={tag.id} tag={tag} />
          ))}
        </ul>
      )}
    </div>
  );
}

function emptyMessage(q: string, filter: TagFilter): string {
  if (q) return "No tags match that search.";
  if (filter === "subscribed") {
    return "You haven't subscribed to any tags yet. Subscribe to one from All.";
  }
  if (filter === "muted") return "You haven't muted any tags.";
  return "No tags yet. Videos get them as they are tagged.";
}

/** Refetches everything that shows tags: this tab, the sidebar's subscribed
 * and muted tags, and tag pages. */
function useInvalidateTags() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: tagAdminKey }),
      queryClient.invalidateQueries({
        queryKey: tagSubscriptionsQuery.queryKey,
      }),
      queryClient.invalidateQueries({ queryKey: ["tag"] }),
    ]);
}

function failure(result: TagResult | undefined, isError: boolean) {
  if (isError) return "Couldn't save that change. Try again.";
  return result?.ok === false ? result.message : null;
}

type Panel = "rename" | "merge" | null;

/**
 * The tag's subscription state and the one-click action for it: Subscribe when
 * there is none, Unsubscribe when subscribed, Unmute when muted.
 */
function SubscriptionControl({ tag }: { tag: AdminTag }) {
  const invalidate = useInvalidateTags();
  const weight = tag.subscription_weight ?? undefined;
  const state = tagState(weight === undefined ? undefined : { weight });
  const slug = tag.slug;
  const toggle = useMutation({
    mutationFn: async () => {
      if (state === "none") {
        const result = await subscribeToTag({ data: { slug } });
        if (!result.ok) throw new Error(result.message);
      } else if (state === "subscribed") {
        await unsubscribeFromTag({ data: { slug } });
      } else {
        await unmuteTagBySlug({ data: { slug } });
      }
    },
    onSettled: invalidate,
  });

  const action = {
    none: {
      label: toggle.isPending ? "Subscribing…" : "Subscribe",
      aria: `Subscribe to ${tag.label}`,
    },
    subscribed: {
      label: toggle.isPending ? "Unsubscribing…" : "Unsubscribe",
      aria: `Unsubscribe from ${tag.label}`,
    },
    muted: {
      label: toggle.isPending ? "Unmuting…" : "Unmute",
      aria: `Unmute ${tag.label}`,
    },
  }[state];

  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-3">
        {state === "subscribed" && (
          <Badge variant="secondary" className="h-6 px-2.5 text-sm">
            <Check aria-hidden="true" />
            Subscribed
          </Badge>
        )}
        {state === "muted" && (
          <Badge
            variant="outline"
            className="h-6 border-dashed px-2.5 text-sm text-muted-foreground"
          >
            <EyeOff aria-hidden="true" />
            Muted
          </Badge>
        )}
        <Button
          type="button"
          variant={state === "none" ? "default" : "secondary"}
          disabled={toggle.isPending}
          aria-label={action.aria}
          onClick={() => toggle.mutate()}
          className="min-w-28 px-4"
        >
          {action.label}
        </Button>
      </div>
      {toggle.isError && (
        <p role="alert" className="text-sm text-destructive">
          {toggle.error.message || "Couldn't save that change. Try again."}
        </p>
      )}
    </div>
  );
}

function TagRow({ tag }: { tag: AdminTag }) {
  const invalidate = useInvalidateTags();
  const [panel, setPanel] = useState<Panel>(null);
  const split = useMutation({
    mutationFn: (alias: string) => splitAlias({ data: { alias } }),
    onSettled: invalidate,
  });
  const error = failure(split.data, split.isError);
  const weight = tag.subscription_weight;

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="min-w-0 break-words">
            <Link
              to="/tags/$slug"
              params={{ slug: tag.slug }}
              className="font-medium hover:underline"
            >
              {tag.label}
            </Link>{" "}
            <span className="text-sm text-muted-foreground">
              {tag.slug} · {videoCount(tag.video_count)}
              {weight != null && (
                <> · {`${weightEffect(weight)} ${formatWeight(weight)}`}</>
              )}
            </span>
          </p>
          <div className="flex gap-4 text-sm">
            <button
              type="button"
              aria-expanded={panel === "rename"}
              aria-label={`Rename ${tag.label}`}
              onClick={() => setPanel(panel === "rename" ? null : "rename")}
              className="underline"
            >
              Rename
            </button>
            <button
              type="button"
              aria-expanded={panel === "merge"}
              aria-label={`Merge ${tag.label} into another tag`}
              onClick={() => setPanel(panel === "merge" ? null : "merge")}
              className="underline"
            >
              Merge into…
            </button>
          </div>
        </div>
        <SubscriptionControl tag={tag} />
      </div>
      {tag.aliases.length > 0 && (
        <ul
          className="flex flex-wrap gap-2 text-sm"
          aria-label={`Spellings of ${tag.label}`}
        >
          {tag.aliases.map((alias) => (
            <li
              key={alias.alias}
              className="flex items-center gap-2 rounded-full bg-secondary px-3 py-0.5"
            >
              <span
                title={alias.source === "user" ? "Set by you" : "Automatic"}
              >
                {alias.alias}
              </span>
              <button
                type="button"
                disabled={split.isPending}
                onClick={() => split.mutate(alias.alias)}
                aria-label={`Split ${alias.alias} out of ${tag.label} into its own tag`}
                className="underline disabled:opacity-50"
              >
                Split
              </button>
            </li>
          ))}
        </ul>
      )}
      {panel === "rename" && (
        <RenameForm tag={tag} onDone={() => setPanel(null)} />
      )}
      {panel === "merge" && (
        <MergePanel tag={tag} onDone={() => setPanel(null)} />
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </li>
  );
}

function RenameForm({ tag, onDone }: { tag: AdminTag; onDone: () => void }) {
  const invalidate = useInvalidateTags();
  const [label, setLabel] = useState(tag.label);
  const rename = useMutation({
    mutationFn: () => renameTagLabel({ data: { id: tag.id, label } }),
    onSuccess: async (result) => {
      if (result.ok) {
        await invalidate();
        onDone();
      }
    },
  });
  const error = failure(rename.data, rename.isError);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (label.trim() && !rename.isPending) rename.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor={`tag-rename-${tag.id}`} className="text-sm font-medium">
        New label
      </label>
      <div className="flex flex-wrap gap-2">
        <Input
          id={`tag-rename-${tag.id}`}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") onDone();
          }}
          maxLength={50}
          required
          autoFocus
          className="max-w-xs"
        />
        <Button type="submit" size="lg" disabled={rename.isPending}>
          {rename.isPending ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={onDone}>
          Cancel
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        The old spelling stays as an alias of this tag.
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}

/** Pick the tag to merge into from a searchable list of radio buttons. */
function MergePanel({ tag, onDone }: { tag: AdminTag; onDone: () => void }) {
  const invalidate = useInvalidateTags();
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search.trim());
  const [targetId, setTargetId] = useState<number | null>(null);
  const { data: found } = useQuery({
    ...tagAdminQuery(q),
    placeholderData: keepPreviousData,
  });
  const candidates = (found ?? []).filter((t) => t.id !== tag.id).slice(0, 8);
  const target = (found ?? []).find((t) => t.id === targetId);
  const merge = useMutation({
    mutationFn: (id: number) =>
      mergeTagInto({ data: { id: tag.id, targetId: id } }),
    onSuccess: async (result) => {
      if (result.ok) {
        await invalidate();
        onDone();
      }
    },
  });
  const error = failure(merge.data, merge.isError);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (targetId !== null && !merge.isPending) merge.mutate(targetId);
  }

  return (
    <form
      onSubmit={onSubmit}
      onKeyDown={(event) => {
        if (event.key === "Escape") onDone();
      }}
      className="flex flex-col gap-2"
    >
      <label htmlFor={`tag-merge-${tag.id}`} className="text-sm font-medium">
        Merge “{tag.label}” into
      </label>
      <Input
        id={`tag-merge-${tag.id}`}
        type="search"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Search for the tag to keep"
        maxLength={100}
        autoFocus
        className="max-w-xs"
      />
      <fieldset className="flex flex-col gap-1">
        <legend className="sr-only">Tag to merge into</legend>
        {candidates.length === 0 && (
          <p className="text-sm text-muted-foreground">No other tags match.</p>
        )}
        {candidates.map((candidate) => (
          <label key={candidate.id} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name={`tag-merge-target-${tag.id}`}
              checked={candidate.id === targetId}
              onChange={() => setTargetId(candidate.id)}
            />
            <span>{candidate.label}</span>
            <span className="text-muted-foreground">
              {videoCount(candidate.video_count)}
            </span>
          </label>
        ))}
      </fieldset>
      {target && (
        <p className="text-sm text-muted-foreground">
          {mergeSummary(tag.label, target.label)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          type="submit"
          size="lg"
          disabled={targetId === null || merge.isPending}
        >
          {merge.isPending ? "Merging…" : "Merge"}
        </Button>
        <Button type="button" variant="ghost" size="lg" onClick={onDone}>
          Cancel
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
