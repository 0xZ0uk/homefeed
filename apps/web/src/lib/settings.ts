/** Helpers for the settings page's feed, schedule, tagging and SponsorBlock sections. Pure, so they are easy to test. */

import type { SettingsOut, UserSettingKey } from "@homefeed/api-client";

export type SettingSource = SettingsOut["sources"][UserSettingKey];
export type LlmProvider = SettingsOut["values"]["llm_provider"];

/** Limits matching the API's (`homefeed_core.user_settings`). */
export const MAX_FEED_SIZE = 200;
export const MAX_TAGS_PER_RUN = 100_000;
export const MAX_TAG_DISCOVERY_PER_DAY = 1_000;

export const LLM_PROVIDERS: { value: LlmProvider; label: string }[] = [
  { value: "openrouter", label: "OpenRouter (hosted)" },
  { value: "ollama", label: "Ollama (on this computer)" },
  { value: "none", label: "Off" },
];

/** Provider defaults, shown when the model is left empty (see `homefeed_core.llm_tags`). */
export const DEFAULT_MODELS: Record<LlmProvider, string> = {
  openrouter: "google/gemini-2.5-flash-lite",
  ollama: "llama3.1:8b",
  none: "",
};

/** SponsorBlock categories in the order shown, with what each skips. */
export const SPONSORBLOCK_CATEGORIES: { value: string; label: string }[] = [
  { value: "sponsor", label: "Sponsors" },
  { value: "selfpromo", label: "Self-promotion and merch" },
  { value: "interaction", label: "Like and subscribe reminders" },
  { value: "intro", label: "Intros" },
  { value: "outro", label: "Endcards and credits" },
  { value: "preview", label: "Previews and recaps" },
  { value: "hook", label: "Hooks and greetings" },
  { value: "music_offtopic", label: "Non-music parts of music videos" },
  { value: "filler", label: "Filler tangents and jokes" },
];

/** Where a setting's value comes from, for a hint next to it ("" for the built-in default). */
export function sourceLabel(source: SettingSource | undefined): string {
  switch (source) {
    case "user":
      return "Changed here.";
    case "env":
      return "From the server's configuration.";
    default:
      return "";
  }
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; message: string };

/** A whole number from a form field, within `min` and `max`. */
export function parseWholeNumber(
  raw: string,
  { min, max, label }: { min: number; max: number; label: string },
): Parsed<number> {
  const text = raw.trim();
  const value = Number(text);
  if (text === "" || !Number.isInteger(value) || value < min || value > max) {
    return {
      ok: false,
      message: `${label} must be a whole number from ${min} to ${max.toLocaleString("en")}.`,
    };
  }
  return { ok: true, value };
}

/** A duration bound in minutes from a form field, as seconds; empty means no bound. */
export function parseOptionalMinutes(
  raw: string,
  label: string,
): Parsed<number | null> {
  const text = raw.trim();
  if (text === "") return { ok: true, value: null };
  const minutes = Number(text);
  if (!Number.isFinite(minutes) || minutes < 0 || minutes > 24 * 60) {
    return {
      ok: false,
      message: `${label} must be a number of minutes, or empty for no limit.`,
    };
  }
  return { ok: true, value: Math.round(minutes * 60) };
}

/** Seconds as minutes for a form field (empty for no bound). */
export function minutesFromSeconds(seconds: number | null): string {
  return seconds === null ? "" : String(Math.round((seconds / 60) * 100) / 100);
}

/** A local time of day as HH:MM, as `<input type="time">` gives it. */
export function parseTime(raw: string, label: string): Parsed<string> {
  const match = /^(\d{2}):(\d{2})(?::\d{2})?$/.exec(raw.trim());
  if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) {
    return { ok: false, message: `Choose a time for ${label}.` };
  }
  return { ok: true, value: `${match[1]}:${match[2]}` };
}

/** "America/Argentina/Buenos_Aires" as "America/Argentina/Buenos Aires". */
export function timezoneLabel(zone: string): string {
  return zone.replaceAll("_", " ");
}

export interface TimezoneItem {
  /** IANA name; "" is the system's time zone. */
  value: string;
  label: string;
}

/**
 * The time zone picker's items: the system's first, then every zone the
 * browser knows (plus the current one, should it not be among them).
 */
export function timezoneItems(
  zones: readonly string[],
  system: string | null,
  current: string | null,
): TimezoneItem[] {
  const names = [...zones];
  if (current && !names.includes(current)) names.push(current);
  names.sort();
  return [
    {
      value: "",
      label: system
        ? `System default (${timezoneLabel(system)})`
        : "System default",
    },
    ...names.map((zone) => ({ value: zone, label: timezoneLabel(zone) })),
  ];
}

/** Every IANA time zone this browser (or server) knows; empty if it can't say. */
export function supportedTimezones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

/** The entries of `next` whose values differ from `current`'s. */
export function changedValues<T extends object>(
  next: T,
  current: Partial<Record<keyof T, unknown>>,
): Partial<T> {
  const changed: Partial<T> = {};
  for (const key of Object.keys(next) as (keyof T)[]) {
    if (JSON.stringify(next[key]) !== JSON.stringify(current[key])) {
      changed[key] = next[key];
    }
  }
  return changed;
}
