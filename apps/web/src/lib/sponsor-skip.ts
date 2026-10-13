/**
 * Skipping SponsorBlock segments in a `<video>` element.
 *
 * A segment is skipped when playback runs into it: once per visit, so seeking
 * back into it (or "Undo") plays it. Seeking into a segment counts as choosing
 * to watch it, so it isn't skipped either.
 */

import type { MediaLike } from "./player-events";

/** A segment to skip, as `GET /videos/{id}/segments` lists it. */
export interface SkipSegment {
  id: string;
  category: string;
  start_seconds: number;
  end_seconds: number;
}

/** Closer than this to a segment's end, there's nothing left worth skipping. */
export const END_MARGIN_SECONDS = 0.5;

const CATEGORY_LABELS: Record<string, string> = {
  sponsor: "sponsor",
  selfpromo: "self-promotion",
  interaction: "subscribe reminder",
  intro: "intro",
  outro: "outro",
  preview: "preview",
  hook: "hook",
  music_offtopic: "non-music section",
  filler: "filler",
};

/** What a SponsorBlock category is, in a few words ("self-promotion"). */
export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category.replaceAll("_", " ");
}

/** The segment `time` falls in (not in its last moment), if any. */
export function segmentAt<S extends SkipSegment>(
  segments: readonly S[],
  time: number,
): S | undefined {
  return segments.find(
    (s) => s.start_seconds <= time && time < s.end_seconds - END_MARGIN_SECONDS,
  );
}

export interface SponsorSkip {
  /** Go back to the start of a skipped segment and play it. */
  undo: (segment: SkipSegment) => void;
  /** Stop skipping (on unmount). */
  stop: () => void;
}

/**
 * Skip `segments` while `media` plays, calling `onSkip` after each skip.
 */
export function attachSponsorSkip(
  media: MediaLike,
  segments: readonly SkipSegment[],
  onSkip: (segment: SkipSegment) => void,
): SponsorSkip {
  // Segments not to skip (again): skipped once, or chosen by seeking into them.
  const done = new Set<string>();
  // Our own seeks (skips and undos) vs. the viewer's.
  let ownSeek = false;
  let viewerSeeking = false;

  const seek = (time: number) => {
    ownSeek = true;
    media.currentTime = time;
  };

  const onTimeUpdate = () => {
    if (ownSeek || viewerSeeking) return;
    const segment = segmentAt(segments, media.currentTime);
    if (!segment || done.has(segment.id)) return;
    done.add(segment.id);
    onSkip(segment);
    seek(segment.end_seconds);
  };
  const onSeeking = () => {
    if (!ownSeek) viewerSeeking = true;
  };
  const onSeeked = () => {
    if (ownSeek) {
      ownSeek = false;
      onTimeUpdate(); // a segment may start right where the last one ended
      return;
    }
    viewerSeeking = false;
    const chosen = segmentAt(segments, media.currentTime);
    if (chosen) done.add(chosen.id);
  };

  media.addEventListener("timeupdate", onTimeUpdate);
  media.addEventListener("seeking", onSeeking);
  media.addEventListener("seeked", onSeeked);

  return {
    undo: (segment) => {
      done.add(segment.id);
      seek(segment.start_seconds);
    },
    stop: () => {
      media.removeEventListener("timeupdate", onTimeUpdate);
      media.removeEventListener("seeking", onSeeking);
      media.removeEventListener("seeked", onSeeked);
    },
  };
}
