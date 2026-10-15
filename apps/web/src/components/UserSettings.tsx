import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { SettingsCard } from "#/components/SettingsCard";
import { TimezonePicker } from "#/components/TimezonePicker";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "#/components/ui/alert-dialog";
import { Button } from "#/components/ui/button";
import { CardContent, CardFooter } from "#/components/ui/card";
import { Input } from "#/components/ui/input";
import {
  MAX_SHARE_PERCENT,
  MIN_SHARE_PERCENT,
  formatShare,
  parseSharePercent,
  sharePercentText,
} from "#/lib/feed-mix";
import {
  DEFAULT_MODELS,
  LLM_PROVIDERS,
  MAX_FEED_SIZE,
  MAX_TAG_DISCOVERY_PER_DAY,
  MAX_TAGS_PER_RUN,
  SPONSORBLOCK_CATEGORIES,
  changedValues,
  minutesFromSeconds,
  parseOptionalMinutes,
  parseTime,
  parseWholeNumber,
  sourceLabel,
  timezoneLabel,
  type LlmProvider,
  type Parsed,
} from "#/lib/settings";
import {
  saveSettings,
  settingsQuery,
  type SettingsChanges,
  type SettingsOut,
  type UserSettingKey,
} from "#/server/settings";

/**
 * The settings stored in the app: feed, schedule and time zone, LLM tagging and
 * SponsorBlock. Each section saves on its own; a changed setting can be put
 * back to its default.
 */
export function UserSettings() {
  const { data: settings } = useSuspenseQuery(settingsQuery);
  // Saving lives out here so that its outcome outlasts the remount below.
  const feed = useSave();
  const schedule = useSave();
  const tagging = useSave();
  const sponsorblock = useSave();
  // Remount a form with its saved values when they change. Only its own
  // values: unsaved edits in the other forms must survive a save.
  const version = (section: keyof typeof SECTION_KEYS) =>
    JSON.stringify(SECTION_KEYS[section].map((key) => settings.values[key]));
  return (
    <>
      <FeedSettings
        key={`feed-${version("feed")}`}
        settings={settings}
        saver={feed}
      />
      <ScheduleSettings
        key={`schedule-${version("schedule")}`}
        settings={settings}
        saver={schedule}
      />
      <TaggingSettings
        key={`tagging-${version("tagging")}`}
        settings={settings}
        saver={tagging}
      />
      <SponsorBlockSettings
        key={`sponsorblock-${version("sponsorblock")}`}
        settings={settings}
        saver={sponsorblock}
      />
    </>
  );
}

/** The values each form edits or shows. */
const SECTION_KEYS = {
  feed: [
    "feed_size",
    "feed_exploration_slots",
    "feed_max_topic_share",
    "feed_min_duration_seconds",
    "feed_max_duration_seconds",
  ],
  schedule: ["feed_refresh_time", "model_training_time", "timezone"],
  tagging: [
    "llm_provider",
    "llm_model",
    "llm_max_tags_per_run",
    "tag_discovery_per_day",
    "openrouter_api_key_set",
    "openrouter_api_key_hint",
  ],
  sponsorblock: ["sponsorblock_categories"],
} as const satisfies Record<string, readonly (keyof SettingsOut["values"])[]>;

type Saver = ReturnType<typeof useSave>;

function useSave() {
  const queryClient = useQueryClient();
  const errorId = useId();
  const [message, setMessage] = useState<string | null>(null);
  // The field the message is about, if any.
  const [invalid, setInvalid] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (data: { set?: SettingsChanges; reset?: UserSettingKey[] }) =>
      saveSettings({ data }),
    onSuccess: (result) => {
      if (result.ok) {
        setMessage(null);
        queryClient.setQueryData(settingsQuery.queryKey, result.settings);
      } else {
        setMessage(result.message);
      }
    },
    onError: () => setMessage("Couldn't save your settings. Try again later."),
  });
  return {
    pending: mutation.isPending,
    saved: mutation.isSuccess && mutation.data.ok,
    message,
    errorId,
    /** Say why the form can't be saved, mark the field at fault and focus it. */
    fail: (failure: Failure | null) => {
      setMessage(failure?.message ?? null);
      setInvalid(failure?.fieldId ?? null);
      if (failure) document.getElementById(failure.fieldId)?.focus();
    },
    /** An input's hint, plus the error while that input is at fault. */
    describe: (fieldId: string) =>
      invalid === fieldId
        ? {
            "aria-describedby": `${fieldId}-hint ${errorId}`,
            "aria-invalid": true,
          }
        : { "aria-describedby": `${fieldId}-hint` },
    save: (set: SettingsChanges, reset: UserSettingKey[] = []) => {
      setInvalid(null);
      if (Object.keys(set).length === 0 && reset.length === 0) {
        setMessage(null);
        return;
      }
      mutation.mutate({ set, reset });
    },
  };
}

