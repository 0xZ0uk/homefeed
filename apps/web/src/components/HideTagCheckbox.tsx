import { HIDE_WEIGHT } from "#/lib/topics";

/**
 * Hides a muted tag's videos from the feed instead of only ranking them down.
 * Only available at the strongest weight (-1); moving the weight away from it
 * turns the option off again.
 */
export function HideTagCheckbox({
  id,
  weight,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  /** The topic's stored weight. */
  weight: number;
  checked: boolean;
  disabled?: boolean;
  onChange: (hide: boolean) => void;
}) {
  const available = weight === HIDE_WEIGHT;
  return (
    <div className="flex flex-col gap-0.5">
      <label className="flex items-center gap-2 text-sm">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          disabled={disabled || !available}
          aria-describedby={`${id}-hint`}
          onChange={(event) => onChange(event.target.checked)}
        />
        Hide these videos from my feed
      </label>
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {available
          ? "Videos with this tag won't appear in your feed at all."
          : "Available when the weight is set to Suppress −1.00."}
      </p>
    </div>
  );
}
