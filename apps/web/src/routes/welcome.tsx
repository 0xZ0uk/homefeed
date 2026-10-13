import type { SubscribedChannel } from "@homefeed/api-client";
import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { Search as SearchIcon } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ChannelAvatar } from "#/components/ChannelAvatar";
import { Button } from "#/components/ui/button";
import { Input } from "#/components/ui/input";
import { channelUrl } from "#/lib/discover";
import {
  THIN_FEED_CHANNELS,
  channelCount,
  type ChannelHit,
} from "#/lib/onboarding";
import { QUERY_MAX_LENGTH } from "#/lib/search";
import { channelsQuery, subscribe, unsubscribe } from "#/server/channels";
import { todayFeedQuery } from "#/server/feeds";
import {
  finishOnboarding,
  onboardingQuery,
  searchChannels,
  skipOnboarding,
} from "#/server/onboarding";

/**
 * First-run setup: what Homefeed is, a few channels to subscribe to, then
 * building the first feed. Shown from the home page until it is finished or
 * skipped (or there is a subscription); reachable by URL any time.
 */
export const Route = createFileRoute("/welcome")({
  head: () => ({ meta: [{ title: "Welcome · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(channelsQuery),
  component: Welcome,
});

const STEPS = ["Welcome", "Add channels", "Build your feed"] as const;

function Welcome() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);

  // Keep keyboard and screen reader users in place when the step's content is
  // swapped: land on the new step's heading.
  useEffect(() => {
    if (moved.current) headingRef.current?.focus();
    moved.current = true;
  }, [step]);

  const skip = useMutation({
    mutationFn: () => skipOnboarding(),
    onSuccess: async (status) => {
      queryClient.setQueryData(onboardingQuery.queryKey, status);
      await navigate({ to: "/" });
    },
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-6 px-4 py-6 sm:py-10">
      <header className="flex items-center justify-between gap-4">
        <p className="text-lg font-bold">Homefeed</p>
        <Button
          variant="ghost"
          size="lg"
          className="px-3"
          disabled={skip.isPending}
          onClick={() => skip.mutate()}
        >
          Skip setup
        </Button>
      </header>
      {skip.isError && (
        <p role="alert" className="text-destructive">
          Couldn't skip setup. Try again later.
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        Step {step + 1} of {STEPS.length}
      </p>
      <h1
        ref={headingRef}
        tabIndex={-1}
        className="text-2xl font-semibold outline-none"
      >
        {STEPS[step]}
      </h1>
      {step === 0 && <WelcomeStep onNext={() => setStep(1)} />}
      {step === 1 && (
        <ChannelsStep onBack={() => setStep(0)} onNext={() => setStep(2)} />
      )}
      {step === 2 && <FinishStep onBack={() => setStep(1)} />}
    </main>
  );
}

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <section className="flex flex-col gap-4">
      <p className="text-pretty text-lg">
        Homefeed gives you a short home feed once a day, built from the
        channels you follow, and it ends. No endless scrolling.
      </p>
      <p className="text-pretty text-muted-foreground">
        Rate what you watch from 1 to 10 and it learns what you like, so
        tomorrow's feed fits you better. To start, it needs a few channels.
      </p>
      <div>
        <Button size="lg" className="px-5" onClick={onNext}>
          Get started
        </Button>
      </div>
    </section>
  );
}

function ChannelsStep({
  onBack,
  onNext,
}: {
  onBack: () => void;
  onNext: () => void;
}) {
  const { data: channels } = useSuspenseQuery(channelsQuery);
  const [status, setStatus] = useState("");

  return (
    <div className="flex flex-col gap-8">
      <p className="text-pretty text-muted-foreground">
        Add the channels you'd want to see new videos from. Five to ten is a
        good start, and you can change them later.
      </p>
      <ChannelSearch
        subscribedIds={new Set(channels.map((c) => c.channel_id))}
        onStatus={setStatus}
      />
      <PasteLink onStatus={setStatus} />
      <p role="status" className="min-h-6">
        {status}
      </p>
      <SubscribedList channels={channels} onStatus={setStatus} />
      <section aria-labelledby="takeout-heading" className="flex flex-col gap-1">
        <h2 id="takeout-heading" className="font-medium">
          Already have a YouTube history?
        </h2>
        <p className="text-pretty text-muted-foreground">
          Export your watch history from Google Takeout (YouTube, History) and
          upload its <code>watch-history.json</code> or{" "}
          <code>watch-history.html</code> file in{" "}
          <Link to="/settings" className="underline">
            Import from Google Takeout
          </Link>
          . It can subscribe you to the channels you watch most.
        </p>
      </section>
      <div className="flex gap-2">
        <Button variant="secondary" size="lg" className="px-4" onClick={onBack}>
          Back
        </Button>
        <Button size="lg" className="px-5" onClick={onNext}>
          Next
        </Button>
      </div>
    </div>
  );
}

function useRefreshChannels() {
  const queryClient = useQueryClient();
  return () =>
    queryClient.invalidateQueries({ queryKey: channelsQuery.queryKey });
}

function ChannelSearch({
  subscribedIds,
  onStatus,
}: {
  subscribedIds: ReadonlySet<string>;
  onStatus: (message: string) => void;
}) {
  const [q, setQ] = useState("");
  const search = useMutation({
    mutationFn: (q: string) => searchChannels({ data: { q } }),
  });
  const outcome = search.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (q.trim()) search.mutate(q);
  }

  return (
    <section aria-labelledby="search-heading" className="flex flex-col gap-3">
      <h2 id="search-heading" className="text-lg font-semibold">
        Search for a channel
      </h2>
      <form role="search" onSubmit={onSubmit} className="flex gap-2">
        <Input
          type="search"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          aria-label="Channel name"
          placeholder="Woodworking, birdwatching, Veritasium…"
          maxLength={QUERY_MAX_LENGTH}
          required
          className="h-10 rounded-full px-4 text-base"
        />
        <Button
          type="submit"
          variant="secondary"
          size="lg"
          className="h-10 gap-2 px-4"
          disabled={search.isPending}
        >
          <SearchIcon />
          {search.isPending ? "Searching…" : "Search"}
        </Button>
      </form>
      {(search.isError || outcome?.ok === false) && (
        <p role="alert" className="text-destructive">
          {outcome?.ok === false
            ? outcome.message
            : "Couldn't search right now. Try again later."}
        </p>
      )}
      {outcome?.ok === true &&
        (outcome.channels.length === 0 ? (
          <p className="text-muted-foreground">
            No channels found. Try another name.
          </p>
        ) : (
          <ul className="flex flex-col divide-y" aria-label="Search results">
            {outcome.channels.map((hit) => (
              <ResultRow
                key={hit.channel_id}
                hit={hit}
                subscribed={subscribedIds.has(hit.channel_id)}
                onStatus={onStatus}
              />
            ))}
          </ul>
        ))}
    </section>
  );
}

function ResultRow({
  hit,
  subscribed,
  onStatus,
}: {
  hit: ChannelHit;
  subscribed: boolean;
  onStatus: (message: string) => void;
}) {
  const refresh = useRefreshChannels();
  const mutation = useMutation({
    mutationFn: () => subscribe({ data: { url: channelUrl(hit.channel_id) } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      onStatus(`Subscribed to ${result.channel.title}.`);
      await refresh();
    },
  });
  const failed =
    mutation.isError || (mutation.data !== undefined && !mutation.data.ok);

  return (
    <li className="flex flex-col gap-1 py-3">
      <div className="flex items-center gap-3">
        <ChannelAvatar url={null} title={hit.title} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{hit.title}</span>
          <span className="block truncate text-sm text-muted-foreground">
            {[hit.handle, `e.g. ${hit.sample_video}`]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
        <Button
          size="lg"
          className="px-4"
          variant={subscribed ? "secondary" : "default"}
          disabled={subscribed || mutation.isPending}
          aria-label={
            subscribed
              ? `Subscribed to ${hit.title}`
              : `Subscribe to ${hit.title}`
          }
          onClick={() => mutation.mutate()}
        >
          {subscribed
            ? "Subscribed"
            : mutation.isPending
              ? "Subscribing…"
              : "Subscribe"}
        </Button>
      </div>
      {failed && (
        <p role="alert" className="text-sm text-destructive">
          {mutation.data && !mutation.data.ok
            ? mutation.data.message
            : "Couldn't subscribe. Try again later."}
        </p>
      )}
    </li>
  );
}

function PasteLink({ onStatus }: { onStatus: (message: string) => void }) {
  const refresh = useRefreshChannels();
  const [url, setUrl] = useState("");
  const mutation = useMutation({
    mutationFn: (url: string) => subscribe({ data: { url } }),
    onSuccess: async (result) => {
      if (!result.ok) return;
      setUrl("");
      onStatus(
        result.created
          ? `Subscribed to ${result.channel.title}.`
          : `You're already subscribed to ${result.channel.title}.`,
      );
      await refresh();
    },
  });
  const result = mutation.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (url.trim()) mutation.mutate(url);
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <label htmlFor="channel-link" className="text-lg font-semibold">
        Paste a channel link
      </label>
      <div className="flex gap-2">
        <Input
          id="channel-link"
          type="text"
          inputMode="url"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://www.youtube.com/@channel"
          required
          aria-invalid={result?.ok === false}
          aria-describedby="channel-link-error"
          className="h-10 px-3 text-base"
        />
        <Button
          type="submit"
          variant="secondary"
          size="lg"
          className="h-10 px-4"
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Subscribing…" : "Subscribe"}
        </Button>
      </div>
      <p id="channel-link-error" role="alert" className="empty:hidden">
        {mutation.isError && (
          <span className="text-destructive">
            Couldn't subscribe. Try again later.
          </span>
        )}
        {result?.ok === false && (
          <span className="text-destructive">{result.message}</span>
        )}
      </p>
    </form>
  );
}

function SubscribedList({
  channels,
  onStatus,
}: {
  channels: SubscribedChannel[];
  onStatus: (message: string) => void;
}) {
  const refresh = useRefreshChannels();
  const remove = useMutation({
    mutationFn: (channel: SubscribedChannel) =>
      unsubscribe({ data: { channelId: channel.channel_id } }),
    onSuccess: async (_, channel) => {
      onStatus(`Removed ${channel.title}.`);
      await refresh();
    },
    onError: () => onStatus("Couldn't remove that channel. Try again later."),
  });

  return (
    <section aria-labelledby="subscribed-heading" className="flex flex-col gap-2">
      <h2 id="subscribed-heading" className="text-lg font-semibold">
        Your channels ({channels.length})
      </h2>
      {channels.length === 0 ? (
        <p className="text-muted-foreground">
          None yet. Search above or paste a link.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Your channels">
          {channels.map((channel) => (
            <li
              key={channel.channel_id}
              className="flex items-center gap-3 py-2"
            >
              <ChannelAvatar url={channel.thumbnail_url} title={channel.title} />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">
                  {channel.title}
                </span>
                {channel.handle && (
                  <span className="block truncate text-sm text-muted-foreground">
                    {channel.handle}
                  </span>
                )}
              </span>
              <Button
                variant="ghost"
                size="lg"
                className="px-3"
                disabled={remove.isPending}
                aria-label={`Remove ${channel.title}`}
                onClick={() => remove.mutate(channel)}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FinishStep({ onBack }: { onBack: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: channels } = useSuspenseQuery(channelsQuery);
  const build = useMutation({
    mutationFn: () => finishOnboarding(),
    onSuccess: async (feed) => {
      queryClient.setQueryData(todayFeedQuery.queryKey, feed);
      await queryClient.invalidateQueries({
        queryKey: onboardingQuery.queryKey,
      });
      await navigate({ to: "/" });
    },
  });

  return (
    <section className="flex flex-col gap-4">
      <p className="text-pretty">
        You've added {channelCount(channels.length)}. Homefeed will fetch their
        latest videos and put together today's feed.
      </p>
      {channels.length < THIN_FEED_CHANNELS && (
        <p className="text-pretty text-muted-foreground">
          That's a small start, so the feed will be short. Go back to add a few
          more, or build it now and add more any time.
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="lg"
          className="px-4"
          disabled={build.isPending}
          onClick={onBack}
        >
          Back
        </Button>
        <Button
          size="lg"
          className="px-5"
          disabled={build.isPending || channels.length === 0}
          onClick={() => build.mutate()}
        >
          {build.isPending ? "Building…" : "Build my feed"}
        </Button>
      </div>
      <p role="status" className="min-h-6">
        {build.isPending && (
          <span className="text-muted-foreground">
            Fetching videos from {channelCount(channels.length)}. This can take
            a moment.
          </span>
        )}
      </p>
      {build.isError && (
        <p role="alert" className="text-destructive">
          Couldn't build the feed. Try again, or skip setup and build it from
          the home page later.
        </p>
      )}
      {channels.length === 0 && (
        <p className="text-muted-foreground">
          Add at least one channel first.
        </p>
      )}
    </section>
  );
}