type Failure = { message: string; fieldId: string };

/** The first failed parse and the field it came from, or null when all worked. */
function firstFailure(
  ...fields: [Parsed<unknown>, fieldId: string][]
): Failure | null {
  for (const [result, fieldId] of fields) {
    if (!result.ok) return { message: result.message, fieldId };
  }
  return null;
}

function Section({
  id,
  title,
  description,
  onSubmit,
  pending,
  saved,
  message,
  errorId,
  children,
}: {
  id: string;
  title: string;
  description: ReactNode;
  onSubmit: () => void;
  pending: boolean;
  saved: boolean;
  message: string | null;
  errorId: string;
  children: ReactNode;
}) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <SettingsCard id={`${id}-heading`} title={title} description={description}>
      <form onSubmit={submit} noValidate className="flex flex-col gap-6">
        <CardContent className="flex flex-col gap-5">{children}</CardContent>
        <CardFooter className="flex-wrap gap-3">
          <Button type="submit" size="lg" className="px-4" disabled={pending}>
            {pending ? "Saving…" : "Save"}
          </Button>
          {message ? (
            <p id={errorId} role="alert" className="text-sm text-destructive">
              {message}
            </p>
          ) : (
            <p role="status" className="text-sm text-muted-foreground">
              {saved && !pending ? "Saved." : ""}
            </p>
          )}
        </CardFooter>
      </form>
    </SettingsCard>
  );
}

/** A labelled field, with where its value comes from and a way back to the default. */
function Field({
  id,
  label,
  hint,
  settingKey,
  settings,
  defaultText,
  onReset,
  pending,
  children,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  settingKey: UserSettingKey;
  settings: SettingsOut;
  /** The default value, as shown to the user. */
  defaultText: string;
  onReset: (key: UserSettingKey) => void;
  pending: boolean;
  children: ReactNode;
}) {
  const source = settings.sources[settingKey];
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {hint}
        {hint ? " " : ""}
        {source === "user" ? (
          <>
            Default: {defaultText}.{" "}
            <button
              type="button"
              disabled={pending}
              onClick={() => onReset(settingKey)}
              className="underline disabled:opacity-50"
            >
              Reset to default
            </button>
          </>
        ) : (
          sourceLabel(source)
        )}
      </p>
    </div>
  );
}

