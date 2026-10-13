import { Slider } from "@base-ui/react/slider";
import type { Ref } from "react";

import { MAX_SCORE, MIN_SCORE, formatScore } from "#/lib/scores";
import { cn } from "#/lib/utils";

interface ScoreSliderProps {
  value: number;
  onValueChange: (score: number) => void;
  /** Names the slider for screen readers, e.g. "Score". */
  label: string;
  disabled?: boolean;
  /** The thumb's range input, e.g. to focus it. */
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
}

/**
 * A 1 to 10 score in steps of 0.1 on a red-to-green track, 💩 at 1 and 🔥 at
 * 10. The exact score shows in a tooltip over the thumb while it is hovered,
 * focused or dragged. Arrow keys move 0.1, Page Up/Down and Shift+arrows 1.
 */
export function ScoreSlider({
  value,
  onValueChange,
  label,
  disabled = false,
  inputRef,
  className,
}: ScoreSliderProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span aria-hidden="true" title="1" className="text-2xl leading-none">
        💩
      </span>
      <Slider.Root
        value={value}
        onValueChange={(next) => onValueChange(Math.round(next * 10) / 10)}
        min={MIN_SCORE}
        max={MAX_SCORE}
        step={0.1}
        largeStep={1}
        disabled={disabled}
        thumbAlignment="edge"
        className="grow"
      >
        <Slider.Control className="relative flex h-8 w-full touch-none items-center select-none data-disabled:opacity-50">
          <Slider.Track className="h-2 w-full rounded-full bg-[linear-gradient(to_right_in_oklch,var(--score-low),var(--score-mid),var(--score-high))]" />
          <Slider.Thumb
            inputRef={inputRef}
            getAriaLabel={() => label}
            getAriaValueText={(_, score) => `${formatScore(score)} out of 10`}
            className="group size-5 rounded-full border-2 border-background bg-foreground shadow-md outline-none transition-[scale,box-shadow] duration-150 ease-out select-none has-focus-visible:ring-3 has-focus-visible:ring-ring/50 data-dragging:scale-110 motion-reduce:transition-none"
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 translate-y-1 rounded-md bg-foreground px-2 py-1 text-sm font-semibold text-background tabular-nums opacity-0 shadow-md transition-[opacity,translate] duration-150 ease-out group-hover:translate-y-0 group-hover:opacity-100 group-has-focus:translate-y-0 group-has-focus:opacity-100 group-data-dragging:translate-y-0 group-data-dragging:opacity-100 motion-reduce:transition-none"
            >
              {formatScore(value)}
            </span>
          </Slider.Thumb>
        </Slider.Control>
      </Slider.Root>
      <span aria-hidden="true" title="10" className="text-2xl leading-none">
        🔥
      </span>
    </div>
  );
}
