import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import type { Chapter } from "#/lib/chapters";
import { cn } from "#/lib/utils";
import { formatDuration } from "#/lib/format";
import {
  chapterPieces,
  describeTime,
  fractionAt,
  segmentColor,
  timelineRanges,
  type ChapterPiece,
  type TimelineRange,
} from "#/lib/player-timeline";
import { categoryLabel, type SkipSegment } from "#/lib/sponsor-skip";

import { useMediaState } from "./media-state";

const KEY_STEPS: Record<string, number> = {
  ArrowLeft: -5,
  ArrowRight: 5,
  PageUp: 10,
  PageDown: -10,
};

/** Space between chapter pieces, in px. */
const GAP = 2;

export interface ScrubberProps {
  media: HTMLVideoElement;
  chapters: readonly Chapter[];
  segments: readonly SkipSegment[];
  /** True while the viewer drags the thumb (the controls stay up). */
  onScrubbingChange?: (scrubbing: boolean) => void;
}

function seek(media: HTMLVideoElement, time: number) {
  media.currentTime = time;
}

/** How much of `piece` is before `time`, between 0 and 1. */
function pieceProgress(piece: ChapterPiece, time: number): number {
  const length = piece.end - piece.start;
  if (length <= 0) return 0;
  return Math.min(1, Math.max(0, (time - piece.start) / length));
}

/** The segment strips that fall in `piece`, positioned within it. */
function pieceStrips(piece: ChapterPiece, ranges: readonly TimelineRange[]) {
  const end = piece.left + piece.width;
  return ranges.flatMap((range) => {
    const left = Math.max(range.left, piece.left);
    const right = Math.min(range.left + range.width, end);
    if (right <= left) return [];
    return [
      {
        segment: range.segment,
        left: (left - piece.left) / piece.width,
        width: (right - left) / piece.width,
      },
    ];
  });
}

