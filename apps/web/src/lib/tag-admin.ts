/** Wording for the Subscriptions page's tags tab. */

export function videoCount(count: number): string {
  return `${count} ${count === 1 ? "video" : "videos"}`;
}

/** What merging `source` into `target` does, for the confirmation. */
export function mergeSummary(source: string, target: string): string {
  return `“${source}” and its spellings become spellings of “${target}”, its videos move there, and “${source}” is deleted.`;
}
