import { createFileRoute } from "@tanstack/react-router";

import { AppHeader } from "#/components/AppHeader";
import { DataExport } from "#/components/DataExport";
import { TakeoutImport } from "#/components/TakeoutImport";

export const Route = createFileRoute("/settings")({
  head: () => ({ meta: [{ title: "Settings · Homefeed" }] }),
  component: Settings,
});

function Settings() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 p-8">
      <AppHeader />
      <h2 className="text-xl font-semibold">Settings</h2>
      <TakeoutImport />
      <DataExport />
    </main>
  );
}
