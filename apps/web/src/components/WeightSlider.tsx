import type { SyntheticEvent } from "react";

import {
  WEIGHT_STEP,
  clampWeight,
  formatWeight,
  weightEffect,
} from "#/lib/topics";

/** The topic weight slider, from Suppress (-1) to Boost (+1); shared by the
 * Topics tab and the tag page. */
export function WeightSlider({
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
  /** Called with the slider's value when the user lets go of it (pointer up,
   * key up or blur). */
  onCommit?: (weight: number) => void;
}) {
  // Read from the element: a key can go up before React re-renders with the
  // value it just set.
  const commit = (event: SyntheticEvent<HTMLInputElement>) =>
    onCommit?.(clampWeight(Number(event.currentTarget.value)));

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <span aria-hidden="true" className="text-xs text-muted-foreground">
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
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
        className="w-48"
      />
      <span aria-hidden="true" className="text-xs text-muted-foreground">
        Boost
      </span>
      <output htmlFor={id} className="w-28 text-sm tabular-nums">
        {weightEffect(value)} {formatWeight(value)}
      </output>
    </div>
  );
}
