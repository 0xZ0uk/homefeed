import type { Ref } from "react";

import { Slider } from "#/components/ui/slider";
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
 * 10. The exact score always shows in a bubble over the thumb. Arrow keys move
 * 0.1, Page Up/Down and Shift+arrows 1.
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
      <Slider
        value={value}
        onValueChange={(next) => onValueChange(Math.round(next * 10) / 10)}
        min={MIN_SCORE}
        max={MAX_SCORE}
        step={0.1}
        largeStep={1}
        disabled={disabled}
        thumbAlignment="edge"
        thumbLabel={label}
        getValueText={(score) => `${formatScore(score)} out of 10`}
        inputRef={inputRef}
        trackClassName="bg-[linear-gradient(to_right_in_oklch,var(--score-low),var(--score-mid),var(--score-high))]"
        bubble={formatScore(value)}
        className="grow"
      />
      <span aria-hidden="true" title="10" className="text-2xl leading-none">
        🔥
      </span>
    </div>
  );
}
