import { useEffect, useId, useRef, useState } from "react";

import {
  MODIFIERS,
  TIERS,
  composeGrade,
  splitGrade,
  type Grade,
  type Tier,
} from "#/lib/grades";

interface RatingPickerProps {
  title: string;
  /** The video's current grade, highlighted. */
  current: Grade | null;
  /** Save a grade. Rejecting shows an error and keeps the picker open. */
  onRate: (grade: Grade) => Promise<void>;
  /** Close the picker: after rating (`rated`) or without rating (skip). */
  onClose: (rated: boolean) => void;
  /** Label of the button that closes without rating, e.g. "Skip". */
  skipLabel?: string;
  /** Label of the button that closes after picking a tier, e.g. "Done". */
  doneLabel?: string;
  /** Move focus into the picker when it appears (for prompts). */
  autoFocus?: boolean;
  /** An extra way out that neither rates nor skips, e.g. "Keep watching". */
  cancel?: { label: string; onCancel: () => void };
}

const BUTTON =
  "min-w-12 rounded border border-gray-400 px-3 py-2 font-semibold aria-pressed:border-gray-900 aria-pressed:bg-gray-900 aria-pressed:text-white disabled:opacity-60";

/**
 * Tier-list rating in one tap: S/A/B/C/D/F saves the plain tier right away.
 * A second, optional tap refines it with ++/+/-/-- and closes the picker.
 */
export function RatingPicker({
  title,
  current,
  onRate,
  onClose,
  skipLabel = "Skip",
  doneLabel = "Done",
  autoFocus = false,
  cancel,
}: RatingPickerProps) {
  const titleId = useId();
  const firstButton = useRef<HTMLButtonElement>(null);
  const [tier, setTier] = useState<Tier | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentParts = current ? splitGrade(current) : null;

  useEffect(() => {
    if (autoFocus) firstButton.current?.focus();
  }, [autoFocus]);

  const save = async (grade: Grade): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      await onRate(grade);
      return true;
    } catch {
      setError("Couldn't save the rating. Try again.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const pickTier = async (picked: Tier) => {
    if (await save(composeGrade(picked))) setTier(picked);
  };

  const pickModifier = async (grade: Grade) => {
    if (await save(grade)) onClose(true);
  };

  return (
    <section
      aria-labelledby={titleId}
      className="flex flex-col gap-3 rounded border border-gray-300 p-4"
    >
      <h3 id={titleId} className="font-semibold">
        {title}
      </h3>
      <div role="group" aria-label="Tier" className="flex flex-wrap gap-2">
        {TIERS.map((t, index) => (
          <button
            key={t}
            ref={index === 0 ? firstButton : undefined}
            type="button"
            className={BUTTON}
            disabled={saving}
            aria-pressed={(tier ?? currentParts?.tier) === t}
            onClick={() => void pickTier(t)}
          >
            {t}
          </button>
        ))}
      </div>
      {tier && (
        <div
          role="group"
          aria-label={`Refine ${tier} (optional)`}
          className="flex flex-wrap items-center gap-2"
        >
          {MODIFIERS.map((modifier) => {
            const grade = composeGrade(tier, modifier);
            return (
              <button
                key={modifier}
                type="button"
                className={BUTTON}
                disabled={saving}
                aria-pressed={current === grade}
                onClick={() => void pickModifier(grade)}
              >
                {grade}
              </button>
            );
          })}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-4">
        {tier ? (
          <button
            type="button"
            className="underline"
            disabled={saving}
            onClick={() => onClose(true)}
          >
            {doneLabel}
          </button>
        ) : (
          <button
            type="button"
            className="underline"
            disabled={saving}
            onClick={() => onClose(false)}
          >
            {skipLabel}
          </button>
        )}
        {cancel && (
          <button
            type="button"
            className="underline"
            disabled={saving}
            onClick={cancel.onCancel}
          >
            {cancel.label}
          </button>
        )}
        <p aria-live="polite" className="text-sm text-gray-600">
          {error ??
            (tier ? `Saved ${current ?? tier}. Add a + or - if you like.` : "")}
        </p>
      </div>
    </section>
  );
}
