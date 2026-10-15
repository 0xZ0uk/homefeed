/**
 * The Taste page's words and rules: what to make of the numbers the API
 * reports (a topic that takes most of your picks, a followed one that hardly
 * shows up), the summary at the top and the copy of each section. Pure, so
 * server and client render the same text and the rules can be tested.
 */

import type { TasteOut } from "@homefeed/api-client";

import { PRIOR_LABELS } from "#/lib/channels";
import { formatPercent, plural } from "#/lib/insights";
import { formatKind, formatTimestamp } from "#/lib/models";
import { TOP_TIER_THRESHOLD } from "#/lib/scores";
import {
  clampWeight,
  formatWeight,
  weightEffect,
} from "#/lib/tag-subscriptions";

export type Taste = TasteOut;
export type TagTaste = TasteOut["tags"][number];
export type RatedChannel = TasteOut["unfollowed_channels"][number];

/** Days of feeds and dismissals the page counts; the API's default window. */
export const TASTE_DAYS = 30;

/**
 * A topic on at least this share of the picks takes more than its share: of
 * 40 picks, 16 or more carry it. The share is compared as the whole percent
 * the page shows, so a topic shown at "40% of your picks" is always flagged.
 */
export const DOMINANT_SHARE = 0.4;

/** A followed topic with this many picks or fewer hardly shows up. */
export const RARE_MAX_PICKS = 1;

/**
 * The fewest picks in the window for the balance to mean anything: two picks
 * out of three are not a pattern, and a first small feed isn't a sample.
 */
export const MIN_PICKS_FOR_BALANCE = 10;

/** How far one click on a suggestion moves a boost. */
export const SUGGESTED_STEP = 0.3;

/** A boost from here up is a strong one: you love the topic. */
export const LOVE_WEIGHT = 0.7;
/** A boost at or below this barely counts: you're lukewarm on the topic. */
export const LUKEWARM_WEIGHT = 0.2;
/** Ratings averaging this or more: you love the topic. */
export const LOVE_AVERAGE = 8;
/** Ratings averaging less than this: you're lukewarm on the topic. */
export const LUKEWARM_AVERAGE = 6.5;
/** Ratings say how you feel about a topic from this many of them. */
export const MIN_RATINGS_FOR_STANCE = 2;

/** At most this many names are listed in a sentence; the rest are counted. */
const NAMES_SHOWN = 3;

interface Labelled {
  label: string;
  slug: string;
}

/** A–Z by label, ignoring case; the slug breaks ties. */
function byLabel(a: Labelled, b: Labelled): number {
  return (
    a.label.localeCompare(b.label, "en", { sensitivity: "base" }) ||
    a.slug.localeCompare(b.slug)
  );
}

/**
 * The followed topics, the most picked first (so the row being edited doesn't
 * move when its boost changes), then A–Z. A weight of 0 still follows the tag,
 * with no effect, as the Tags tab shows it.
 */
export function followedTopics(tags: readonly TagTaste[]): TagTaste[] {
  return tags
    .filter((tag) => tag.weight >= 0)
    .sort((a, b) => b.picks - a.picks || byLabel(a, b));
}

/** The muted topics (a negative weight), A–Z. */
export function mutedTopics(tags: readonly TagTaste[]): TagTaste[] {
  return tags.filter((tag) => tag.weight < 0).sort(byLabel);
}

/** The share of all picks that carry a topic, 0 to 1. */
export function shareOfPicks(picks: number, totalPicks: number): number {
  return totalPicks > 0 ? Math.min(1, picks / totalPicks) : 0;
}

/** What is off about a followed topic's share of the picks. */
export type Imbalance =
  | { kind: "dominant"; share: number; picks: number }
  | { kind: "rare"; picks: number };

/**
 * Whether a followed topic takes a large part of the picks (`DOMINANT_SHARE`
 * or more) or hardly shows up (`RARE_MAX_PICKS` or fewer). Null when it
 * doesn't, before `MIN_PICKS_FOR_BALANCE` videos were picked, and for a muted
 * topic, which is meant to stay away.
 */
export function imbalanceOf(
  tag: Pick<TagTaste, "weight" | "picks">,
  totalPicks: number,
): Imbalance | null {
  if (tag.weight < 0 || totalPicks < MIN_PICKS_FOR_BALANCE) return null;
  const share = shareOfPicks(tag.picks, totalPicks);
  if (Math.round(share * 100) >= DOMINANT_SHARE * 100) {
    return { kind: "dominant", share, picks: tag.picks };
  }
  if (tag.picks <= RARE_MAX_PICKS) return { kind: "rare", picks: tag.picks };
  return null;
}

