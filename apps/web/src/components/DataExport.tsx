import { SettingsCard } from "#/components/SettingsCard";
import { buttonVariants } from "#/components/ui/button";
import { CardFooter } from "#/components/ui/card";
import { EXPORT_PATH } from "#/lib/export";
import { cn } from "#/lib/utils";

/** Download everything as one JSON file (see `routes/export[.]json.ts`). */
export function DataExport() {
  return (
    <SettingsCard
      id="export-heading"
      title="Export your data"
      description="Download your ratings, channels and subscriptions, feed history, watch history, queue, playlists and settings as one JSON file. Cached data such as embeddings and tags isn't included, and neither are API keys."
    >
      <CardFooter>
        <a
          href={EXPORT_PATH}
          download
          className={cn(buttonVariants({ size: "lg" }), "px-4")}
        >
          Download JSON
        </a>
      </CardFooter>
    </SettingsCard>
  );
}
