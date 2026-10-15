import { Slider } from "#/components/ui/slider";
import {
  WEIGHT_STEP,
  clampWeight,
  formatWeight,
  weightEffect,
} from "#/lib/tag-subscriptions";
import { cn } from "#/lib/utils";

/**
 * The tag weight slider, from Suppress (-1) to Boost (+1), on the tag page and
 * in the Rebalance popover.
 */
export function WeightSlider({
  id,
  label,
  hideLabel,
  value,
  disabled,
  stacked = false,
  onChange,
  onCommit,
}: {
  id: string;
  label: string;
  /** Name the slider for screen readers only, for a row that already shows
   * what the slider is for, e.g. under its topic's name. */
  hideLabel?: boolean;
  value: number;
  disabled?: boolean;
  /** Puts the label on a line of its own, for a narrow place with several. */
  stacked?: boolean;
  onChange: (weight: number) => void;
  /** Called with the slider's value when the user lets go of it (pointer up
   * or key up). */
  onCommit?: (weight: number) => void;
}) {
  // Percent along the track, with 0 in the middle.
  const percent = ((value + 1) / 2) * 100;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {/* Hidden from the reading order, the name still reaches the slider
          through aria-labelledby, and is not read again beside it. */}
      <span
        id={id}
        aria-hidden={hideLabel ? "true" : undefined}
        className={
          hideLabel
            ? "sr-only"
            : cn("text-sm font-medium", stacked && "basis-full")
        }
      >
        {label}
      </span>
      <span aria-hidden="true" className="text-xs text-muted-foreground">
        Suppress
      </span>
      <Slider
        value={value}
        onValueChange={(next) => onChange(clampWeight(next))}
        onValueCommitted={(next) => onCommit?.(clampWeight(next))}
        min={-1}
        max={1}
        step={WEIGHT_STEP}
        disabled={disabled}
        thumbAlignment="center"
        aria-labelledby={id}
        thumbLabel={label}
        getValueText={(weight) =>
          `${weightEffect(weight)} ${formatWeight(weight)}`
        }
        track={
          <>
            <span
              aria-hidden="true"
              className={
                value < 0
                  ? "absolute inset-y-0 bg-muted-foreground/60"
                  : "absolute inset-y-0 bg-primary"
              }
              style={{
                left: `${Math.min(50, percent)}%`,
                width: `${Math.abs(percent - 50)}%`,
              }}
            />
            <span
              aria-hidden="true"
              className="absolute top-1/2 left-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted-foreground"
            />
          </>
        }
        className="w-48"
      />
      <span aria-hidden="true" className="text-xs text-muted-foreground">
        Boost
      </span>
      <output className="w-28 text-sm tabular-nums">
        {weightEffect(value)} {formatWeight(value)}
      </output>
    </div>
  );
}