function FeedSettings({
  settings,
  saver,
}: {
  settings: SettingsOut;
  saver: Saver;
}) {
  const id = useId();
  const { values, defaults } = settings;
  const { save, ...state } = saver;
  const [size, setSize] = useState(String(values.feed_size));
  const [slots, setSlots] = useState(String(values.feed_exploration_slots));
  const [share, setShare] = useState(
    sharePercentText(values.feed_max_topic_share),
  );
  const [shortest, setShortest] = useState(
    minutesFromSeconds(values.feed_min_duration_seconds),
  );
  const [longest, setLongest] = useState(
    minutesFromSeconds(values.feed_max_duration_seconds),
  );

  const submit = () => {
    const parsedSize = parseWholeNumber(size, {
      min: 1,
      max: MAX_FEED_SIZE,
      label: "Videos per day",
    });
    const parsedSlots = parseWholeNumber(slots, {
      min: 0,
      max: MAX_FEED_SIZE,
      label: "Discovery slots",
    });
    const parsedShare = parseSharePercent(
      share,
      "Most of a feed one topic may take",
    );
    const parsedShortest = parseOptionalMinutes(shortest, "Shortest video");
    const parsedLongest = parseOptionalMinutes(longest, "Longest video");
    const failure = firstFailure(
      [parsedSize, `${id}-size`],
      [parsedSlots, `${id}-slots`],
      [parsedShare, `${id}-share`],
      [parsedShortest, `${id}-shortest`],
      [parsedLongest, `${id}-longest`],
    );
    if (
      failure ||
      !parsedSize.ok ||
      !parsedSlots.ok ||
      !parsedShare.ok ||
      !parsedShortest.ok ||
      !parsedLongest.ok
    ) {
      state.fail(failure);
      return;
    }
    if (parsedSlots.value > parsedSize.value) {
      state.fail({
        message: "Discovery slots can't be more than videos per day.",
        fieldId: `${id}-slots`,
      });
      return;
    }
    if (
      parsedShortest.value !== null &&
      parsedLongest.value !== null &&
      parsedShortest.value > parsedLongest.value
    ) {
      state.fail({
        message: "The shortest video can't be longer than the longest.",
        fieldId: `${id}-shortest`,
      });
      return;
    }
    save(
      changedValues(
        {
          feed_size: parsedSize.value,
          feed_exploration_slots: parsedSlots.value,
          feed_max_topic_share: parsedShare.value,
          feed_min_duration_seconds: parsedShortest.value,
          feed_max_duration_seconds: parsedLongest.value,
        },
        values,
      ),
    );
  };
  const field = {
    settings,
    pending: state.pending,
    onReset: (key: UserSettingKey) => save({}, [key]),
  };
  const noLimit = (seconds: number | null) =>
    seconds === null ? "no limit" : `${minutesFromSeconds(seconds)} min`;

  return (
    <Section
      id={`${id}-feed`}
      title="Feed"
      description="How big your daily feed is and which videos can be in it."
      onSubmit={submit}
      {...state}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={`${id}-size`}
          label="Videos per day"
          hint="Show more adds this many again."
          settingKey="feed_size"
          defaultText={String(defaults.feed_size)}
          {...field}
        >
          <Input
            id={`${id}-size`}
            type="number"
            inputMode="numeric"
            min={1}
            max={MAX_FEED_SIZE}
            value={size}
            {...state.describe(`${id}-size`)}
            onChange={(event) => setSize(event.target.value)}
            className="max-w-32"
          />
        </Field>
        <Field
          id={`${id}-slots`}
          label="Discovery slots"
          hint="Of those, picks from channels you've rated little or not at all."
          settingKey="feed_exploration_slots"
          defaultText={String(defaults.feed_exploration_slots)}
          {...field}
        >
          <Input
            id={`${id}-slots`}
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_FEED_SIZE}
            value={slots}
            {...state.describe(`${id}-slots`)}
            onChange={(event) => setSlots(event.target.value)}
            className="max-w-32"
          />
        </Field>
        <div className="sm:col-span-2">
          <Field
            id={`${id}-share`}
            label="Most of a feed one topic may take"
            hint={`As a share of the videos per day, from ${MIN_SHARE_PERCENT}% to ${MAX_SHARE_PERCENT}% (${MAX_SHARE_PERCENT}% is no limit). Picks that would go over it come last.`}
            settingKey="feed_max_topic_share"
            defaultText={formatShare(defaults.feed_max_topic_share)}
            {...field}
          >
            <div className="flex items-center gap-2">
              <Input
                id={`${id}-share`}
                type="number"
                inputMode="numeric"
                min={MIN_SHARE_PERCENT}
                max={MAX_SHARE_PERCENT}
                value={share}
                {...state.describe(`${id}-share`)}
                onChange={(event) => setShare(event.target.value)}
                className="max-w-32"
              />
              <span
                aria-hidden="true"
                className="text-sm text-muted-foreground"
              >
                %
              </span>
            </div>
          </Field>
        </div>
        <Field
          id={`${id}-shortest`}
          label="Shortest video (minutes)"
          hint="Empty for no limit."
          settingKey="feed_min_duration_seconds"
          defaultText={noLimit(defaults.feed_min_duration_seconds)}
          {...field}
        >
          <Input
            id={`${id}-shortest`}
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            value={shortest}
            {...state.describe(`${id}-shortest`)}
            onChange={(event) => setShortest(event.target.value)}
            className="max-w-32"
          />
        </Field>
        <Field
          id={`${id}-longest`}
          label="Longest video (minutes)"
          hint="Empty for no limit."
          settingKey="feed_max_duration_seconds"
          defaultText={noLimit(defaults.feed_max_duration_seconds)}
          {...field}
        >
          <Input
            id={`${id}-longest`}
            type="number"
            inputMode="decimal"
            min={0}
            step="any"
            value={longest}
            {...state.describe(`${id}-longest`)}
            onChange={(event) => setLongest(event.target.value)}
            className="max-w-32"
          />
        </Field>
      </div>
    </Section>
  );
}

