import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { DEFAULT_WEEK_RANGE } from "#/lib/insights";
import { describeModel, type Taste } from "#/lib/taste";
import { modelsQuery } from "#/server/models";

const LINK =
  "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

/**
 * Where the ranking model stands: the active version and when it was trained,
 * or, before there is one, how far your ratings are from training the first.
 * It is the model that learns from your ratings; the Models page lists every
 * version and rolls back.
 */
export function TasteModel({ taste }: { taste: Taste }) {
  const { data: versions, isError, refetch } = useQuery(modelsQuery);

  return (
    <section aria-labelledby="model-heading" className="flex flex-col gap-2">
      <h2 id="model-heading" className="text-lg font-semibold">
        Model
      </h2>
      {isError ? (
        <div role="alert" className="flex flex-col items-start gap-2 text-sm">
          <p>Couldn't load the model's status. The API may be down.</p>
          <button type="button" onClick={() => void refetch()} className={LINK}>
            Try again
          </button>
        </div>
      ) : versions === undefined ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <p className="max-w-prose text-pretty">
          {describeModel(
            versions,
            taste.signals.ratings,
            taste.min_ratings_to_train,
          )}
        </p>
      )}
      <p className="text-sm">
        <Link to="/models" className={LINK}>
          Open Models
        </Link>{" "}
        to see every version and roll back.{" "}
        <Link
          to="/insights"
          search={{ weeks: DEFAULT_WEEK_RANGE }}
          className={LINK}
        >
          Open Insights
        </Link>{" "}
        to see how well the feed is working.
      </p>
    </section>
  );
}
