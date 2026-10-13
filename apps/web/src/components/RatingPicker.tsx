import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { ScoreSlider } from "#/components/ScoreSlider";
import { Button } from "#/components/ui/button";
import { formatScore } from "#/lib/scores";

interface RatingPickerProps {
  title: string;
  /** The video's current score, where the slider starts. */
  current: number | null;
  /** Save a score. Rejecting shows an error and keeps the picker open. */
  onRate: (score: number) => Promise<void>;
  /** Close the picker: after rating (`rated`) or without rating (skip). */
  onClose: (rated: boolean) => void;
  /** Label of the button that closes without rating, e.g. "Skip". */
  skipLabel?: string;
  /** Label of the button that saves and closes, given the formatted score. */
  submitLabel?: (score: string) => string;
  /** Move focus to the slider when the picker appears (for prompts). */
  autoFocus?: boolean;
  /** An extra way out that neither rates nor skips, e.g. "Keep watching". */
  cancel?: { label: string; onCancel: () => void };
}

/** Where the slider starts for an unrated video: the middle of the scale. */
const UNRATED_START = 5.5;

/**
 * A 1 to 10 rating: pick the score on the slider, then save it, which closes
 * the picker. Nothing is saved until then.
 */
export function RatingPicker({
  title,
  current,
  onRate,
  onClose,
  skipLabel = "Skip",
  submitLabel = (score) => `Save ${score}`,
  autoFocus = false,
  cancel,
}: RatingPickerProps) {
  const titleId = useId();
  const slider = useRef<HTMLInputElement>(null);
  const [score, setScore] = useState(current ?? UNRATED_START);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!autoFocus) return;
    // The thumb stays hidden until the slider has measured where it goes, and
    // a hidden input can't take focus, so wait a frame.
    const frame = requestAnimationFrame(() => slider.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [autoFocus]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onRate(score);
    } catch {
      setError("Couldn't save the rating. Try again.");
      setSaving(false);
      return;
    }
    setSaving(false);
    onClose(true);
  };

  return (
    <form
      aria-labelledby={titleId}
      onSubmit={(event) => void submit(event)}
      className="flex flex-col gap-3 rounded-xl bg-secondary/60 p-4"
    >
      <h3 id={titleId} className="font-semibold">
        {title}
      </h3>
      <ScoreSlider
        value={score}
        onValueChange={setScore}
        label="Score"
        disabled={saving}
        inputRef={slider}
        className="max-w-xl pt-6"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="submit"
          size="lg"
          className="px-4 tabular-nums"
          disabled={saving}
        >
          {submitLabel(formatScore(score))}
        </Button>
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
        {cancel && (
          <Button
            type="button"
            variant="ghost"
            size="lg"
            className="px-4"
            disabled={saving}
            onClick={cancel.onCancel}
          >
            {cancel.label}
          </Button>
        )}
        <p aria-live="polite" className="text-sm text-destructive">
          {error}
        </p>
      </div>
    </form>
  );
}
