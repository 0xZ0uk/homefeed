import type { Topic } from "@homefeed/api-client";
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import {
  HALF_LIFE_DAYS,
  WEIGHT_STEP,
  clampWeight,
  decayNote,
  formatWeight,
  weightEffect,
} from "#/lib/topics";
import {
  createTopic,
  editTopic,
  reaffirm,
  removeTopic,
  topicsQuery,
  type NewTopic,
  type TopicUpdate,
} from "#/server/topics";

/**
 * Topics: plain-language descriptions with a weight slider. Videos similar to a
 * description are boosted (positive weight) or suppressed (negative weight).
 */
export function TopicsTab() {
  const { data: topics } = useSuspenseQuery(topicsQuery);

  return (
    <div className="flex flex-col gap-6">
      <TopicForm />
      {topics.length === 0 ? (
        <p className="text-gray-600">
          No topics yet. Describe something you want more (or less) of above.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Topics">
          {topics.map((topic) => (
            <TopicRow key={topic.id} topic={topic} />
          ))}
        </ul>
      )}
    </div>
  );
}

function useInvalidateTopics() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: topicsQuery.queryKey });
}

const EMPTY: NewTopic = {
  name: "",
  description: "",
  weight: 0.5,
  decay: false,
};

function TopicForm() {
  const invalidate = useInvalidateTopics();
  const [topic, setTopic] = useState<NewTopic>(EMPTY);
  const mutation = useMutation({
    mutationFn: (data: NewTopic) => createTopic({ data }),
    onSuccess: async (result) => {
      if (result.ok) {
        setTopic(EMPTY);
        await invalidate();
      }
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (topic.name.trim() && topic.description.trim()) mutation.mutate(topic);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <h2 className="font-medium">Add a topic</h2>
      <p className="text-sm text-gray-600">
        Describe a topic in plain language. Videos about it are boosted or
        suppressed by the weight you set, more so the closer they match.
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor="topic-name" className="text-sm font-medium">
          Name
        </label>
        <input
          id="topic-name"
          type="text"
          value={topic.name}
          onChange={(event) => setTopic({ ...topic, name: event.target.value })}
          placeholder="e.g. Hand-tool woodworking"
          maxLength={60}
          required
          className="rounded border px-3 py-2"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="topic-description" className="text-sm font-medium">
          Description
        </label>
        <textarea
          id="topic-description"
          value={topic.description}
          onChange={(event) =>
            setTopic({ ...topic, description: event.target.value })
          }
          placeholder="e.g. Building furniture with chisels, hand planes and saws; joinery techniques"
          maxLength={500}
          rows={2}
          required
          className="rounded border px-3 py-2"
        />
      </div>
      <WeightSlider
        id="topic-weight"
        label="Weight"
        value={topic.weight}
        onChange={(weight) => setTopic({ ...topic, weight })}
      />
      <DecayCheckbox
        checked={topic.decay}
        onChange={(decay) => setTopic({ ...topic, decay })}
      />
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded bg-black px-3 py-2 font-medium text-white disabled:opacity-50"
        >
          {mutation.isPending ? "Adding…" : "Add topic"}
        </button>
        <p role="status" className="min-h-6">
          {mutation.isError && (
            <span className="text-red-600">
              Couldn't add the topic. Try again later.
            </span>
          )}
          {result?.ok === false && (
            <span className="text-red-600">{result.message}</span>
          )}
          {result?.ok === true && `Added “${result.topic.name}”.`}
        </p>
      </div>
    </form>
  );
}

function WeightSlider({
  id,
  label,
  value,
  disabled,
  onChange,
  onCommit,
}: {
  id: string;
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (weight: number) => void;
  /** Called when the user lets go of the slider (pointer up, key up or blur). */
  onCommit?: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <span aria-hidden="true" className="text-xs text-gray-600">
        Suppress
      </span>
      <input
        id={id}
        type="range"
        min={-1}
        max={1}
        step={WEIGHT_STEP}
        value={value}
        disabled={disabled}
        aria-valuetext={`${weightEffect(value)} ${formatWeight(value)}`}
        onChange={(event) => onChange(clampWeight(Number(event.target.value)))}
        onPointerUp={onCommit}
        onKeyUp={onCommit}
        onBlur={onCommit}
        className="w-48"
      />
      <span aria-hidden="true" className="text-xs text-gray-600">
        Boost
      </span>
      <output htmlFor={id} className="w-28 text-sm tabular-nums">
        {weightEffect(value)} {formatWeight(value)}
      </output>
    </div>
  );
}

function DecayCheckbox({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  onChange: (decay: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      Fade over time (the weight halves every {HALF_LIFE_DAYS} days unless you
      reaffirm it)
    </label>
  );
}

function TopicRow({ topic }: { topic: Topic }) {
  const invalidate = useInvalidateTopics();
  const update = useMutation({
    mutationFn: (changes: Omit<TopicUpdate, "id">) =>
      editTopic({ data: { id: topic.id, ...changes } }),
    onSettled: invalidate,
  });
  const renew = useMutation({
    mutationFn: () => reaffirm({ data: { id: topic.id } }),
    onSettled: invalidate,
  });
  const remove = useMutation({
    mutationFn: () => removeTopic({ data: { id: topic.id } }),
    onSettled: invalidate,
  });
  const busy = update.isPending || renew.isPending || remove.isPending;
  // The slider's position while dragging; saved when let go.
  const [weight, setWeight] = useState(topic.weight);
  const [savedWeight, setSavedWeight] = useState(topic.weight);
  if (topic.weight !== savedWeight) {
    // The stored weight changed (saved here or elsewhere): follow it.
    setSavedWeight(topic.weight);
    setWeight(topic.weight);
  }

  function commitWeight() {
    if (weight !== topic.weight && !update.isPending) update.mutate({ weight });
  }

  const failed =
    update.isError ||
    renew.isError ||
    remove.isError ||
    update.data?.ok === false;

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6">
        <p className="min-w-0 break-words font-medium">{topic.name}</p>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Delete the topic “${topic.name}”?`)) {
              remove.mutate();
            }
          }}
          aria-label={`Delete ${topic.name}`}
          className="text-sm text-red-700 underline disabled:opacity-50"
        >
          Delete
        </button>
      </div>
      <p className="break-words text-sm text-gray-700">{topic.description}</p>
      <WeightSlider
        id={`topic-weight-${topic.id}`}
        label="Weight"
        value={weight}
        disabled={remove.isPending}
        onChange={setWeight}
        onCommit={commitWeight}
      />
      <DecayCheckbox
        checked={topic.decay}
        disabled={busy}
        onChange={(decay) => update.mutate({ decay })}
      />
      {topic.decay && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-gray-600">{decayNote(topic)}</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => renew.mutate()}
            className="rounded border px-2 py-1 disabled:opacity-50"
          >
            {renew.isPending ? "Reaffirming…" : "Reaffirm"}
          </button>
        </div>
      )}
      {failed && (
        <p role="alert" className="text-sm text-red-600">
          {update.data?.ok === false
            ? update.data.message
            : "Couldn't save that change. Try again."}
        </p>
      )}
    </li>
  );
}
