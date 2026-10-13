/** Tag pages: URL parsing and paging. Pure. */

/** Videos per tag page: fills the grid at 2, 3 and 4 columns. */
export const TAG_PAGE_SIZE = 24;

/** Longest tag slug the API accepts. */
export const TAG_SLUG_MAX_LENGTH = 100;

/** A tag page's URL state. */
export interface TagParams {
  /** 1-based; omitted for the first page. */
  page?: number;
}

/** The tag page's URL search params, dropping anything unknown and the default. */
export function parseTagParams(raw: Record<string, unknown>): TagParams {
  const page = typeof raw.page === "string" ? Number(raw.page) : raw.page;
  if (typeof page === "number" && Number.isInteger(page) && page > 1) {
    return { page: Math.min(page, 10_000) };
  }
  return {};
}

/** Whether `slug` could be a tag's (or alias's) slug; anything else is a 404. */
export function isTagSlug(slug: string): boolean {
  return slug.length > 0 && slug.length <= TAG_SLUG_MAX_LENGTH;
}

/** The API's `limit` and `offset` for a page. */
export function tagWindow(params: TagParams): {
  limit: number;
  offset: number;
} {
  return {
    limit: TAG_PAGE_SIZE,
    offset: ((params.page ?? 1) - 1) * TAG_PAGE_SIZE,
  };
}

/** How many pages `videoCount` videos make (at least one). */
export function pageCount(videoCount: number): number {
  return Math.max(1, Math.ceil(videoCount / TAG_PAGE_SIZE));
}

/** "1 video" or "12 videos". */
export function describeVideoCount(count: number): string {
  return `${count} ${count === 1 ? "video" : "videos"}`;
}
