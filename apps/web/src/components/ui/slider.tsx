import { Slider as SliderPrimitive } from "@base-ui/react/slider";
import type { ReactNode, Ref } from "react";

import { cn } from "#/lib/utils";

interface SliderProps extends Omit<
  SliderPrimitive.Root.Props<number>,
  "children" | "render"
> {
  /** Names the thumb's input for screen readers. */
  thumbLabel: string;
  /** Spoken value, e.g. "7.5 out of 10". */
  getValueText?: (value: number) => string;
  /** The thumb's range input, e.g. to focus it. */
  inputRef?: Ref<HTMLInputElement>;
  /** Classes for the track (the gradient or fill colour goes here). */
  trackClassName?: string;
  /** Content inside the track, e.g. an indicator fill or a tick. */
  track?: ReactNode;
  /** Text of an always-visible bubble over the thumb. */
  bubble?: ReactNode;
}

/** The shared slider look: a tall hit area, a thin rounded track and a round
 * thumb with an optional value bubble. */
function Slider({
  thumbLabel,
  getValueText,
  inputRef,
  trackClassName,
  track,
  bubble,
  thumbAlignment = "edge",
  ...props
}: SliderProps) {
  return (
    <SliderPrimitive.Root
      data-slot="slider"
      thumbAlignment={thumbAlignment}
      {...props}
    >
      <SliderPrimitive.Control className="relative flex h-8 w-full touch-none items-center select-none data-disabled:opacity-50">
        <SliderPrimitive.Track
          className={cn(
            "relative h-2 w-full rounded-full bg-secondary",
            trackClassName,
          )}
        >
          {track}
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb
          inputRef={inputRef}
          getAriaLabel={() => thumbLabel}
          getAriaValueText={
            getValueText ? (_, value) => getValueText(value) : undefined
          }
          className="size-5 rounded-full border-2 border-background bg-foreground shadow-md outline-none transition-[scale,box-shadow] duration-150 ease-out select-none has-focus-visible:ring-3 has-focus-visible:ring-ring/50 data-dragging:scale-110 motion-reduce:transition-none"
        >
          {bubble != null && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute bottom-full left-1/2 mb-2 -translate-x-1/2 rounded-md bg-foreground px-2 py-1 text-sm font-semibold text-background tabular-nums shadow-md"
            >
              {bubble}
            </span>
          )}
        </SliderPrimitive.Thumb>
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  );
}

export { Slider };
