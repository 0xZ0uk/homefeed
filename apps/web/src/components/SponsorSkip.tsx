import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { usePlayerMedia } from "#/components/PlayerMedia";
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
 * short notice over the player and a way to watch the skipped part. Shows
 * nothing when the video has no segments or SponsorBlock can't be reached
 * (the segments are marked on the progress bar).
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

  const watchSkipped = () => {
    if (skipped) skipper.current?.undo(skipped);
    setSkipped(null);
  };

  return (
    <div role="status" className="flex justify-end">
      {skipped && (
        <p className="pointer-events-auto flex items-center gap-3 rounded-md bg-black/80 py-1.5 ps-3 pe-1.5 text-sm text-white shadow-lg animate-in fade-in slide-in-from-right-2 motion-reduce:animate-none">
          <span>Skipped {categoryLabel(skipped.category)}</span>
          <button
            type="button"
            className="rounded px-2 py-1 font-medium hover:bg-white/15 focus-visible:ring-2 focus-visible:ring-white/70 focus-visible:outline-none"
            onClick={watchSkipped}
          >
            Undo
          </button>
        </p>
      )}
    </div>
  );
}
