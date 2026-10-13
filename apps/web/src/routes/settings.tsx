import { createFileRoute } from "@tanstack/react-router";

import { AppShell } from "#/components/AppShell";
import { DataExport } from "#/components/DataExport";
import { TakeoutImport } from "#/components/TakeoutImport";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "Settings · Homefeed" }] }),
  component: Settings,
});

function Settings() {
  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <h2 className="text-xl font-semibold">Settings</h2>
      <TakeoutImport />
      <DataExport />
    </AppShell>
  );
}
