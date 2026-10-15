import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useId, useState } from "react";

import {
  MIX_PRESETS,
  currentMix,
  describeMix,
  mixOf,
  mixSettings,
  type MixPreset,
} from "#/lib/feed-mix";
import { cn } from "#/lib/utils";
import { saveSettings, settingsQuery } from "#/server/settings";

/**
 * The "Mix" dial: how adventurous the next feed is, as three choices in a
 * radio group, Familiar, Balanced and Adventurous. Each stands for a number of
 * discovery slots and for the most of the feed one topic may take (see
 * `MIX_PRESETS`); choosing one saves both as settings at once. When the
 * settings are something else (set by hand on the Settings page) the dial says
 * "Custom", with a link there, and no choice is picked.
 *
 * It only changes the settings: a feed already built stays as it is, and
 * `onChanged` tells the caller to say so, with a way to build it again.
 */
export function MixDial({ onChanged }: { onChanged: () => void }) {
  const name = useId();
  const descriptionId = useId();
  const queryClient = useQueryClient();
  const { data: settings, isError, refetch } = useQuery(settingsQuery);
  // The choice being saved, shown at once and until the save is done.
  const [picked, setPicked] = useState<MixPreset | null>(null);
  const save = useMutation({
    mutationFn: ({
      preset,
      feedSize,
    }: {
      preset: MixPreset;
      feedSize: number;
    }) => saveSettings({ data: { set: mixSettings(preset, feedSize) } }),
    onSuccess: (result) => {
      if (!result.ok) return;
      queryClient.setQueryData(settingsQuery.queryKey, result.settings);
      onChanged();
    },
    onSettled: () => setPicked(null),
  });

  if (!settings) {
    return isError ? (
      <div role="alert" className="flex flex-col items-start gap-1 text-sm">
        <p>Couldn't load the mix. The API may be down.</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="rounded-sm underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          Try again
        </button>
      </div>
    ) : (
      <p className="text-sm text-muted-foreground">Loading the mix…</p>
    );
  }

  const { values } = settings;
  const choice = picked ?? currentMix(values);
  const { slots, share } = mixOf(choice, values);
  let failure: string | null = null;
  if (save.isError) failure = "Couldn't save the mix. Try again.";
  else if (save.data && !save.data.ok) failure = save.data.message;

  return (
    <fieldset
      role="radiogroup"
      className="flex flex-col gap-2"
      aria-describedby={descriptionId}
    >
      <legend className="mb-2 text-sm font-medium">Mix</legend>
      <div className="grid grid-cols-3 gap-1 rounded-lg bg-secondary p-1">
        {MIX_PRESETS.map(({ value, label }) => (
          <label key={value} className="relative flex cursor-pointer">
            <input
              type="radio"
              name={name}
              value={value}
              checked={choice === value}
              onChange={() => {
                if (picked !== null) return;
                setPicked(value);
                save.mutate({ preset: value, feedSize: values.feed_size });
              }}
              className="peer sr-only"
            />
            <span
              className={cn(
                "flex h-8 w-full items-center justify-center gap-1 rounded-md px-1.5 text-sm font-medium",
                "peer-focus-visible:ring-3 peer-focus-visible:ring-ring/50",
                choice === value
                  ? "bg-primary text-primary-foreground"
                  : "hover:bg-accent",
              )}
            >
              {choice === value && (
                <Check aria-hidden="true" className="size-3.5 shrink-0" />
              )}
              {label}
            </span>
          </label>
        ))}
      </div>
      <p id={descriptionId} className="text-xs text-muted-foreground">
        {choice === "custom" && (
          <>
            <span className="font-medium text-foreground">Custom:</span>{" "}
          </>
        )}
        {describeMix(slots, share)}
        {choice === "custom" && (
          <>
            {" "}
            <Link
              to="/settings"
              className="rounded-sm underline outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              Change it in Settings
            </Link>
            .
          </>
        )}
      </p>
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      )}
    </fieldset>
  );
}