function picksIn(picks: number, days: number): string {
  return `${picks === 0 ? "no picks" : plural(picks, "pick")} in the last ${days} days`;
}

/** "Takes 75% of your picks" or "Rarely shows up: 1 pick in the last 30 days". */
export function describeImbalance(
  imbalance: Imbalance,
  days: number = TASTE_DAYS,
): string {
  return imbalance.kind === "dominant"
    ? `Takes ${formatPercent(imbalance.share)} of your picks`
    : `Rarely shows up: ${picksIn(imbalance.picks, days)}`;
}

/** A boost to offer instead of the current one, and the button's words. */
export interface Suggestion {
  weight: number;
  label: string;
}

/**
 * The one click that would help: a topic that takes too much gets a lower
 * boost, one that hardly shows up a higher one, `SUGGESTED_STEP` away and
 * within the range a followed topic has (0 to 1). Null when the boost can't
 * move that way, e.g. a rare topic already at +1.00.
 */
export function suggestionFor(
  tag: Pick<TagTaste, "weight">,
  imbalance: Imbalance,
): Suggestion | null {
  const lower = imbalance.kind === "dominant";
  const weight = clampWeight(
    lower
      ? Math.max(0, tag.weight - SUGGESTED_STEP)
      : Math.min(1, tag.weight + SUGGESTED_STEP),
  );
  if (weight === clampWeight(tag.weight)) return null;
  return {
    weight,
    label: `${lower ? "Lower" : "Raise"} boost to ${formatWeight(weight)}`,
  };
}

/**
 * A topic's numbers on one line, as a channel's are on the Subscriptions page:
 * "Watched 12 of 30 picks · avg 7.4 from 5 ratings". The picks are those of the
 * window; the ratings are all of them.
 */
export function describeTopic(
  tag: Pick<
    TagTaste,
    "picks" | "watched_picks" | "rating_count" | "average_score"
  >,
  days: number = TASTE_DAYS,
): string {
  const { picks, watched_picks, rating_count, average_score } = tag;
  return [
    picks > 0
      ? `Watched ${watched_picks} of ${plural(picks, "pick")}`
      : `No picks in the last ${days} days`,
    rating_count > 0 && average_score !== null
      ? describeRatings(rating_count, average_score)
      : "no ratings yet",
  ].join(" · ");
}

/**
 * What a muted topic does and whether it still gets through, e.g. "Suppress
 * −0.50 · 2 picks in the last 30 days anyway". Hiding drops its videos, so
 * that says so.
 */
export function describeMuted(
  tag: Pick<TagTaste, "weight" | "hide" | "picks">,
  days: number = TASTE_DAYS,
): string {
  return [
    `${weightEffect(tag.weight)} ${formatWeight(tag.weight)}`,
    tag.hide ? "hides its videos" : null,
    tag.picks > 0
      ? `${plural(tag.picks, "pick")} in the last ${days} days anyway`
      : null,
  ]
    .filter((part) => part !== null)
    .join(" · ");
}

/** "avg 9.0 from 4 ratings". */
export function describeRatings(count: number, average: number): string {
  return `avg ${average.toFixed(1)} from ${plural(count, "rating")}`;
}

/** How you feel about a followed topic. */
export type Stance = "love" | "lukewarm";

/**
 * Whether you love a followed topic or are lukewarm on it. Ratings speak first,
 * from `MIN_RATINGS_FOR_STANCE` of them: an average of `LOVE_AVERAGE` or more is
 * love, under `LUKEWARM_AVERAGE` lukewarm. Anything between, and a topic with
 * fewer ratings, goes by its boost: `LOVE_WEIGHT` or more is love,
 * `LUKEWARM_WEIGHT` or less lukewarm. Anything else is neither, and a muted
 * topic has no stance.
 */
export function stanceOf(
  tag: Pick<TagTaste, "weight" | "rating_count" | "average_score">,
): Stance | null {
  if (tag.weight < 0) return null;
  const { average_score: average } = tag;
  if (tag.rating_count >= MIN_RATINGS_FOR_STANCE && average !== null) {
    if (average >= LOVE_AVERAGE) return "love";
    if (average < LUKEWARM_AVERAGE) return "lukewarm";
  }
  if (tag.weight >= LOVE_WEIGHT) return "love";
  if (tag.weight <= LUKEWARM_WEIGHT) return "lukewarm";
  return null;
}

