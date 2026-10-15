import { useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Sparkles } from "lucide-react";

import { ActionStatusLine, useActionStatus } from "#/components/ActionStatus";
import { AppShell } from "#/components/AppShell";
import { TasteChannels } from "#/components/TasteChannels";
import { TasteModel } from "#/components/TasteModel";
import { TasteSignals } from "#/components/TasteSignals";
import { TasteTopics } from "#/components/TasteTopics";
import { Card } from "#/components/ui/card";
import { summarizeTaste } from "#/lib/taste";
import { channelHealthQuery, channelsQuery } from "#/server/channels";
import { modelsQuery } from "#/server/models";
import { tasteQuery } from "#/server/taste";

/**
 * What the app believes about you, and how to change it: a few sentences of
 * summary, then your topics (with their boosts), channels, signals and model.
 * The knowledge used to be spread over Subscriptions, the tag pages, Insights
 * and Models.
 */
export const Route = createFileRoute("/taste")({
  head: () => ({ meta: [{ title: "Your taste · Homefeed" }] }),
  loader: async ({ context: { queryClient } }) => {
    await Promise.all([
      queryClient.ensureQueryData(tasteQuery),
      // The rest only fills in the channels and the model: the page copes
      // without it if the API fails to give it.
      queryClient.ensureQueryData(channelsQuery).catch(() => {}),
      queryClient.ensureQueryData(channelHealthQuery).catch(() => {}),
      queryClient.ensureQueryData(modelsQuery).catch(() => {}),
    ]);
  },
  component: TastePage,
});

function TastePage() {
  const { data: taste } = useSuspenseQuery(tasteQuery);
  const { status, announce, ref: statusRef } = useActionStatus();

  return (
    <AppShell className="flex max-w-4xl flex-col gap-10">
      <header className="flex flex-col gap-1 pt-2">
        <h1 className="text-xl font-semibold">Your taste</h1>
        <p className="max-w-prose text-pretty text-muted-foreground">
          What Homefeed has learned from the topics you follow, the channels you
          rate and what you dismiss, and how to change it.
        </p>
      </header>
      <Card className="flex-row items-start gap-3 bg-accent p-4">
        <Sparkles
          aria-hidden="true"
          className="mt-1 size-4 shrink-0 text-brand"
        />
        <p className="max-w-prose min-w-0 leading-relaxed text-pretty">
          {summarizeTaste(taste).join(" ")}
        </p>
      </Card>
      {/* Hangs under the masthead once the page is scrolled to it, so what a
          change did (and its Undo) is in view wherever you are; at the top
          of the page it sits where the topics begin, not over the title.
          Focus moves here when the row that was used is gone. It takes no
          room: the margin cancels the gap. */}
      <div className="sticky top-14 z-30 -mb-10 h-0">
        <ActionStatusLine
          status={status}
          statusRef={statusRef}
          className="absolute top-2 left-0 max-w-full"
        />
      </div>
      <TasteTopics taste={taste} announce={announce} />
      <TasteChannels taste={taste} announce={announce} />
      <TasteSignals taste={taste} />
      <TasteModel taste={taste} />
    </AppShell>
  );
}
