/**
 * The pure parts of the home page's Discovery carousel: paging through its
 * slides and naming where each video was found.
 */

/** How long the carousel shows a page before moving on, when it's running. */
export const AUTO_ADVANCE_MS = 6000;

/** Pages of `count` slides shown `perPage` at a time; at least one. */
export function pageCount(count: number, perPage: number): number {
  return Math.max(1, Math.ceil(count / Math.max(1, perPage)));
}

/** The page after `page`, back to the first after the last. */
export function nextPage(page: number, pages: number): number {
  return pages > 0 ? (page + 1) % pages : 0;
}

/** `page` kept within the `pages` there are. */
export function clampPage(page: number, pages: number): number {
  return Math.min(Math.max(0, page), Math.max(0, pages - 1));
}

const SOURCE_LABELS: Record<string, string> = {
  related: "Related",
  channel_graph: "Featured channel",
  tag: "Tag",
  saved_search: "Saved search",
  external: "Linked",
};

/** Longest a label taken from a source's detail (a search, a feed) may be. */
const DETAIL_MAX_LENGTH = 28;

/**
 * A short label for where a video was found: the tag (`#woodworking`), saved
 * search or external source by name when known, otherwise the kind of source.
 * Null for sources it doesn't know.
 */
export function sourceLabel(
  source: string,
  detail?: string | null,
): string | null {
  const name = detail?.trim();
  if (name && source === "tag") return `#${name}`;
  if (name && (source === "saved_search" || source === "external")) {
    return name.length > DETAIL_MAX_LENGTH
      ? `${name.slice(0, DETAIL_MAX_LENGTH - 1).trimEnd()}…`
      : name;
  }
  return SOURCE_LABELS[source] ?? null;
}
