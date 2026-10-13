import { useState, type RefObject } from "react";

import { formatDuration } from "#/lib/format";

/**
 * Under the player when it picks up where I left off: says where, and offers
 * to start from the beginning instead.
 */
export function ResumeNotice({
  startAt,
  videoRef,
}: {
  startAt: number | null | undefined;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const [dismissed, setDismissed] = useState(false);
  if (startAt == null || dismissed) return null;

  const restart = () => {
    const video = videoRef.current;
    if (video) video.currentTime = 0;
    setDismissed(true);
  };

  return (
    <p className="text-sm text-gray-600">
      Resuming at{" "}
      <span className="tabular-nums">{formatDuration(startAt)}</span>.{" "}
      <button type="button" className="underline" onClick={restart}>
        Start from the beginning
      </button>
    </p>
  );
}
