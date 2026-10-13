import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
  type RefObject,
} from "react";

/**
 * Shares the watch page's `<video>` element with what sits around the player
 * (chapters, SponsorBlock skipping), so they can follow and seek playback.
 */

interface PlayerMediaValue {
  media: HTMLVideoElement | null;
  setMedia: (media: HTMLVideoElement | null) => void;
}

const PlayerMediaContext = createContext<PlayerMediaValue | null>(null);

export function PlayerMediaProvider({ children }: { children: ReactNode }) {
  const [media, setMedia] = useState<HTMLVideoElement | null>(null);
  const value = useMemo(() => ({ media, setMedia }), [media]);
  return (
    <PlayerMediaContext.Provider value={value}>
      {children}
    </PlayerMediaContext.Provider>
  );
}

/** The player's `<video>` element, or null before it mounts (or outside a provider). */
export function usePlayerMedia(): HTMLVideoElement | null {
  return useContext(PlayerMediaContext)?.media ?? null;
}

/** Make `ref`'s element the page's player (called by `VideoPlayer`). */
export function useRegisterPlayerMedia(
  ref: RefObject<HTMLVideoElement | null>,
): void {
  const setMedia = useContext(PlayerMediaContext)?.setMedia;
  useEffect(() => {
    if (!setMedia) return;
    setMedia(ref.current);
    return () => setMedia(null);
  }, [ref, setMedia]);
}