function ScheduleSettings({
  settings,
  saver,
}: {
  settings: SettingsOut;
  saver: Saver;
}) {
  const id = useId();
  const { values, defaults } = settings;
  const { save, ...state } = saver;
  const [refresh, setRefresh] = useState(values.feed_refresh_time);
  const [training, setTraining] = useState(values.model_training_time);
  const [timezone, setTimezone] = useState(values.timezone ?? "");

  const submit = () => {
    const parsedRefresh = parseTime(refresh, "the daily feed");
    const parsedTraining = parseTime(training, "training");
    if (!parsedRefresh.ok || !parsedTraining.ok) {
      state.fail(
        firstFailure(
          [parsedRefresh, `${id}-refresh`],
          [parsedTraining, `${id}-training`],
        ),
      );
      return;
    }
    const set: SettingsChanges = changedValues(
      {
        feed_refresh_time: parsedRefresh.value,
        model_training_time: parsedTraining.value,
      },
      values,
    );
    const reset: UserSettingKey[] = [];
    if (timezone === "" && settings.sources.timezone === "user") {
      reset.push("timezone");
    } else if (timezone !== "" && timezone !== values.timezone) {
      set.timezone = timezone;
    }
    save(set, reset);
  };
  const field = {
    settings,
    pending: state.pending,
    onReset: (key: UserSettingKey) => save({}, [key]),
  };
  const systemZone = settings.system_timezone
    ? timezoneLabel(settings.system_timezone)
    : "the system's";

  return (
    <Section
      id={`${id}-schedule`}
      title="Schedule and time zone"
      description="When your feed is built and the ranking model learns from your ratings. Changes apply within a minute."
      onSubmit={submit}
      {...state}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={`${id}-refresh`}
          label="New feed every day at"
          settingKey="feed_refresh_time"
          defaultText={defaults.feed_refresh_time}
          {...field}
        >
          <Input
            id={`${id}-refresh`}
            type="time"
            required
            value={refresh}
            {...state.describe(`${id}-refresh`)}
            onChange={(event) => setRefresh(event.target.value)}
            className="max-w-36"
          />
        </Field>
        <Field
          id={`${id}-training`}
          label="Train the model every night at"
          hint="Best a few hours before the feed."
          settingKey="model_training_time"
          defaultText={defaults.model_training_time}
          {...field}
        >
          <Input
            id={`${id}-training`}
            type="time"
            required
            value={training}
            {...state.describe(`${id}-training`)}
            onChange={(event) => setTraining(event.target.value)}
            className="max-w-36"
          />
        </Field>
      </div>
      <Field
        id={`${id}-timezone`}
        label="Time zone"
        hint="Decides when your day starts and when those times are."
        settingKey="timezone"
        defaultText={`system default (${systemZone})`}
        {...field}
      >
        <TimezonePicker
          id={`${id}-timezone`}
          value={timezone}
          system={settings.system_timezone}
          disabled={state.pending}
          describedBy={`${id}-timezone-hint`}
          onChange={setTimezone}
        />
      </Field>
    </Section>
  );
}

