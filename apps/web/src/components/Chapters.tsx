import { useEffect, useState } from "react";

import { usePlayerMedia } from "#/components/PlayerMedia";
import { chapterIndexAt, type Chapter } from "#/lib/chapters";
import { formatDuration } from "#/lib/format";

/**
 * The video's chapters; picking one seeks the player there (without starting
 * playback). The chapter playing now is marked.
 */
export function Chapters({ chapters }: { chapters: readonly Chapter[] }) {
  const media = usePlayerMedia();
  const [current, setCurrent] = useState(-1);

  useEffect(() => {
    if (!media) return;
    const update = () =>
      setCurrent(chapterIndexAt(chapters, media.currentTime));
    media.addEventListener("timeupdate", update);
    media.addEventListener("seeked", update);
    media.addEventListener("loadedmetadata", update);
    return () => {
      media.removeEventListener("timeupdate", update);
      media.removeEventListener("seeked", update);
      media.removeEventListener("loadedmetadata", update);
    };
  }, [media, chapters]);

  if (chapters.length === 0) return null;

  return (
    <section aria-labelledby="chapters-heading" className="flex flex-col gap-2">
      <h2 id="chapters-heading" className="px-1 text-base font-bold">
        Chapters
      </h2>
      <ol className="flex flex-col">
        {chapters.map((chapter, index) => (
          <li key={`${chapter.start_seconds}-${index}`}>
            <button
              type="button"
              disabled={!media}
              aria-current={index === current ? "true" : undefined}
              onClick={() => {
                if (media) media.currentTime = chapter.start_seconds;
              }}
              className="flex w-full gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-secondary disabled:cursor-not-allowed aria-[current=true]:bg-secondary aria-[current=true]:font-semibold"
            >
              <span className="w-16 shrink-0 tabular-nums text-muted-foreground">
                {formatDuration(chapter.start_seconds)}
              </span>
              <span>{chapter.title || `Chapter ${index + 1}`}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
