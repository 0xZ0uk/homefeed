import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { usePlayerMedia } from "#/components/PlayerMedia";
import { formatDuration } from "#/lib/format";
import {
  attachSponsorSkip,
  categoryLabel,
  type SkipSegment,
  type SponsorSkip as Skipper,
} from "#/lib/sponsor-skip";
import { sponsorSegmentsQuery } from "#/server/video-extras";

/** How long the "Skipped ..." notice stays up. */
const NOTICE_MS = 8000;

/**
 * Skips the video's SponsorBlock segments as playback reaches them, with a
 * short notice and a way to watch the skipped part. Shows nothing when the
 * video has no segments or SponsorBlock can't be reached.
 */
export function SponsorSkip({ videoId }: { videoId: string }) {
  const media = usePlayerMedia();
  const { data: segments } = useQuery(sponsorSegmentsQuery(videoId));
  const [skipped, setSkipped] = useState<SkipSegment | null>(null);
  const skipper = useRef<Skipper | null>(null);

  useEffect(() => {
    if (!media || !segments?.length) return;
    const skip = attachSponsorSkip(media, segments, setSkipped);
    skipper.current = skip;
    return () => {
      skip.stop();
      skipper.current = null;
    };
  }, [media, segments]);

  useEffect(() => {
    if (!skipped) return;
    const timer = setTimeout(() => setSkipped(null), NOTICE_MS);
    return () => clearTimeout(timer);
  }, [skipped]);

  if (!segments?.length) return null;

  const watchSkipped = () => {
    if (skipped) skipper.current?.undo(skipped);
    setSkipped(null);
  };

  const categories = [
    ...new Set(segments.map((s) => categoryLabel(s.category))),
  ];
  return (
    <p role="status" className="text-sm text-muted-foreground">
      {skipped ? (
        <>
          Skipped {categoryLabel(skipped.category)} (
          {formatDuration(skipped.start_seconds)}–
          {formatDuration(skipped.end_seconds)}).{" "}
          <button type="button" className="underline" onClick={watchSkipped}>
            Watch it
          </button>
        </>
      ) : (
        <>
          SponsorBlock: skipping {segments.length}{" "}
          {segments.length === 1 ? "segment" : "segments"} (
          {categories.join(", ")}).
        </>
      )}
    </p>
  );
}
