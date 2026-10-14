/**
 * The geometry of the player's progress bar: chapter pieces, SponsorBlock
 * strips and pointer maths. Positions are fractions (0-1) of the bar.
 */

import { chapterIndexAt, type Chapter } from "./chapters";
import type { SkipSegment } from "./sponsor-skip";

/** Colour for a category the table below doesn't know. */
export const SEGMENT_FALLBACK_COLOR = "var(--sb-fallback)";

/** SponsorBlock category to its colour variable (see `styles.css`). */
export const SEGMENT_COLORS: Record<string, string> = {
  sponsor: "var(--sb-sponsor)",
  selfpromo: "var(--sb-selfpromo)",
  interaction: "var(--sb-interaction)",
  intro: "var(--sb-intro)",
  outro: "var(--sb-outro)",
  preview: "var(--sb-preview)",
  hook: "var(--sb-hook)",
  music_offtopic: "var(--sb-music-offtopic)",
  filler: "var(--sb-filler)",
};

/** The colour for a SponsorBlock category. */
export function segmentColor(category: string): string {
  return SEGMENT_COLORS[category] ?? SEGMENT_FALLBACK_COLOR;
}

export interface TimelineRange {
  segment: SkipSegment;
  left: number;
  width: number;
}

export interface ChapterPiece {
  /** Seconds. */
  start: number;
  end: number;
  left: number;
  width: number;
  /** Absent for the bar's untitled stretches. */
  title?: string;
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

/** Where each segment sits on the bar; none while the duration is unknown. */
export function timelineRanges(
  segments: readonly SkipSegment[],
  duration: number | null,
): TimelineRange[] {
  if (!duration || duration <= 0) return [];
  const ranges: TimelineRange[] = [];
  for (const segment of segments) {
    const left = clamp01(segment.start_seconds / duration);
    const right = clamp01(segment.end_seconds / duration);
    if (right > left) ranges.push({ segment, left, width: right - left });
  }
  return ranges;
}

/**
 * The bar split at chapter starts. Without chapters (or a duration) it's one
 * piece; a first chapter after 0 gets an untitled piece before it.
 */
export function chapterPieces(
  chapters: readonly Chapter[],
  duration: number | null,
): ChapterPiece[] {
  if (!duration || duration <= 0) {
    return [{ start: 0, end: 0, left: 0, width: 1 }];
  }
  const starts = chapters
    .filter((c) => c.start_seconds < duration)
    .sort((a, b) => a.start_seconds - b.start_seconds);
  const pieces: ChapterPiece[] = [];
  const add = (start: number, end: number, title?: string) => {
    if (end <= start) return;
    pieces.push({
      start,
      end,
      left: start / duration,
      width: (end - start) / duration,
      ...(title === undefined ? {} : { title }),
    });
  };
  const first = starts[0];
  if (!first || first.start_seconds > 0) {
    add(0, first?.start_seconds ?? duration);
  }
  starts.forEach((chapter, i) => {
    const start = Math.max(0, chapter.start_seconds);
    add(start, starts[i + 1]?.start_seconds ?? duration, chapter.title);
  });
  return pieces.length > 0
    ? pieces
    : [{ start: 0, end: duration, left: 0, width: 1 }];
}

/** What the hover tooltip says about `time`. */
export function describeTime(
  time: number,
  chapters: readonly Chapter[],
  segments: readonly SkipSegment[],
): { chapterTitle: string | null; segment: SkipSegment | null } {
  const chapter = chapters[chapterIndexAt(chapters, time)];
  const segment = segments.find(
    (s) => s.start_seconds <= time && time < s.end_seconds,
  );
  return { chapterTitle: chapter?.title ?? null, segment: segment ?? null };
}

/** How far along the bar `clientX` is, between 0 and 1. */
export function fractionAt(
  clientX: number,
  rect: Pick<DOMRect, "left" | "width">,
): number {
  if (rect.width <= 0) return 0;
  return clamp01((clientX - rect.left) / rect.width);
}
