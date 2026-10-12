/**
 * The tier-list scale (PLAN.md section 3) as the rating prompt sees it: a tier
 * (one tap) and an optional modifier (a second tap). Grades are the strings the
 * API stores, e.g. "B" or "A+".
 */

/** Best first, as the prompt lists them. */
export const TIERS = ["S", "A", "B", "C", "D", "F"] as const;
/** Best first; no modifier ("") is the plain tier, between "+" and "-". */
export const MODIFIERS = ["++", "+", "-", "--"] as const;

export type Tier = (typeof TIERS)[number];
export type Modifier = (typeof MODIFIERS)[number] | "";
export type Grade = `${Tier}${Modifier}`;

export function composeGrade(tier: Tier, modifier: Modifier = ""): Grade {
  return `${tier}${modifier}`;
}

/** A grade's tier and modifier, or null if `value` isn't one of the 30 grades. */
export function splitGrade(
  value: string,
): { tier: Tier; modifier: Modifier } | null {
  const tier = TIERS.find((t) => t === value[0]);
  if (!tier) return null;
  const rest = value.slice(1);
  if (rest === "") return { tier, modifier: "" };
  const modifier = MODIFIERS.find((m) => m === rest);
  return modifier ? { tier, modifier } : null;
}

export function isGrade(value: unknown): value is Grade {
  return typeof value === "string" && splitGrade(value) !== null;
}
