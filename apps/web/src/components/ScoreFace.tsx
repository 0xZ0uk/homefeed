import type { CSSProperties, ReactNode } from "react";

import { cn } from "#/lib/utils";

interface ScoreFaceProps {
  /** A whole score, 1 to 10. */
  score: number;
  /**
   * Draw the face on a disc in the score's colour (`--rating-N`), its features
   * a darker shade of it. Otherwise only the features, in `currentColor`.
   */
  filled?: boolean;
  /** A hover tooltip, e.g. the score's word. */
  title?: string;
  className?: string;
}

/**
 * The face for a score, from a wail (1) through a flat "meh" (5) to a grin
 * (10). Hidden from screen readers: callers name the score in text.
 */
export function ScoreFace({
  score,
  filled = false,
  title,
  className,
}: ScoreFaceProps) {
  const style = filled
    ? ({
        "--face": `var(--rating-${score})`,
        color: "color-mix(in oklch, var(--face) 35%, black)",
      } as CSSProperties)
    : undefined;
  return (
    <svg
      viewBox="0 0 40 40"
      aria-hidden="true"
      focusable="false"
      className={cn("shrink-0", className)}
      style={style}
    >
      {title && <title>{title}</title>}
      {filled && <circle cx="20" cy="20" r="20" fill="var(--face)" />}
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {FEATURES[score - 1]}
      </g>
    </svg>
  );
}

const DOT_EYES = (
  <>
    <circle cx="14" cy="17" r="2.3" fill="currentColor" stroke="none" />
    <circle cx="26" cy="17" r="2.3" fill="currentColor" stroke="none" />
  </>
);

// Closed, smiling eyes: ^ ^
const HAPPY_EYES = <path d="M11.5 18.5q2.5-4 5 0M23.5 18.5q2.5-4 5 0" />;

/**
 * A mouth from (20 - width, y) to (20 + width, y), bent by `curve`: up at the
 * corners (a smile) when positive, down (a frown) when negative.
 */
function mouth(curve: number, width = 6) {
  const y = 27 - curve * 2;
  const control = 27 + curve * 8;
  return <path d={`M${20 - width} ${y}Q20 ${control} ${20 + width} ${y}`} />;
}

const FEATURES: readonly ReactNode[] = [
  // 1: squeezed-shut eyes and an open wail.
  <>
    <path d="M11 14l5 3-5 3M29 14l-5 3 5 3" />
    <path d="M13.5 31.5a6.5 6 0 0 1 13 0z" fill="currentColor" />
  </>,
  // 2: worried brows and a deep frown.
  <>
    <path d="M10.5 13.5l5.5-2.5M29.5 13.5l-5.5-2.5" />
    {DOT_EYES}
    {mouth(-0.85, 7)}
  </>,
  // 3: a frown.
  <>
    {DOT_EYES}
    {mouth(-0.6)}
  </>,
  // 4: a slight frown.
  <>
    {DOT_EYES}
    {mouth(-0.3, 5.5)}
  </>,
  // 5: a flat mouth.
  <>
    {DOT_EYES}
    <path d="M15 27.5h10" />
  </>,
  // 6: a slight smile.
  <>
    {DOT_EYES}
    {mouth(0.3, 5.5)}
  </>,
  // 7: a smile.
  <>
    {DOT_EYES}
    {mouth(0.6)}
  </>,
  // 8: a wide smile.
  <>
    {DOT_EYES}
    {mouth(0.85, 7.5)}
  </>,
  // 9: smiling eyes and an open smile.
  <>
    {HAPPY_EYES}
    <path d="M14 25h12a6 6 0 0 1-12 0z" fill="currentColor" />
  </>,
  // 10: smiling eyes and a wide open grin.
  <>
    {HAPPY_EYES}
    <path d="M12 24h16a8 8 0 0 1-16 0z" fill="currentColor" />
  </>,
];