/** "A", "A and B", "A, B and C" or "A, B, C and 2 others". */
export function nameList(names: readonly string[]): string {
  if (names.length <= 1) return names.join("");
  if (names.length <= NAMES_SHOWN) {
    return `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  }
  const rest = names.length - NAMES_SHOWN;
  return `${names.slice(0, NAMES_SHOWN).join(", ")} and ${rest} ${rest === 1 ? "other" : "others"}`;
}

/**
 * Clauses of one sentence: "A", "A, and B" or "A, B, and C". When a clause
 * lists names (so has commas of its own) they are separated by semicolons
 * instead, as in "A, B and C; D", which keeps the lists apart.
 */
function joinClauses(clauses: readonly string[]): string {
  if (clauses.length <= 1) return clauses.join("");
  const last = clauses.at(-1);
  if (clauses.some((clause) => clause.includes(","))) {
    const head = clauses.slice(0, -1).join("; ");
    return clauses.length === 2 ? `${head}; ${last}` : `${head}; and ${last}`;
  }
  return `${clauses.slice(0, -1).join(", ")}, and ${last}`;
}

/** Labels, the most boosted first, then the best rated, then A–Z. */
function labelsByStrength(tags: readonly TagTaste[]): string[] {
  return [...tags]
    .sort(
      (a, b) =>
        b.weight - a.weight ||
        (b.average_score ?? 0) - (a.average_score ?? 0) ||
        byLabel(a, b),
    )
    .map((tag) => tag.label);
}

/**
 * Who you love, who you are lukewarm on and what you muted: "You love Godot and
 * developer tools, and you're lukewarm on news." With nothing that stands out
 * it says how many topics you follow; with none at all, that the feed has only
 * your channels and ratings to go on.
 */
function tasteSentence(tags: readonly TagTaste[]): string {
  const followed = followedTopics(tags);
  const muted = mutedTopics(tags);
  if (followed.length === 0 && muted.length === 0) {
    return "You haven't followed any topics yet, so the feed has only your channels and ratings to go on.";
  }
  const loved = followed.filter((tag) => stanceOf(tag) === "love");
  const lukewarm = followed.filter((tag) => stanceOf(tag) === "lukewarm");

  const clauses: string[] = [];
  if (loved.length > 0) {
    clauses.push(`you love ${nameList(labelsByStrength(loved))}`);
  }
  if (lukewarm.length > 0) {
    clauses.push(`you're lukewarm on ${nameList(labelsByStrength(lukewarm))}`);
  }
  if (clauses.length === 0 && followed.length > 0) {
    clauses.push(`you follow ${plural(followed.length, "topic")}`);
  }
  if (muted.length > 0) {
    clauses.push(`you've muted ${nameList(muted.map((tag) => tag.label))}`);
  }
  const sentence = `${joinClauses(clauses)}.`;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/**
 * What is out of balance in the picks, in one sentence: "Game development takes
 * 75% of your picks, while Rust is followed but rarely shows up: 1 pick in the
 * last 30 days." Null when nothing is.
 */
function balanceSentence(
  tags: readonly TagTaste[],
  totalPicks: number,
  days: number,
): string | null {
  const flagged = followedTopics(tags).map((tag) => ({
    tag,
    imbalance: imbalanceOf(tag, totalPicks),
  }));
  const dominant = flagged
    .flatMap(({ tag, imbalance }) =>
      imbalance?.kind === "dominant" ? [{ tag, share: imbalance.share }] : [],
    )
    .sort((a, b) => b.share - a.share);
  const rare = flagged.flatMap(({ tag, imbalance }) =>
    imbalance?.kind === "rare" ? [tag] : [],
  );

  const clauses: string[] = [];
  if (dominant.length > 0) {
    const [first, second] = dominant;
    clauses.push(
      `${first?.tag.label} takes ${formatPercent(first?.share)} of your picks` +
        (second
          ? ` and ${second.tag.label} takes ${formatPercent(second.share)}`
          : ""),
    );
  }
  const [onlyRare] = rare;
  if (rare.length === 1 && onlyRare) {
    clauses.push(
      `${onlyRare.label} is followed but rarely shows up: ${picksIn(onlyRare.picks, days)}`,
    );
  } else if (rare.length > 1) {
    const names = nameList(labelsByStrength(rare));
    clauses.push(
      `${names} are followed but rarely show up: ${plural(RARE_MAX_PICKS, "pick")} or fewer each in the last ${days} days`,
    );
  }
  if (clauses.length === 0) return null;
  // A tag's label can be lowercase, and this sentence starts with one.
  const sentence = `${clauses.join(", while ")}.`;
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/** How many ratings you have, and what that means for the model. */
function ratingsSentence(ratings: number, needed: number): string {
  if (ratings >= needed) {
    return `You've rated ${plural(ratings, "video")}, enough for the model to train on.`;
  }
  const rated =
    ratings === 0
      ? "You haven't rated any videos yet"
      : `You've rated ${plural(ratings, "video")}`;
  return `${rated}; the model starts training at ${needed}.`;
}

/** What the page says before it knows anything about you. */
export const FRESH_SUMMARY =
  "Homefeed doesn't know your taste yet. Follow a few topics and rate what you watch, and this page will show what it learns.";

/**
 * Two or three plain sentences on what the app believes about you, made from
 * the numbers: who you love and are lukewarm on, what is out of balance in your
 * picks, and how far your ratings are from training the model. For example:
 * "You love Godot and developer tools, and you're lukewarm on news. Rust is
 * followed but rarely shows up: 1 pick in the last 30 days. You've rated 10
 * videos; the model starts training at 20." A fresh install gets one sentence
 * on where to begin.
 */
export function summarizeTaste(
  taste: Pick<
    Taste,
    "tags" | "total_picks" | "days" | "min_ratings_to_train" | "signals"
  >,
): string[] {
  const { tags, signals } = taste;
  if (tags.length === 0 && signals.ratings === 0) return [FRESH_SUMMARY];
  return [
    tasteSentence(tags),
    balanceSentence(tags, taste.total_picks, taste.days),
    ratingsSentence(signals.ratings, taste.min_ratings_to_train),
  ].filter((sentence): sentence is string => sentence !== null);
}

/** The channels you follow, all preferences counted. */
export function totalChannels(counts: Taste["channel_priors"]): number {
  return counts.love + counts.like + counts.neutral + counts.skeptical;
}

/**
 * A nudge when half of the channels or more are still on the default
 * preference, which tells the feed nothing: it learns about those only from
 * your ratings. Null otherwise.
 */
export function neutralNudge(counts: Taste["channel_priors"]): string | null {
  const total = totalChannels(counts);
  const { neutral } = counts;
  if (neutral === 0 || neutral * 2 < total) return null;
  const which =
    neutral === total
      ? total === 1
        ? "Your channel is"
        : `All ${total} of your channels are`
      : `${neutral} of your ${total} channels ${neutral === 1 ? "is" : "are"}`;
  return `${which} still on ${PRIOR_LABELS.neutral}, the default, so the feed only learns about ${neutral === 1 ? "it" : "them"} from your ratings. Set ${PRIOR_LABELS.love}, ${PRIOR_LABELS.like} or ${PRIOR_LABELS.skeptical} on the ones you have a view on.`;
}

/** At most this many of the channels you follow are listed as best rated. */
export const TOP_RATED_SHOWN = 5;

/** The fewest ratings for a channel to count as rated well (as the API counts it). */
export const RATED_MIN_RATINGS = 2;

/** The average from which a channel counts as rated well (as the API counts it). */
export const RATED_MIN_AVERAGE = TOP_TIER_THRESHOLD;

/** What rating a channel well takes, for the notes under empty lists. */
export const RATED_WELL = `${RATED_MIN_AVERAGE} or higher on average, from ${RATED_MIN_RATINGS} ratings or more`;

/** A followed channel with its ratings. */
export interface RatedFollowed<T> {
  channel: T;
  rating_count: number;
  average_score: number;
}

/**
 * The channels you follow whose videos you rated best: those averaging
 * `RATED_MIN_AVERAGE` or more from `RATED_MIN_RATINGS` ratings or more (so one
 * lucky video doesn't make a favourite), the highest average first, then the
 * most ratings, then A–Z. `health` is the per-channel numbers of the
 * Subscriptions page.
 */
export function topRatedChannels<
  T extends { channel_id: string; title: string },
>(
  channels: readonly T[],
  health: ReadonlyMap<
    string,
    { rating_count: number; average_score: number | null }
  >,
  limit: number = TOP_RATED_SHOWN,
): RatedFollowed<T>[] {
  return channels
    .flatMap((channel) => {
      const stats = health.get(channel.channel_id);
      if (
        !stats ||
        stats.average_score === null ||
        stats.average_score < RATED_MIN_AVERAGE ||
        stats.rating_count < RATED_MIN_RATINGS
      ) {
        return [];
      }
      return [
        {
          channel,
          rating_count: stats.rating_count,
          average_score: stats.average_score,
        },
      ];
    })
    .sort(
      (a, b) =>
        b.average_score - a.average_score ||
        b.rating_count - a.rating_count ||
        a.channel.title.localeCompare(b.channel.title, "en", {
          sensitivity: "base",
        }),
    )
    .slice(0, limit);
}

/** What each signal does to the ranking, in a line. */
export const SIGNAL_EFFECTS = {
  ratings:
    "Ratings train the model, set each channel's score and decide which videos new picks are compared with.",
  more: "Pushes videos like these up in the next feeds, as a high rating would, without counting as a rating.",
  less: "Pushes videos like these down in the next feeds, as a low rating would, without counting as a rating.",
  dismissals:
    "A dismissed video never comes back, and counts as a weak “no” when the model trains.",
} as const;

/** The reason a dismissal was given, or that there was none. */
export function dismissalReason(reason: string | null): string {
  return reason ?? "No reason given";
}

/** How many videos were dismissed, over all reasons. */
export function totalDismissals(
  dismissals: readonly { count: number }[],
): number {
  return dismissals.reduce((sum, { count }) => sum + count, 0);
}

/**
 * How much of what you watched you rated, for under the rating count: "38% of
 * the 26 videos you've watched". Null before you watched anything.
 */
export function describeRatedShare(
  ratings: number,
  watched: number,
): string | null {
  if (watched <= 0) return null;
  return `${formatPercent(ratings / watched)} of the ${plural(watched, "video")} you've watched`;
}

/** The slice of a model version the page reads. */
export interface ModelVersionStatus {
  id: number;
  kind: string;
  active: boolean;
  created_at: string;
}

/**
 * Where the ranking model stands, in a sentence or two: the active version and
 * when it was trained, no active version, or no model at all (with how far your
 * ratings are from training one).
 */
export function describeModel(
  versions: readonly ModelVersionStatus[],
  ratings: number,
  needed: number,
): string {
  const active = versions.find((version) => version.active);
  if (active) {
    return `Version ${active.id} (${formatKind(active.kind)}) ranks your feed, together with your subscriptions and topics. It was trained on ${formatTimestamp(active.created_at)}.`;
  }
  if (versions.length > 0) {
    return "No model is active, so the feed is ranked by your subscriptions and topics. Choose a version on the Models page.";
  }
  const base =
    "No model yet: until there are enough ratings, the feed is ranked by your subscriptions and topics.";
  return ratings >= needed
    ? `${base} You have enough now, so the next scheduled training should make one.`
    : `${base} You have ${ratings} of the ${needed} it needs to start.`;
}

/*
 * What the status line says after an action on a topic. A boost dragged below
 * zero mutes the topic, which moves it to the muted list, so it says so.
 */

export function boostMessage(label: string, weight: number): string {
  return weight < 0
    ? `Muted ${label} (${formatWeight(weight)}).`
    : `Set the boost of ${label} to ${formatWeight(weight)}. The next feed uses it.`;
}

export function mutedMessage(label: string): string {
  return `Muted ${label}. It's in your muted topics now.`;
}

export function unfollowedMessage(label: string): string {
  return `Unfollowed ${label}.`;
}

export function unmutedMessage(label: string): string {
  return `Unmuted ${label}.`;
}

export function restoredMessage(label: string): string {
  return `Restored ${label}.`;
}

/*
 * What the status line says after an action on a channel you rate well but
 * don't follow.
 */

export function subscribedMessage(title: string): string {
  return `Subscribed to ${title}.`;
}

export function trialMessage(title: string, created: boolean): string {
  return created
    ? `Started a 2-week trial of ${title}. You decide in Subscriptions whether to keep it.`
    : `You're already subscribed to ${title}.`;
}

export function unsubscribedMessage(title: string): string {
  return `Unsubscribed from ${title}.`;
}
