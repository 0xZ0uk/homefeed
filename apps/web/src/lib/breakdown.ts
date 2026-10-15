import type { ScoreBreakdownOut } from "@homefeed/api-client";

/**
 * A feed item's score breakdown as rows for display. The terms sum to the
 * score: `alpha * model + channel + similarity + sum(tags) = final`.
 */
export interface BreakdownTerm {
  key: string;
  label: string;
  value: number;
  /** What the term was computed from, when there's more to say. */
  detail?: string;
}

/** Every term, in a fixed order: channel, similarity, tags, model. */
export function breakdownTerms(breakdown: ScoreBreakdownOut): BreakdownTerm[] {
  const tags = Object.entries(breakdown.tags)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({
      key: `tag:${label}`,
      label: `Tag “${label}”`,
      value,
    }));
  return [
    { key: "channel", label: "Channel", value: breakdown.channel },
    {
      key: "similarity",
      label: "Similarity to your ratings",
      value: breakdown.similarity,
      detail: similarityDetail(breakdown),
    },
    ...tags,
    {
      key: "model",
      label: "Model",
      value: breakdown.alpha * breakdown.model,
      detail:
        breakdown.alpha > 0
          ? `${formatScore(breakdown.model)} at weight ${breakdown.alpha.toFixed(2)}`
          : "No trained model yet",
    },
  ];
}

function similarityDetail(breakdown: ScoreBreakdownOut): string {
  const features = breakdown.similarity_features;
  if (!features) return "Not analyzed yet";
  const parts: string[] = [];
  if (features.top_tier) {
    parts.push(`closest top-tier video ${features.top_tier.max.toFixed(2)}`);
  }
  if (features.bottom_tier) {
    parts.push(
      `closest bottom-tier video ${features.bottom_tier.max.toFixed(2)}`,
    );
  }
  return parts.length > 0
    ? `Cosine similarity: ${parts.join(", ")}`
    : "No top- or bottom-tier ratings to compare with yet";
}

/** A score term with its sign, e.g. "+0.25", "-0.10" or "0.00". */
export function formatScore(value: number): string {
  const rounded = value.toFixed(2);
  if (Number(rounded) === 0) return "0.00";
  return value > 0 ? `+${rounded}` : rounded;
}

/** Which way a score term moves the score, as `formatScore` shows it. */
export type ScoreDirection = "up" | "down" | "none";

/**
 * Whether `value` adds to the score, takes from it, or (rounded as shown)
 * does neither: what colours a term green, red or grey.
 */
export function scoreDirection(value: number): ScoreDirection {
  if (Number(value.toFixed(2)) === 0) return "none";
  return value > 0 ? "up" : "down";
}
