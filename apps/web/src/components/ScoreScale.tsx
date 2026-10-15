import {
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type PointerEvent,
  type Ref,
} from "react";

import { ScoreFace } from "#/components/ScoreFace";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "#/components/ui/tooltip";
import {
  MAX_SCORE,
  MIN_SCORE,
  SCORES,
  scoreLabel,
  scoreText,
} from "#/lib/scores";
import { cn } from "#/lib/utils";

interface ScoreScaleProps {
  /** The picked score, or null when none is picked. */
  value: number | null;
  /**
   * A face was clicked (or pressed with Enter or Space), or a drag ended on
   * it. It can be the face already picked: the caller decides what that
   * means, e.g. removing the rating.
   */
  onPick: (score: number) => void;
  /** Names the group for screen readers, e.g. "Rate this video". */
  label: string;
  disabled?: boolean;
  /** The face that takes focus (the picked one, else the first). */
  buttonRef?: Ref<HTMLButtonElement>;
  className?: string;
}

/**
 * A 1 to 10 score as ten face buttons on a pill, a wail at 1 and a grin at 10.
 * The picked face grows into a coloured disc that slides along the pill, its
 * word in a bubble above. A click picks at once; a drag shows each face it
 * passes and picks the one it ends on. Arrow keys, Home and End move focus
 * without picking, and Enter or Space picks.
 */
export function ScoreScale({
  value,
  onPick,
  label,
  disabled = false,
  buttonRef,
  className,
}: ScoreScaleProps) {
  const track = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<number, HTMLButtonElement>());
  // The face under the pointer while it is pressed; null when not dragging.
  const [dragged, setDragged] = useState<number | null>(null);
  // The face that Tab lands on, moved by the arrow keys.
  const [focusable, setFocusable] = useState<number | null>(null);
  const shown = dragged ?? value;
  const tabStop = focusable ?? value ?? MIN_SCORE;

  const scoreAt = (clientX: number) => {
    const rect = track.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return null;
    const cell = Math.floor(
      ((clientX - rect.left) / rect.width) * SCORES.length,
    );
    return Math.min(MAX_SCORE, Math.max(MIN_SCORE, MIN_SCORE + cell));
  };

  const focus = (score: number) => {
    setFocusable(score);
    buttons.current.get(score)?.focus({ preventScroll: true });
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    // Keep the press on the pill so a drag follows the pointer across faces;
    // focus moves to the face it ends on.
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragged(scoreAt(event.clientX));
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (dragged !== null) setDragged(scoreAt(event.clientX));
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (dragged === null) return;
    setDragged(null);
    const score = scoreAt(event.clientX);
    if (score === null) return;
    focus(score);
    onPick(score);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step: Record<string, number> = {
      ArrowLeft: -1,
      ArrowDown: -1,
      ArrowRight: 1,
      ArrowUp: 1,
    };
    let next: number | null = null;
    if (event.key in step) next = tabStop + (step[event.key] ?? 0);
    else if (event.key === "Home") next = MIN_SCORE;
    else if (event.key === "End") next = MAX_SCORE;
    if (next === null) return;
    event.preventDefault();
    focus(Math.min(MAX_SCORE, Math.max(MIN_SCORE, next)));
  };

  // Pointer clicks are handled on the pill (above); this is for Enter, Space
  // and assistive tech, whose clicks have no pointer position (detail 0).
  const onClick = (event: MouseEvent<HTMLButtonElement>, score: number) => {
    if (event.detail !== 0) return;
    setFocusable(score);
    onPick(score);
  };

  return (
    <div
      role="group"
      aria-label={label}
      aria-disabled={disabled || undefined}
      className={cn(
        "group/scale pt-9 pb-1.5 aria-disabled:opacity-50",
        className,
      )}
    >
      <div
        ref={track}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDragged(null)}
        onKeyDown={onKeyDown}
        className="relative grid h-11 touch-pan-y grid-cols-10 rounded-full bg-secondary select-none"
      >
        <TooltipProvider delay={200} closeDelay={0}>
          {SCORES.map((score) => (
            <Tooltip
              key={score}
              // The picked face already wears its word in the bubble.
              disabled={disabled || dragged !== null || shown === score}
            >
              <TooltipTrigger
                render={
                  <button
                    ref={(node) => {
                      if (node) buttons.current.set(score, node);
                      else buttons.current.delete(score);
                      if (score === tabStop) assignRef(buttonRef, node);
                    }}
                    type="button"
                    aria-label={scoreText(score)}
                    aria-pressed={value === score}
                    tabIndex={score === tabStop ? 0 : -1}
                    disabled={disabled}
                    onFocus={() => setFocusable(score)}
                    onClick={(event) => onClick(event, score)}
                    className={cn(
                      "group/face relative flex items-center justify-center text-muted-foreground/70 outline-none transition-colors hover:text-foreground motion-reduce:transition-none",
                      // A short divider before every face but the first.
                      score > MIN_SCORE &&
                        "before:absolute before:inset-y-3 before:left-0 before:w-px before:bg-border",
                      disabled ? "cursor-default" : "cursor-pointer",
                    )}
                  >
                    <ScoreFace
                      score={score}
                      title={scoreLabel(score)}
                      className={cn(
                        "pointer-events-none size-6 rounded-full transition-[scale,opacity] duration-150 ease-out group-focus-visible/face:ring-3 group-focus-visible/face:ring-ring/50 motion-reduce:transition-none",
                        shown === score && "opacity-0",
                        !disabled && "group-hover/face:scale-110",
                      )}
                    />
                  </button>
                }
              />
              <TooltipContent>
                {score} · {scoreLabel(score)}
              </TooltipContent>
            </Tooltip>
          ))}
        </TooltipProvider>
        {shown !== null && (
          <div
            aria-hidden="true"
            data-dragging={dragged !== null || undefined}
            style={{
              left: `${((shown - MIN_SCORE + 0.5) / SCORES.length) * 100}%`,
            }}
            className="pointer-events-none absolute top-1/2 aspect-square w-[clamp(2.75rem,calc(10%+1.25rem),3.5rem)] -translate-x-1/2 -translate-y-1/2 rounded-full shadow-md transition-[left,scale,box-shadow] duration-200 ease-out group-has-[[aria-pressed=true]:focus-visible]/scale:ring-3 group-has-[[aria-pressed=true]:focus-visible]/scale:ring-ring/50 data-dragging:scale-105 data-dragging:duration-100 motion-reduce:transition-none"
          >
            <ScoreFace score={shown} filled className="size-full" />
            <span className="absolute bottom-full left-1/2 mb-1.5 -translate-x-1/2 rounded-md bg-foreground px-2 py-1 text-sm font-semibold whitespace-nowrap text-background shadow-md">
              {scoreLabel(shown)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function assignRef<T>(ref: Ref<T> | undefined, node: T | null) {
  if (typeof ref === "function") ref(node);
  else if (ref) ref.current = node;
}
