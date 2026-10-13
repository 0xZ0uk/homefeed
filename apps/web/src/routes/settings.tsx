import { createFileRoute } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { DataExport } from "#/components/DataExport";
import { HiddenChannels } from "#/components/HiddenChannels";
import { TakeoutImport } from "#/components/TakeoutImport";
import { UserSettings } from "#/components/UserSettings";
import { channelHidesQuery } from "#/server/channel-hides";
import { settingsQuery } from "#/server/settings";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "Settings · Homefeed" }] }),
  loader: ({ context: { queryClient } }) =>
    Promise.all([
      queryClient.ensureQueryData(settingsQuery),
      queryClient.ensureQueryData(channelHidesQuery),
    ]),
  component: Settings,
});

function Settings() {
  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h2 className="text-xl font-semibold">Settings</h2>
      <UserSettings />
      <TakeoutImport />
      <HiddenChannels />
      <DataExport />
    </AppShell>
  );
}