/** The player's progress bar: chapters, buffering, SponsorBlock and seeking. */
export function Scrubber({
  media,
  chapters,
  segments,
  onScrubbingChange,
}: ScrubberProps) {
  const { currentTime, duration, bufferedEnd } = useMediaState(media);
  const rootRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [drag, setDrag] = useState<number | null>(null);
  // Where the last drag ended, until the media reports having sought there.
  const [landed, setLanded] = useState<number | null>(null);

  const pieces = useMemo(
    () => chapterPieces(chapters, duration),
    [chapters, duration],
  );
  const ranges = useMemo(
    () => timelineRanges(segments, duration),
    [segments, duration],
  );
  const strips = useMemo(
    () => pieces.map((piece) => pieceStrips(piece, ranges)),
    [pieces, ranges],
  );

  const known = duration !== null;
  const total = duration ?? 0;
  const shownFraction =
    drag ?? landed ?? (known ? Math.min(1, currentTime / total) : 0);
  const shownTime = shownFraction * total;
  const pointer = drag ?? hover;
  const pointerTime = pointer === null ? null : pointer * total;
  const active =
    pointer === null
      ? -1
      : pieces.reduce((found, p, i) => (p.left <= pointer ? i : found), 0);
  const info = useMemo(
    () =>
      pointerTime === null
        ? null
        : describeTime(pointerTime, chapters, segments),
    [pointerTime, chapters, segments],
  );

  useEffect(() => {
    if (landed === null) return;
    const clear = () => setLanded(null);
    media.addEventListener("seeked", clear, { once: true });
    const timer = setTimeout(clear, 1000);
    return () => {
      media.removeEventListener("seeked", clear);
      clearTimeout(timer);
    };
  }, [media, landed]);

  // Keep the tooltip inside the bar's edges.
  useLayoutEffect(() => {
    const root = rootRef.current;
    const tooltip = tooltipRef.current;
    if (!root || !tooltip || pointer === null) return;
    const half = tooltip.offsetWidth / 2;
    const x = pointer * root.clientWidth;
    tooltip.style.left = `${Math.min(
      Math.max(x, half),
      Math.max(half, root.clientWidth - half),
    )}px`;
  });

  const fractionOf = (event: PointerEvent) =>
    fractionAt(event.clientX, event.currentTarget.getBoundingClientRect());

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (!known || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrag(fractionOf(event));
    setHover(null);
    onScrubbingChange?.(true);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!known) return;
    const fraction = fractionOf(event);
    if (drag !== null) setDrag(fraction);
    else if (event.pointerType !== "touch") setHover(fraction);
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>, commit: boolean) => {
    if (drag === null) return;
    const fraction = fractionOf(event);
    setDrag(null);
    if (event.pointerType === "touch") setHover(null);
    onScrubbingChange?.(false);
    if (commit && known) {
      setLanded(fraction);
      seek(media, fraction * total);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!known) return;
    let target: number;
    if (event.key === "Home") target = 0;
    else if (event.key === "End") target = total;
    else if (event.key in KEY_STEPS)
      target = media.currentTime + (KEY_STEPS[event.key] ?? 0);
    else return;
    event.preventDefault();
    event.stopPropagation();
    seek(media, Math.min(total, Math.max(0, target)));
  };

  return (
    <div
      ref={rootRef}
      {...(known
        ? {
            role: "slider",
            tabIndex: 0,
            "aria-label": "Seek",
            "aria-orientation": "horizontal",
            "aria-valuemin": 0,
            "aria-valuemax": total,
            "aria-valuenow": Math.floor(shownTime),
            "aria-valuetext": `${formatDuration(shownTime)} of ${formatDuration(total)}`,
          }
        : { "aria-hidden": true })}
      data-dragging={drag !== null || undefined}
      className={cn(
        "group/scrub relative h-4 w-full touch-none select-none rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-white/70",
        known && "cursor-pointer",
      )}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => endDrag(event, true)}
      onPointerCancel={(event) => endDrag(event, false)}
      onPointerLeave={() => setHover(null)}
      onKeyDown={onKeyDown}
    >
      {pieces.map((piece, i) => {
        const last = i === pieces.length - 1;
        return (
          <div
            key={piece.start}
            className="pointer-events-none absolute inset-y-0 flex items-center"
            style={{
              left: `${piece.left * 100}%`,
              width: last
                ? `${piece.width * 100}%`
                : `calc(${piece.width * 100}% - ${GAP}px)`,
            }}
          >
            <div
              data-active={i === active || undefined}
              className="relative h-[3px] w-full overflow-hidden rounded-[1px] bg-white/20 transition-[height] duration-100 ease-out data-active:h-[5px] motion-reduce:transition-none"
            >
              <Fill
                className="bg-white/40"
                fraction={pieceProgress(piece, bufferedEnd)}
              />
              {pointer !== null && (
                <Fill
                  className="bg-white/50"
                  fraction={pieceProgress(piece, pointer * total)}
                />
              )}
              <Fill
                className="bg-brand"
                fraction={pieceProgress(piece, shownTime)}
              />
              {strips[i]?.map((strip) => (
                <div
                  key={strip.segment.id}
                  className="absolute inset-y-0 opacity-80"
                  style={{
                    left: `${strip.left * 100}%`,
                    width: `${strip.width * 100}%`,
                    backgroundColor: segmentColor(strip.segment.category),
                  }}
                />
              ))}
            </div>
          </div>
        );
      })}

      {known && (
        <div
          className="pointer-events-none absolute top-1/2 size-[13px] -translate-x-1/2 -translate-y-1/2 scale-0 rounded-full bg-brand shadow-sm transition-[scale] duration-150 ease-out group-hover/scrub:scale-100 group-focus-visible/scrub:scale-100 group-data-dragging/scrub:scale-100 motion-reduce:transition-none"
          style={{ left: `${shownFraction * 100}%` }}
        />
      )}

      {info && pointerTime !== null && (
        <div
          ref={tooltipRef}
          className="pointer-events-none absolute bottom-full mb-2 flex max-w-64 -translate-x-1/2 flex-col items-center gap-0.5 rounded-md bg-black/80 px-2 py-1 text-center text-xs whitespace-nowrap text-white tabular-nums"
        >
          {info.chapterTitle && (
            <span className="max-w-full truncate">{info.chapterTitle}</span>
          )}
          <span className="font-medium">{formatDuration(pointerTime)}</span>
          {info.segment && (
            <span className="flex items-center gap-1.5 text-white/80">
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: segmentColor(info.segment.category) }}
              />
              {categoryLabel(info.segment.category)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** A piece's fill, `fraction` of its width. */
function Fill({
  className,
  fraction,
}: {
  className: string;
  fraction: number;
}) {
  return (
    <div
      className={cn("absolute inset-0 origin-left", className)}
      style={{ transform: `scaleX(${fraction})` }}
    />
  );
}
