import { useEffect, useId, useRef, useState } from "react";

import { ScoreScale } from "#/components/ScoreScale";
import { Button } from "#/components/ui/button";

interface RatingPickerProps {
  title: string;
  /** The video's current score, lit at the start; null lights none. */
  current: number | null;
  /** Save a score. Rejecting shows an error and keeps the picker open. */
  onRate: (score: number) => Promise<void>;
  /** Close the picker: after rating (`rated`) or without rating (skip). */
  onClose: (rated: boolean) => void;
  /** Label of the button that closes without rating, e.g. "Skip". */
  skipLabel?: string;
  /** Move focus to the scale when the picker appears (for prompts). */
  autoFocus?: boolean;
}

/**
 * A 1 to 10 rating prompt: picking a face saves it and closes the prompt.
 * Picking the face already lit keeps that rating and closes too.
 */
export function RatingPicker({
  title,
  current,
  onRate,
  onClose,
  skipLabel = "Skip",
  autoFocus = false,
}: RatingPickerProps) {
  const titleId = useId();
  const scale = useRef<HTMLButtonElement>(null);
  const [picked, setPicked] = useState(current);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!autoFocus) return;
    // Wait a frame so the prompt is laid out before it takes focus.
    const frame = requestAnimationFrame(() => scale.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [autoFocus]);

  const pick = async (score: number) => {
    if (saving) return;
    setPicked(score);
    setError(null);
    if (score === current) {
      onClose(true);
      return;
    }
    setSaving(true);
    try {
      await onRate(score);
    } catch {
      setError("Couldn't save the rating. Try again.");
      setPicked(current);
      setSaving(false);
      return;
    }
    setSaving(false);
    onClose(true);
  };

  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col items-center gap-2"
    >
      <h3 id={titleId} className="text-lg font-semibold">
        {title}
      </h3>
      <ScoreScale
        value={picked}
        onPick={(score) => void pick(score)}
        label={title}
        disabled={saving}
        buttonRef={scale}
        className="w-full max-w-xl"
      />
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="lg"
          className="px-4"
          disabled={saving}
          onClick={() => onClose(false)}
        >
          {skipLabel}
        </Button>
      </div>
      <p aria-live="polite" className="text-sm text-destructive">
        {error}
      </p>
    </section>
  );
}
