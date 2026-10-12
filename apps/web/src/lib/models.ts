/** Formatting for the models page. Pure, so server and client render the same text. */

/** A metric to 3 decimals, or "–" when it is undefined (e.g. Spearman on a constant holdout). */
export function formatMetric(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "–";
  return value.toFixed(3);
}

/** An ISO 8601 UTC timestamp as e.g. "Oct 12, 2026, 03:00 UTC", or "–" when unset. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "–";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return `${parsed.toLocaleString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "UTC",
  })} UTC`;
}

const KIND_LABELS: Record<string, string> = {
  lightgbm: "LightGBM",
  ridge: "Ridge",
};

/** The model kind as shown, e.g. "LightGBM". */
export function formatKind(kind: string): string {
  return KIND_LABELS[kind] ?? kind;
}

/** The holdout size from a version's training report, or null if it isn't there. */
export function holdoutSize(metrics: Record<string, unknown>): number | null {
  const n = metrics.n_holdout;
  return typeof n === "number" && Number.isInteger(n) ? n : null;
}
