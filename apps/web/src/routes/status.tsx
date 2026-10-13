import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppHeader } from "#/components/AppHeader";
import { formatPercent } from "#/lib/insights";
import { formatTimestamp } from "#/lib/models";
import {
  STATUS_WINDOWS,
  formatAgo,
  formatMilliseconds,
  healthBadgeClass,
  healthLabel,
  healthSummary,
  operationLabel,
  parseStatusHours,
  type ExtractorHealth,
} from "#/lib/status";
import {
  extractorStatusQuery,
  type FailedEvent,
  type OperationStatus,
  type SmokeTestRun,
} from "#/server/status";

interface StatusSearch {
  hours?: number;
}

/** Extraction health: how requests to YouTube have been going, per operation. */
export const Route = createFileRoute("/status")({
  validateSearch: (search: Record<string, unknown>): StatusSearch =>
    search.hours === undefined ? {} : { hours: parseStatusHours(search.hours) },
  head: () => ({ meta: [{ title: "Status · Homefeed" }] }),
  loaderDeps: ({ search }) => ({ hours: parseStatusHours(search.hours) }),
  loader: ({ context, deps }) =>
    context.queryClient.ensureQueryData(extractorStatusQuery(deps.hours)),
  component: Status,
  errorComponent: StatusError,
});

function Status() {
  const { hours } = Route.useLoaderDeps();
  const { data } = useSuspenseQuery(extractorStatusQuery(hours));

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 p-8">
      <AppHeader />
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-4">
          <h2 className="text-xl font-semibold">Extractor status</h2>
          <nav aria-label="Time window" className="flex gap-3 text-sm">
            {STATUS_WINDOWS.map((window) => (
              <Link
                key={window.hours}
                to="/status"
                search={{ hours: window.hours }}
                aria-current={window.hours === hours ? "page" : undefined}
                className="underline aria-[current=page]:font-medium aria-[current=page]:no-underline"
              >
                {window.label}
              </Link>
            ))}
          </nav>
        </div>
        <p role="status" className="flex flex-wrap items-center gap-2">
          <HealthBadge health={data.health} />
          <span>{healthSummary(data.health)}</span>
        </p>
      </div>

      <SmokeTest run={data.last_smoke_test} />
      <Operations operations={data.operations} />
      <RecentFailures failures={data.recent_failures} />
    </main>
  );
}

function HealthBadge({ health }: { health: ExtractorHealth }) {
  return (
    <span
      className={`rounded px-2 py-0.5 text-xs font-medium ${healthBadgeClass(health)}`}
    >
      {healthLabel(health)}
    </span>
  );
}

/** A relative time ("5 min ago") with the absolute one on hover. Relative to
 * the clock where it renders, so it may differ by a minute after hydration. */
function Ago({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <>–</>;
  return (
    <time dateTime={iso} title={formatTimestamp(iso)} suppressHydrationWarning>
      {formatAgo(iso)}
    </time>
  );
}

function SmokeTest({ run }: { run: SmokeTestRun | null }) {
  return (
    <section aria-labelledby="smoke-heading" className="flex flex-col gap-2">
      <h3 id="smoke-heading" className="text-lg font-semibold">
        Live smoke test
      </h3>
      {run ? (
        <div className="flex flex-col gap-1 rounded border border-gray-200 p-4">
          <p className="flex flex-wrap items-center gap-2">
            <HealthBadge health={run.success ? "ok" : "failing"} />
            <span>
              {run.success ? "Passed" : "Failed"} <Ago iso={run.at} />, in{" "}
              {formatMilliseconds(run.duration_ms)}.
            </span>
          </p>
          {run.error && (
            <p className="text-sm break-words text-red-700">{run.error}</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-600">
          Never run. Set <code>GATEWAY_SMOKE_TEST_TIME</code> (e.g.{" "}
          <code>05:30</code>) for the worker to check every Gateway operation
          against YouTube once a day.
        </p>
      )}
    </section>
  );
}

function Operations({ operations }: { operations: OperationStatus[] }) {
  return (
    <section
      aria-labelledby="operations-heading"
      className="flex flex-col gap-2"
    >
      <h3 id="operations-heading" className="text-lg font-semibold">
        Operations
      </h3>
      {operations.length === 0 ? (
        <p className="text-sm text-gray-600">No requests in this window.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-gray-600">
              <tr>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Operation
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Health
                </th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">
                  Requests
                </th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">
                  Succeeded
                </th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">
                  Avg time
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Last success
                </th>
                <th scope="col" className="py-2 font-medium">
                  Last failure
                </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {operations.map((op) => (
                <tr key={op.operation}>
                  <th scope="row" className="py-2 pr-4 font-normal">
                    {operationLabel(op.operation)}
                  </th>
                  <td className="py-2 pr-4">
                    <HealthBadge health={op.health} />
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {op.total}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {formatPercent(op.success_rate)}
                  </td>
                  <td className="py-2 pr-4 text-right tabular-nums">
                    {formatMilliseconds(op.avg_duration_ms)}
                  </td>
                  <td className="py-2 pr-4">
                    <Ago iso={op.last_success_at} />
                  </td>
                  <td className="py-2" title={op.last_error ?? undefined}>
                    <Ago iso={op.last_failure_at} />
                    {op.last_error_kind && (
                      <span className="text-gray-600">
                        {" "}
                        ({op.last_error_kind})
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="text-xs text-gray-600">
        Failures about the video or channel itself (removed, private, a URL that
        isn&apos;t YouTube&apos;s) don&apos;t count against an operation&apos;s
        health.
      </p>
    </section>
  );
}

function RecentFailures({ failures }: { failures: FailedEvent[] }) {
  return (
    <section aria-labelledby="failures-heading" className="flex flex-col gap-2">
      <h3 id="failures-heading" className="text-lg font-semibold">
        Recent failures
      </h3>
      {failures.length === 0 ? (
        <p className="text-sm text-gray-600">No failures in this window.</p>
      ) : (
        <ul className="flex flex-col divide-y text-sm">
          {failures.map((failure) => (
            <li key={failure.id} className="flex flex-col gap-0.5 py-2">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-medium">
                  {operationLabel(failure.operation)}
                </span>
                {failure.target && (
                  <code className="text-xs break-all">{failure.target}</code>
                )}
                <span className="text-gray-600">
                  {failure.error_kind ?? "error"}
                  {!failure.breakage && " (not the extractor's fault)"}
                  {failure.attempts > 1 && `, ${failure.attempts} attempts`}
                </span>
                <span className="ml-auto text-gray-600">
                  <Ago iso={failure.at} />
                </span>
              </div>
              {failure.error && (
                <p className="break-words text-gray-700">{failure.error}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StatusError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <main className="mx-auto max-w-4xl p-8">
      <AppHeader />
      <div role="alert" className="mt-8 flex flex-col items-start gap-3">
        <p>Couldn&apos;t load the extractor status. The API may be down.</p>
        <button
          type="button"
          onClick={() => void router.invalidate()}
          className="underline"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
