import { Menu } from "@base-ui/react/menu";
import { Slider } from "@base-ui/react/slider";
import {
  CheckIcon,
  ChevronRightIcon,
  ListMinusIcon,
  ListPlusIcon,
  LoaderCircleIcon,
  MaximizeIcon,
  MinimizeIcon,
  PauseIcon,
  PictureInPicture2Icon,
  PlayIcon,
  RotateCcwIcon,
  SettingsIcon,
  Volume1Icon,
  Volume2Icon,
  VolumeXIcon,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useSyncExternalStore,
  type FocusEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { QueueStatus, useQueueToggle } from "#/components/QueueButton";
import { Scrubber } from "#/components/player/Scrubber";
import {
  useMediaState,
  type ShakaPlayer,
} from "#/components/player/media-state";
import { useFullscreen } from "#/components/player/use-fullscreen";
import {
  PLAYBACK_SPEEDS,
  setPlaybackRate,
  setVolume,
  toggleMute,
  togglePictureInPicture,
  togglePlayback,
  usePlayerShortcuts,
  type PlayerAction,
} from "#/components/player/use-player-shortcuts";
import { chapterIndexAt, type Chapter } from "#/lib/chapters";
import { formatDuration } from "#/lib/format";
import type { SkipSegment } from "#/lib/sponsor-skip";
import { cn } from "#/lib/utils";

/** How long the controls stay up after the pointer last moved while playing. */
const IDLE_MS = 3000;
const VOLUME_KEY = "player-volume";

export interface PlayerControlsProps {
  videoId: string;
  media: HTMLVideoElement | null;
  player: ShakaPlayer | null;
  /** The element that goes fullscreen (wraps the video and the controls). */
  containerRef: RefObject<HTMLElement | null>;
  chapters: readonly Chapter[];
  segments: readonly SkipSegment[];
  /** Overlay content that rides above the control bar, e.g. the "Skipped sponsor" toast. */
  children?: ReactNode;
}

const BUTTON =
  "inline-flex size-10 shrink-0 items-center justify-center rounded-full text-white outline-none transition-colors hover:bg-white/15 focus-visible:ring-2 focus-visible:ring-white/80 motion-reduce:transition-none [&_svg]:pointer-events-none [&_svg]:size-6";

interface StoredVolume {
  volume: number;
  muted: boolean;
}

function readStoredVolume(): StoredVolume | null {
  try {
    const raw = window.localStorage.getItem(VOLUME_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return null;
    const { volume, muted } = parsed as Partial<StoredVolume>;
    if (typeof volume !== "number" || !(volume >= 0 && volume <= 1)) {
      return null;
    }
    return { volume, muted: muted === true };
  } catch {
    return null;
  }
}

function writeStoredVolume(value: StoredVolume) {
  try {
    window.localStorage.setItem(VOLUME_KEY, JSON.stringify(value));
  } catch {
    // Storage may be full or blocked; the volume just won't carry over.
  }
}

function restoreVolume(media: HTMLMediaElement, stored: StoredVolume) {
  media.volume = stored.volume;
  media.muted = stored.muted;
}

/** Restores the saved volume and mute onto `media`, then keeps them saved. */
function usePersistedVolume(media: HTMLMediaElement | null) {
  useEffect(() => {
    if (!media) return;
    const stored = readStoredVolume();
    if (stored) restoreVolume(media, stored);
    const save = () =>
      writeStoredVolume({ volume: media.volume, muted: media.muted });
    media.addEventListener("volumechange", save);
    return () => media.removeEventListener("volumechange", save);
  }, [media]);
}

const noopSubscribe = () => () => {};

/** Whether the browser can put a video in picture-in-picture. */
function usePictureInPictureAvailable(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => typeof document !== "undefined" && document.pictureInPictureEnabled,
    () => false,
  );
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function clock(seconds: number): string {
  return formatDuration(Math.floor(seconds)) ?? "0:00";
}

/**
 * The player's controls over the video: click to play and pause, a bottom bar
 * with the scrubber, volume, time, settings and fullscreen, and keyboard
 * shortcuts. They fade out while a playing video sits untouched.
 */
export function PlayerControls({
  videoId,
  media,
  player,
  containerRef,
  chapters,
  segments,
  children,
}: PlayerControlsProps) {
  const state = useMediaState(media);
  const queue = useQueueToggle(videoId);
  const queueLabel = queue.queued ? "Remove from queue" : "Add to queue";
  const { isFullscreen, toggle: toggleFullscreen } =
    useFullscreen(containerRef);
  const pipAvailable = usePictureInPictureAvailable();
  usePersistedVolume(media);

  const rootRef = useRef<HTMLDivElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const flashRef = useRef<HTMLDivElement>(null);
  const idleTimer = useRef<number | undefined>(undefined);
  const touchReveal = useRef(false);
  const pinnedRef = useRef(true);

  const [awake, setAwake] = useState(true);
  const [scrubbing, setScrubbing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [flash, setFlash] = useState<{ key: number; paused: boolean } | null>(
    null,
  );

  const pinned = state.paused || state.ended || scrubbing || menuOpen;
  const visible = pinned || awake;

  const countdown = useCallback(() => {
    window.clearTimeout(idleTimer.current);
    idleTimer.current = window.setTimeout(() => {
      if (!pinnedRef.current) setAwake(false);
    }, IDLE_MS);
  }, []);
  const wake = useCallback(() => {
    setAwake(true);
    countdown();
  }, [countdown]);

  // Starts the countdown when playback resumes or the last reason to stay up ends.
  useEffect(() => {
    pinnedRef.current = pinned;
    if (!pinned) countdown();
  }, [pinned, countdown]);
  useEffect(() => () => window.clearTimeout(idleTimer.current), []);

  // The toast above the bar drops by the bar's height when the bar hides.
  useEffect(() => {
    const bar = barRef.current;
    const root = rootRef.current;
    if (!bar || !root) return;
    const measure = () =>
      root.style.setProperty("--controls-h", `${bar.offsetHeight}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [media]);

  useEffect(() => {
    if (!flash) return;
    const reduced = prefersReducedMotion();
    flashRef.current?.animate(
      [
        { opacity: 0.9, transform: "scale(1)" },
        { opacity: 0, transform: reduced ? "scale(1)" : "scale(1.8)" },
      ],
      { duration: 500, easing: "ease-out", fill: "forwards" },
    );
  }, [flash]);

  const showFlash = useCallback((video: HTMLVideoElement) => {
    setFlash((previous) => ({
      key: (previous?.key ?? 0) + 1,
      paused: video.paused,
    }));
  }, []);

  const onShortcut = useCallback(
    (action: PlayerAction) => {
      wake();
      if (action.type === "toggle-play" && media) showFlash(media);
    },
    [media, showFlash, wake],
  );
  usePlayerShortcuts({
    media,
    containerRef,
    toggleFullscreen,
    onAction: onShortcut,
  });

  if (!media) return null;

  const onPointerMove = (event: PointerEvent) => {
    if (event.pointerType !== "touch") wake();
  };
  const onPointerLeave = (event: PointerEvent) => {
    if (event.pointerType === "touch" || pinned) return;
    window.clearTimeout(idleTimer.current);
    setAwake(false);
  };
  // Tabbing through or using the controls brings them back, like the pointer.
  const onFocus = (event: FocusEvent) => {
    if (event.target.matches(":focus-visible")) wake();
  };

  const onLayerPointerDown = (event: PointerEvent) => {
    // On touch, the first tap on hidden controls only brings them back.
    touchReveal.current = event.pointerType === "touch" && !visible;
    if (event.pointerType === "touch") wake();
  };
  const onLayerClick = () => {
    if (touchReveal.current) {
      touchReveal.current = false;
      return;
    }
    togglePlayback(media);
    showFlash(media);
  };

  const { currentTime, duration } = state;
  const chapter = chapters[chapterIndexAt(chapters, currentTime)];
  const playLabel = state.ended
    ? "Replay (k)"
    : state.paused
      ? "Play (k)"
      : "Pause (k)";
  const muteLabel =
    state.muted || state.volume === 0 ? "Unmute (m)" : "Mute (m)";
  const fullscreenLabel = isFullscreen
    ? "Exit full screen (f)"
    : "Full screen (f)";
  const firstPlay = state.paused && !state.ended && currentTime === 0;

  return (
    <div
      ref={rootRef}
      className={cn(
        "absolute inset-0 overflow-hidden text-white select-none",
        !visible && "cursor-none",
      )}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      onFocus={onFocus}
      onKeyDown={wake}
    >
      <div
        className="absolute inset-0"
        onPointerDown={onLayerPointerDown}
        onClick={onLayerClick}
        onDoubleClick={toggleFullscreen}
      />

      {firstPlay && (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-1/2 grid size-16 -translate-1/2 place-items-center rounded-full bg-black/60 sm:size-20"
        >
          <PlayIcon className="size-8 translate-x-0.5 fill-current sm:size-10" />
        </div>
      )}
      {state.waiting && (
        <div
          role="status"
          aria-label="Buffering"
          className="pointer-events-none absolute top-1/2 left-1/2 -translate-1/2"
        >
          <LoaderCircleIcon className="size-12 drop-shadow motion-safe:animate-spin" />
        </div>
      )}
      {flash && (
        <div
          key={flash.key}
          ref={flashRef}
          aria-hidden="true"
          className="pointer-events-none absolute top-1/2 left-1/2 grid size-16 -translate-1/2 place-items-center rounded-full bg-black/60 opacity-0"
        >
          {flash.paused ? (
            <PauseIcon className="size-8 fill-current" />
          ) : (
            <PlayIcon className="size-8 translate-x-0.5 fill-current" />
          )}
        </div>
      )}

      <div
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-linear-to-t from-black/70 to-transparent transition-opacity duration-200 motion-reduce:transition-none",
          !visible && "opacity-0",
        )}
      />

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col">
        {children != null && (
          <div
            className={cn(
              "px-3 pb-3 transition-transform [&>*]:pointer-events-auto duration-200 ease-out motion-reduce:transition-none",
              visible ? "translate-y-0" : "translate-y-(--controls-h)",
            )}
          >
            {children}
          </div>
        )}
        <div
          ref={barRef}
          className={cn(
            "px-3 pb-1 transition-opacity duration-200 motion-reduce:transition-none",
            visible ? "pointer-events-auto" : "opacity-0",
          )}
        >
          <Scrubber
            media={media}
            chapters={chapters}
            segments={segments}
            onScrubbingChange={setScrubbing}
          />
          <div className="flex items-center gap-1">
            <button
              type="button"
              className={BUTTON}
              aria-label={playLabel}
              title={playLabel}
              onClick={() => togglePlayback(media)}
            >
              {state.ended ? (
                <RotateCcwIcon />
              ) : state.paused ? (
                <PlayIcon className="fill-current" />
              ) : (
                <PauseIcon className="fill-current" />
              )}
            </button>

            <VolumeControl
              media={media}
              volume={state.volume}
              muted={state.muted}
              muteLabel={muteLabel}
            />

            <div className="ml-2 flex min-w-0 items-baseline gap-2 text-sm">
              <span className="shrink-0 tabular-nums">
                {clock(currentTime)} /{" "}
                {duration == null ? "-:--" : clock(duration)}
              </span>
              {chapter && (
                <span className="min-w-0 truncate text-white/80">
                  <span aria-hidden="true">• </span>
                  {chapter.title}
                </span>
              )}
            </div>

            <div className="ml-auto flex items-center gap-1">
              <SettingsMenu
                player={player}
                playbackRate={state.playbackRate}
                media={media}
                containerRef={containerRef}
                onOpenChange={setMenuOpen}
              />
              <button
                type="button"
                className={BUTTON}
                aria-label={queueLabel}
                title={queueLabel}
                disabled={!queue.ready}
                onClick={queue.toggle}
              >
                {queue.queued ? <ListMinusIcon /> : <ListPlusIcon />}
              </button>
              <QueueStatus message={queue.message} className="sr-only" />
              {pipAvailable && (
                <button
                  type="button"
                  className={BUTTON}
                  aria-label="Picture in picture (i)"
                  title="Picture in picture (i)"
                  onClick={() => togglePictureInPicture(media)}
                >
                  <PictureInPicture2Icon />
                </button>
              )}
              <button
                type="button"
                className={BUTTON}
                aria-label={fullscreenLabel}
                title={fullscreenLabel}
                onClick={toggleFullscreen}
              >
                {isFullscreen ? <MinimizeIcon /> : <MaximizeIcon />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function VolumeControl({
  media,
  volume,
  muted,
  muteLabel,
}: {
  media: HTMLVideoElement;
  volume: number;
  muted: boolean;
  muteLabel: string;
}) {
  const [dragging, setDragging] = useState(false);
  const level = muted ? 0 : volume;
  const Icon =
    level === 0 ? VolumeXIcon : level < 0.5 ? Volume1Icon : Volume2Icon;

  return (
    <div className="group/volume flex items-center">
      <button
        type="button"
        className={BUTTON}
        aria-label={muteLabel}
        title={muteLabel}
        onClick={() => toggleMute(media)}
      >
        <Icon />
      </button>
      <div
        className={cn(
          "w-0 overflow-hidden transition-[width] duration-200 ease-out group-hover/volume:w-20 group-has-focus-visible/volume:w-20 motion-reduce:transition-none",
          dragging && "w-20",
        )}
      >
        <Slider.Root
          value={Math.round(level * 100)}
          min={0}
          max={100}
          step={1}
          onValueChange={(value) => setVolume(media, value / 100)}
          onValueCommitted={() => setDragging(false)}
          className="w-20 px-2"
        >
          <Slider.Control
            className="relative flex h-10 w-full touch-none items-center"
            onPointerDown={() => setDragging(true)}
          >
            <Slider.Track className="relative h-1 w-full rounded-full bg-white/30">
              <Slider.Indicator className="rounded-full bg-white" />
              <Slider.Thumb
                getAriaLabel={() => "Volume"}
                getAriaValueText={(_, value) => `${value}%`}
                className="size-3 rounded-full bg-white outline-none has-focus-visible:ring-2 has-focus-visible:ring-white/80"
              />
            </Slider.Track>
          </Slider.Control>
        </Slider.Root>
      </div>
    </div>
  );
}

interface Qualities {
  /** Distinct heights, highest first. */
  heights: number[];
  activeHeight: number | null;
  /** Whether Shaka picks the quality itself. */
  auto: boolean;
}

function readQualities(player: ShakaPlayer | null): Qualities {
  if (!player) return { heights: [], activeHeight: null, auto: true };
  const tracks = player.getVariantTracks();
  const heights = [
    ...new Set(
      tracks.flatMap((track) => (track.height != null ? [track.height] : [])),
    ),
  ].sort((a, b) => b - a);
  return {
    heights,
    activeHeight: tracks.find((track) => track.active)?.height ?? null,
    auto: player.getConfiguration().abr.enabled,
  };
}

const QUALITY_EVENTS = [
  "adaptation",
  "variantchanged",
  "trackschanged",
  "abrstatuschanged",
] as const;

/** `player`'s quality choices, kept in step with its adaptation. */
function useQualities(player: ShakaPlayer | null) {
  const [version, refresh] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    if (!player) return;
    for (const type of QUALITY_EVENTS) player.addEventListener(type, refresh);
    return () => {
      for (const type of QUALITY_EVENTS) {
        player.removeEventListener(type, refresh);
      }
    };
  }, [player]);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `version` marks Shaka-side changes
  const qualities = useMemo(() => readQualities(player), [player, version]);

  const choose = useCallback(
    (choice: "auto" | number) => {
      if (!player) return;
      if (choice === "auto") {
        player.configure({ abr: { enabled: true } });
      } else {
        const tracks = player.getVariantTracks();
        const language = tracks.find((track) => track.active)?.language;
        const sameHeight = tracks.filter((track) => track.height === choice);
        const pool = sameHeight.filter((track) => track.language === language);
        const best = (pool.length > 0 ? pool : sameHeight).reduce<
          (typeof tracks)[number] | null
        >(
          (top, track) =>
            !top || track.bandwidth > top.bandwidth ? track : top,
          null,
        );
        if (!best) return;
        player.configure({ abr: { enabled: false } });
        player.selectVariantTrack(best, /* clearBuffer */ true);
      }
      refresh();
    },
    [player],
  );

  return { ...qualities, choose };
}

const POPUP =
  "z-50 min-w-48 origin-(--transform-origin) rounded-xl bg-black/90 p-1 text-sm text-white shadow-lg ring-1 ring-white/10 outline-none transition-[opacity,scale] duration-150 ease-out data-starting-style:opacity-0 data-ending-style:opacity-0 motion-safe:data-starting-style:scale-[0.96] motion-safe:data-ending-style:scale-[0.96]";
const ITEM =
  "flex cursor-default items-center gap-2 rounded-lg px-3 py-2 outline-none select-none data-highlighted:bg-white/15 data-popup-open:bg-white/15";

function RadioRow({
  value,
  children,
}: {
  value: string | number;
  children: ReactNode;
}) {
  return (
    <Menu.RadioItem value={value} closeOnClick className={ITEM}>
      <span className="grid size-4 place-items-center">
        <Menu.RadioItemIndicator>
          <CheckIcon className="size-4" />
        </Menu.RadioItemIndicator>
      </span>
      {children}
    </Menu.RadioItem>
  );
}

const SettingsMenu = memo(function SettingsMenu({
  media,
  player,
  playbackRate,
  containerRef,
  onOpenChange,
}: {
  media: HTMLVideoElement;
  player: ShakaPlayer | null;
  playbackRate: number;
  containerRef: RefObject<HTMLElement | null>;
  onOpenChange: (open: boolean) => void;
}) {
  const quality = useQualities(player);
  const showQuality = quality.heights.length > 1;
  const qualityValue = quality.auto ? "auto" : (quality.activeHeight ?? "auto");
  const qualityLabel = quality.auto
    ? quality.activeHeight
      ? `Auto (${quality.activeHeight}p)`
      : "Auto"
    : `${quality.activeHeight}p`;

  return (
    <Menu.Root onOpenChange={onOpenChange}>
      <Menu.Trigger
        className={cn(
          BUTTON,
          "[&_svg]:transition-transform [&_svg]:duration-200 data-popup-open:[&_svg]:rotate-45 motion-reduce:[&_svg]:transition-none",
        )}
        aria-label="Settings"
        title="Settings"
      >
        <SettingsIcon />
      </Menu.Trigger>
      <Menu.Portal container={containerRef}>
        <Menu.Positioner
          side="top"
          align="end"
          sideOffset={8}
          collisionPadding={8}
          className="z-50 outline-none"
        >
          <Menu.Popup
            className={cn(POPUP, "max-h-(--available-height) overflow-y-auto")}
          >
            <SubMenu
              label="Playback speed"
              value={playbackRate === 1 ? "Normal" : `${playbackRate}`}
              containerRef={containerRef}
            >
              <Menu.RadioGroup
                value={playbackRate}
                onValueChange={(speed) => setPlaybackRate(media, Number(speed))}
              >
                {PLAYBACK_SPEEDS.map((speed) => (
                  <RadioRow key={speed} value={speed}>
                    {speed === 1 ? "Normal" : speed}
                  </RadioRow>
                ))}
              </Menu.RadioGroup>
            </SubMenu>
            {showQuality && (
              <SubMenu
                label="Quality"
                value={qualityLabel}
                containerRef={containerRef}
              >
                <Menu.RadioGroup
                  value={qualityValue}
                  onValueChange={(choice) => quality.choose(choice)}
                >
                  <RadioRow value="auto">
                    {quality.auto && quality.activeHeight
                      ? `Auto (${quality.activeHeight}p)`
                      : "Auto"}
                  </RadioRow>
                  {quality.heights.map((height) => (
                    <RadioRow key={height} value={height}>
                      {height}p
                    </RadioRow>
                  ))}
                </Menu.RadioGroup>
              </SubMenu>
            )}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
});

function SubMenu({
  label,
  value,
  containerRef,
  children,
}: {
  label: string;
  value: string;
  containerRef: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <Menu.SubmenuRoot>
      <Menu.SubmenuTrigger className={ITEM}>
        <span>{label}</span>
        <span className="ml-auto pl-6 text-white/70 tabular-nums">{value}</span>
        <ChevronRightIcon className="size-4 text-white/70" />
      </Menu.SubmenuTrigger>
      <Menu.Portal container={containerRef}>
        <Menu.Positioner
          side="left"
          align="start"
          alignOffset={-4}
          sideOffset={4}
          collisionPadding={8}
          className="z-50 outline-none"
        >
          <Menu.Popup
            className={cn(POPUP, "max-h-(--available-height) overflow-y-auto")}
          >
            {children}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.SubmenuRoot>
  );
}