function TaggingSettings({
  settings,
  saver,
}: {
  settings: SettingsOut;
  saver: Saver;
}) {
  const id = useId();
  const { values, defaults, sources } = settings;
  const { save, ...state } = saver;
  const [provider, setProvider] = useState<LlmProvider>(values.llm_provider);
  const [model, setModel] = useState(values.llm_model);
  const [key, setKey] = useState("");
  const [perRun, setPerRun] = useState(String(values.llm_max_tags_per_run));
  const [perDay, setPerDay] = useState(String(values.tag_discovery_per_day));

  const submit = () => {
    const parsedPerRun = parseWholeNumber(perRun, {
      min: 0,
      max: MAX_TAGS_PER_RUN,
      label: "Videos tagged per run",
    });
    const parsedPerDay = parseWholeNumber(perDay, {
      min: 0,
      max: MAX_TAG_DISCOVERY_PER_DAY,
      label: "New videos per followed tag",
    });
    if (!parsedPerRun.ok || !parsedPerDay.ok) {
      state.fail(
        firstFailure(
          [parsedPerRun, `${id}-per-run`],
          [parsedPerDay, `${id}-per-day`],
        ),
      );
      return;
    }
    const set: SettingsChanges = changedValues(
      {
        llm_provider: provider,
        llm_model: model.trim(),
        llm_max_tags_per_run: parsedPerRun.value,
        tag_discovery_per_day: parsedPerDay.value,
      },
      values,
    );
    if (key.trim()) set.openrouter_api_key = key.trim();
    save(set);
  };
  const field = {
    settings,
    pending: state.pending,
    onReset: (settingKey: UserSettingKey) => save({}, [settingKey]),
  };
  const providerLabel = (value: LlmProvider) =>
    LLM_PROVIDERS.find((option) => option.value === value)?.label ?? value;
  const keyHint = values.openrouter_api_key_set
    ? `A key ending in ${values.openrouter_api_key_hint ?? "…"} is saved${
        sources.openrouter_api_key === "env"
          ? " in the server's configuration"
          : ""
      }. Enter a new one to replace it.`
    : "Get one at openrouter.ai/settings/keys. It's stored on this computer.";

  return (
    <Section
      id={`${id}-tagging`}
      title="Tagging"
      description="A language model tags new videos (topic, depth, clickbait) so the feed can rank by them, and followed tags find new videos on YouTube."
      onSubmit={submit}
      {...state}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id={`${id}-provider`}
          label="Tag videos with"
          settingKey="llm_provider"
          defaultText={providerLabel(defaults.llm_provider)}
          {...field}
        >
          <select
            id={`${id}-provider`}
            value={provider}
            {...state.describe(`${id}-provider`)}
            onChange={(event) => {
              const picked = LLM_PROVIDERS.find(
                (option) => option.value === event.target.value,
              );
              if (picked) setProvider(picked.value);
            }}
            className="h-8 max-w-64 rounded-lg border border-input bg-transparent px-2 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm dark:bg-input/30"
          >
            {LLM_PROVIDERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        {provider !== "none" && (
          <Field
            id={`${id}-model`}
            label="Model"
            hint="Empty for the provider's default."
            settingKey="llm_model"
            defaultText={defaults.llm_model || "the provider's"}
            {...field}
          >
            <Input
              id={`${id}-model`}
              value={model}
              placeholder={DEFAULT_MODELS[provider]}
              autoComplete="off"
              spellCheck={false}
              {...state.describe(`${id}-model`)}
              onChange={(event) => setModel(event.target.value)}
              className="max-w-sm"
            />
          </Field>
        )}
      </div>
      {provider === "openrouter" && (
        <ApiKeyField
          id={`${id}-key`}
          value={key}
          hint={keyHint}
          canRemove={sources.openrouter_api_key === "user"}
          pending={state.pending}
          onChange={setKey}
          onRemove={() => save({}, ["openrouter_api_key"])}
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {provider !== "none" && (
          <Field
            id={`${id}-per-run`}
            label="Videos tagged per run"
            hint="At most, every 30 minutes; limits what tagging costs."
            settingKey="llm_max_tags_per_run"
            defaultText={String(defaults.llm_max_tags_per_run)}
            {...field}
          >
            <Input
              id={`${id}-per-run`}
              type="number"
              inputMode="numeric"
              min={0}
              max={MAX_TAGS_PER_RUN}
              value={perRun}
              {...state.describe(`${id}-per-run`)}
              onChange={(event) => setPerRun(event.target.value)}
              className="max-w-32"
            />
          </Field>
        )}
        <Field
          id={`${id}-per-day`}
          label="New videos per followed tag"
          hint="Per day, from searching YouTube for the tag. 0 turns it off."
          settingKey="tag_discovery_per_day"
          defaultText={String(defaults.tag_discovery_per_day)}
          {...field}
        >
          <Input
            id={`${id}-per-day`}
            type="number"
            inputMode="numeric"
            min={0}
            max={MAX_TAG_DISCOVERY_PER_DAY}
            value={perDay}
            {...state.describe(`${id}-per-day`)}
            onChange={(event) => setPerDay(event.target.value)}
            className="max-w-32"
          />
        </Field>
      </div>
    </Section>
  );
}

function ApiKeyField({
  id,
  value,
  hint,
  canRemove,
  pending,
  onChange,
  onRemove,
}: {
  id: string;
  value: string;
  hint: string;
  canRemove: boolean;
  pending: boolean;
  onChange: (value: string) => void;
  onRemove: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        OpenRouter API key
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          id={id}
          type="password"
          value={value}
          placeholder="sk-or-…"
          autoComplete="off"
          spellCheck={false}
          aria-describedby={`${id}-hint`}
          onChange={(event) => onChange(event.target.value)}
          className="max-w-sm"
        />
        {canRemove && (
          <AlertDialog open={confirming} onOpenChange={setConfirming}>
            <AlertDialogTrigger
              render={
                <Button
                  type="button"
                  variant="destructive"
                  size="lg"
                  className="px-3"
                  disabled={pending}
                />
              }
            >
              Remove key
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  Remove the OpenRouter API key?
                </AlertDialogTitle>
                <AlertDialogDescription>
                  This computer forgets the key and can&apos;t show it again.
                  Tagging through OpenRouter stops until you enter a key.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  onClick={() => {
                    setConfirming(false);
                    onRemove();
                  }}
                >
                  Remove key
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
      <p id={`${id}-hint`} className="text-xs text-muted-foreground">
        {hint}
      </p>
    </div>
  );
}

function SponsorBlockSettings({
  settings,
  saver,
}: {
  settings: SettingsOut;
  saver: Saver;
}) {
  const id = useId();
  const { values, defaults, sources } = settings;
  const { save, ...state } = saver;
  const [skipped, setSkipped] = useState(
    () => new Set(values.sponsorblock_categories),
  );
  const options = SPONSORBLOCK_CATEGORIES.filter((option) =>
    settings.sponsorblock_category_options.includes(option.value),
  );

  const submit = () => {
    const categories = options
      .map((option) => option.value)
      .filter((value) => skipped.has(value));
    const current = options
      .map((option) => option.value)
      .filter((value) => values.sponsorblock_categories.includes(value));
    save(
      changedValues(
        { sponsorblock_categories: categories },
        { sponsorblock_categories: current },
      ),
    );
  };
  const toggle = (value: string, on: boolean) =>
    setSkipped((before) => {
      const next = new Set(before);
      if (on) next.add(value);
      else next.delete(value);
      return next;
    });
  const defaultText =
    defaults.sponsorblock_categories.length === 0
      ? "nothing"
      : defaults.sponsorblock_categories
          .map(
            (value) =>
              SPONSORBLOCK_CATEGORIES.find((option) => option.value === value)
                ?.label ?? value,
          )
          .join(", ")
          .toLowerCase();

  return (
    <Section
      id={`${id}-sponsorblock`}
      title="Skipping segments"
      description="The player skips these parts of videos, as marked by SponsorBlock's community."
      onSubmit={submit}
      {...state}
    >
      <fieldset
        className="flex flex-col gap-2"
        aria-describedby={`${id}-sponsorblock-hint`}
      >
        <legend className="sr-only">Parts to skip</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((option) => (
            <label
              key={option.value}
              className="flex items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                checked={skipped.has(option.value)}
                disabled={state.pending}
                onChange={(event) => toggle(option.value, event.target.checked)}
              />
              {option.label}
            </label>
          ))}
        </div>
        <p
          id={`${id}-sponsorblock-hint`}
          className="text-xs text-muted-foreground"
        >
          None checked turns skipping off.{" "}
          {sources.sponsorblock_categories === "user" ? (
            <>
              Default: {defaultText}.{" "}
              <button
                type="button"
                disabled={state.pending}
                onClick={() => save({}, ["sponsorblock_categories"])}
                className="underline disabled:opacity-50"
              >
                Reset to default
              </button>
            </>
          ) : (
            sourceLabel(sources.sponsorblock_categories)
          )}
        </p>
      </fieldset>
    </Section>
  );
}
