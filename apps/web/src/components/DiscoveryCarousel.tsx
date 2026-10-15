import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  useSyncExternalStore,
  type FocusEvent,
} from "react";

import { VideoCard } from "#/components/VideoCard";
import { WhyThisPopover } from "#/components/WhyThisPopover";
import { Button } from "#/components/ui/button";
import {
  AUTO_ADVANCE_MS,
  clampPage,
  nextPage,
  pageCount,
  sourceLabel,
} from "#/lib/carousel";
import { cn } from "#/lib/utils";
import { discoveryVideosQuery, type DiscoveryVideo } from "#/server/discover";

/**
 * The top of the home page: ten videos from outside the subscriptions, two at
 * a time (one on narrow screens), in a row that scrolls sideways a page at a
 * time. It moves on by itself every few seconds, wrapping back to the start,
 * but holds still while a video is hovered or focused, when paused with its
 * button, and for people who prefer reduced motion (they can still start it).
 * It's left out while the videos load, when there are none, and if they fail:
 * the feed below matters more.
 */
export function DiscoveryCarousel() {
  const { data: videos } = useQuery(discoveryVideosQuery);
  // One "now" per render pass keeps every item's age consistent.
  const [now] = useState(() => new Date());
  if (!videos || videos.length === 0) return null;
  return <Carousel videos={videos} now={now} />;
}

