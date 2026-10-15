import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import { Button } from "#/components/ui/button";
import { AppShell } from "#/components/AppShell";
import { formatKind, formatMetric, formatTimestamp } from "#/lib/models";
import {
  activateModelVersion,
  modelsQuery,
  type ModelVersion,
} from "#/server/models";

export const Route = createFileRoute("/models")({
  head: () => ({ meta: [{ title: "Models · Homefeed" }] }),
  loader: ({ context }) => context.queryClient.ensureQueryData(modelsQuery),
  component: Models,
});

function Models() {
  const { data: versions } = useSuspenseQuery(modelsQuery);

  return (
    <AppShell className="flex max-w-4xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-xl font-semibold">Ranking models</h1>
        <p className="text-muted-foreground">
          A new model is trained each night on your ratings and becomes active
          only if it ranks the newest ratings about as well as the current one.
          Activate an earlier version to roll back; the next feed is ranked with
          it.
        </p>
      </div>
      {versions.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-muted-foreground">
          No models yet. The first is trained once you've rated enough videos;
          until then the feed is ranked by your subscriptions alone.
        </p>
      ) : (
        <ul className="flex flex-col divide-y" aria-label="Model versions">
          {versions.map((version) => (
            <ModelRow key={version.id} version={version} />
          ))}
        </ul>
      )}
    </AppShell>
  );
}

function ModelRow({ version }: { version: ModelVersion }) {
  const queryClient = useQueryClient();
  const activate = useMutation({
    mutationFn: () => activateModelVersion({ data: { id: version.id } }),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: modelsQuery.queryKey }),
  });
  const failure = activate.isError
    ? "Couldn't activate that model. Try again later."
    : activate.data?.ok === false
      ? activate.data.message
      : null;
  const holdout = version.holdout_size;

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 className="flex items-baseline gap-2 font-medium">
          Version {version.id}
          <span className="text-sm font-normal text-muted-foreground">
            {formatKind(version.kind)}
          </span>
          {version.active && (
            <span className="rounded bg-success/15 px-2 py-0.5 text-xs font-medium text-success">
              Active
            </span>
          )}
        </h2>
        {!version.active &&
          (version.compatible ? (
            <Button
              type="button"
              variant="secondary"
              size="lg"
              disabled={activate.isPending}
              onClick={() => activate.mutate()}
              aria-label={`Activate version ${version.id}`}
              className="px-4"
            >
              {activate.isPending ? "Activating…" : "Activate"}
            </Button>
          ) : (
            <span className="text-sm text-muted-foreground">
              Trained with older features; can't be activated
            </span>
          ))}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <Metric label="Spearman" value={formatMetric(version.spearman)} />
        <Metric label="MAE" value={formatMetric(version.mae)} />
        <Metric label="Trained" value={formatTimestamp(version.created_at)} />
        <Metric
          label="Activated"
          value={formatTimestamp(version.activated_at)}
        />
      </dl>
      {holdout !== null && (
        <p className="text-xs text-muted-foreground">
          Metrics on the newest {holdout} rating{holdout === 1 ? "" : "s"}, held
          out from training.
        </p>
      )}
      {failure && (
        <p role="alert" className="text-sm text-destructive">
          {failure}
        </p>
      )}
    </li>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}