function Carousel({ videos, now }: { videos: DiscoveryVideo[]; now: Date }) {
  const headingId = useId();
  const { scroller, page, pages, goTo } = usePages(videos.length);
  const reducedMotion = usePrefersReducedMotion();
  const [paused, setPaused] = useState<boolean | null>(null);
  const [held, setHeld] = useState({ hover: false, focus: false });
  // Unless paused or played by hand, reduced motion means paused.
  const stopped = paused ?? reducedMotion;
  const running = !stopped && !held.hover && !held.focus && pages > 1;

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) goTo((current) => nextPage(current, pages));
    }, AUTO_ADVANCE_MS);
    return () => window.clearInterval(timer);
  }, [running, pages, goTo]);

  const onBlur = (event: FocusEvent<HTMLOListElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget)) {
      setHeld((h) => ({ ...h, focus: false }));
    }
  };

  return (
    <section
      aria-roledescription="carousel"
      aria-labelledby={headingId}
      className="flex flex-col gap-3 pt-3"
    >
      <div className="flex items-center gap-2">
        <h2 id={headingId} className="mr-auto text-xl font-bold">
          Discovery
        </h2>
        <Button
          variant="ghost"
          size="icon-lg"
          onClick={() => setPaused(!stopped)}
          aria-label={
            stopped ? "Play Discovery slideshow" : "Pause Discovery slideshow"
          }
        >
          {stopped ? <Play /> : <Pause />}
        </Button>
        <Button
          variant="secondary"
          size="icon-lg"
          onClick={() => goTo((current) => current - 1)}
          disabled={page === 0}
          aria-label="Previous videos"
        >
          <ChevronLeft className="size-5" />
        </Button>
        <Button
          variant="secondary"
          size="icon-lg"
          onClick={() => goTo((current) => current + 1)}
          disabled={page >= pages - 1}
          aria-label="Next videos"
        >
          <ChevronRight className="size-5" />
        </Button>
      </div>
      <ol
        ref={scroller}
        // Only the videos hold it still, so its own buttons can start it.
        onPointerEnter={(e) =>
          e.pointerType === "mouse" && setHeld((h) => ({ ...h, hover: true }))
        }
        onPointerLeave={() => setHeld((h) => ({ ...h, hover: false }))}
        onFocus={() => setHeld((h) => ({ ...h, focus: true }))}
        onBlur={onBlur}
        aria-label="Discovery videos"
        className="-m-2 grid snap-x snap-mandatory scroll-px-2 auto-cols-[100%] grid-flow-col gap-4 overflow-x-auto overscroll-x-contain p-2 [scrollbar-width:none] sm:auto-cols-[calc((100%-1rem)/2)] [&::-webkit-scrollbar]:hidden"
      >
        {videos.map((video) => (
          <Slide key={video.video_id} video={video} now={now} />
        ))}
      </ol>
      {pages > 1 && (
        <div className="flex justify-center gap-1">
          {Array.from({ length: pages }, (_, index) => (
            <button
              key={index}
              type="button"
              onClick={() => goTo(index)}
              aria-label={`Page ${index + 1} of ${pages}`}
              aria-current={index === page ? "true" : undefined}
              className="group flex size-6 items-center justify-center rounded-full outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-1.5 rounded-full bg-muted-foreground/40 transition-[width,background-color] group-hover:bg-muted-foreground/70 motion-reduce:transition-none",
                  index === page ? "w-4 bg-foreground" : "w-1.5",
                )}
              />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** A video in the carousel: a card with where it was found and why it's here. */
function Slide({ video, now }: { video: DiscoveryVideo; now: Date }) {
  const source = sourceLabel(video.source, video.source_detail);
  return (
    <VideoCard
      video={{ ...video, watched: false }}
      now={now}
      className="snap-start"
      overlay={
        <>
          {source && (
            <span className="absolute bottom-1.5 left-1.5 max-w-[calc(100%-5rem)] truncate rounded bg-black/80 px-1.5 py-px text-xs font-medium text-white">
              {source}
            </span>
          )}
          <WhyThisPopover
            explanation={video.explanation}
            breakdown={video.breakdown}
          />
        </>
      }
    />
  );
}

/**
 * Which page of the `scroller` is in view and how many there are, measured
 * from the slides themselves (so the breakpoints stay in CSS), and moving to a
 * page. `goTo` takes a page or a function of the current one, kept in range.
 */
function usePages(count: number) {
  const scroller = useRef<HTMLOListElement>(null);
  const [page, setPage] = useState(0);
  const [perPage, setPerPage] = useState(2);
  const pageRef = useRef(0);
  const pages = pageCount(count, perPage);

  /** The distance between pages, and how many slides each shows. */
  const measure = useCallback(() => {
    const element = scroller.current;
    const [first, second] = element?.children ?? [];
    if (!element || !(first instanceof HTMLElement)) return null;
    const pitch =
      second instanceof HTMLElement
        ? second.offsetLeft - first.offsetLeft
        : element.clientWidth;
    const fits = Math.max(1, Math.round(element.clientWidth / pitch));
    return { step: pitch * fits, fits };
  }, []);

  useEffect(() => {
    const element = scroller.current;
    if (!element) return;
    const sync = () => {
      const size = measure();
      if (!size) return;
      setPerPage(size.fits);
      const atEnd =
        element.scrollLeft + element.clientWidth >= element.scrollWidth - 1;
      const current = atEnd
        ? pageCount(count, size.fits) - 1
        : Math.round(element.scrollLeft / size.step);
      pageRef.current = current;
      setPage(current);
    };
    sync();
    element.addEventListener("scroll", sync, { passive: true });
    const observer = new ResizeObserver(sync);
    observer.observe(element);
    return () => {
      element.removeEventListener("scroll", sync);
      observer.disconnect();
    };
  }, [measure, count]);

  const goTo = useCallback(
    (target: number | ((current: number) => number)) => {
      const element = scroller.current;
      const size = measure();
      if (!element || !size) return;
      const total = pageCount(count, size.fits);
      const next = clampPage(
        typeof target === "function" ? target(pageRef.current) : target,
        total,
      );
      const reduce = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      element.scrollTo({
        left: next * size.step,
        behavior: reduce ? "instant" : "smooth",
      });
    },
    [measure, count],
  );

  return { scroller, page, pages, goTo };
}

function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia("(prefers-reduced-motion: reduce)");
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}
