import {
  useQueryErrorResetBoundary,
  useSuspenseQuery,
} from "@tanstack/react-query";
import { Link, createFileRoute, useRouter } from "@tanstack/react-router";
import {
  CircleCheck,
  CircleDashed,
  CircleX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "#/components/AppShell";
import { Badge } from "#/components/ui/badge";
import { buttonVariants } from "#/components/ui/button";
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
import { cn } from "#/lib/utils";
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
    <AppShell className="flex max-w-5xl flex-col gap-10">
      <header className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <h2 className="text-xl font-semibold">Extractor status</h2>
          <nav aria-label="Time window" className="flex gap-2">
            {STATUS_WINDOWS.map((window) => (
              <Link
                key={window.hours}
                to="/status"
                search={{ hours: window.hours }}
                aria-current={window.hours === hours ? "page" : undefined}
                className={cn(
                  buttonVariants({ variant: "secondary", size: "lg" }),
                  "rounded-lg px-3 aria-[current=page]:bg-primary aria-[current=page]:text-primary-foreground",
                )}
              >
                {window.label}
              </Link>
            ))}
          </nav>
        </div>
        <p
          role="status"
          className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border p-4"
        >
          <HealthBadge health={data.health} />
          <span className="text-pretty">{healthSummary(data.health)}</span>
        </p>
      </header>

      <SmokeTest run={data.last_smoke_test} />
      <Operations operations={data.operations} />
      <RecentFailures failures={data.recent_failures} />
    </AppShell>
  );
}

const HEALTH_ICONS: Record<ExtractorHealth, LucideIcon> = {
  ok: CircleCheck,
  degraded: TriangleAlert,
  failing: CircleX,
  unknown: CircleDashed,
};

function HealthBadge({ health }: { health: ExtractorHealth }) {
  const Icon = HEALTH_ICONS[health];
  return (
    <Badge className={cn("rounded-md", healthBadgeClass(health))}>
      <Icon aria-hidden="true" />
      {healthLabel(health)}
    </Badge>
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

/** A titled part of the page. */
function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h3 id={id} className="text-lg font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

function SmokeTest({ run }: { run: SmokeTestRun | null }) {
  return (
    <Section id="smoke-heading" title="Live smoke test">
      {run ? (
        <div className="flex flex-col gap-2 rounded-xl border p-4">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <HealthBadge health={run.success ? "ok" : "failing"} />
            <span>
              {run.success ? "Passed" : "Failed"} <Ago iso={run.at} />, in{" "}
              {formatMilliseconds(run.duration_ms)}.
            </span>
          </p>
          {run.error && (
            <p className="text-sm break-words text-destructive">{run.error}</p>
          )}
        </div>
      ) : (
        <p className="max-w-prose text-sm text-pretty text-muted-foreground">
          Never run. Set <code>GATEWAY_SMOKE_TEST_TIME</code> (e.g.{" "}
          <code>05:30</code>) for the worker to check every Gateway operation
          against YouTube once a day.
        </p>
      )}
    </Section>
  );
}

function Operations({ operations }: { operations: OperationStatus[] }) {
  return (
    <Section id="operations-heading" title="Operations">
      {operations.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No requests in this window.
        </p>
      ) : (
        <>
          <OperationsTable operations={operations} />
          <OperationsList operations={operations} />
        </>
      )}
      <p className="max-w-prose text-sm text-pretty text-muted-foreground">
        Failures about the video or channel itself (removed, private, a URL that
        isn&apos;t YouTube&apos;s) don&apos;t count against an operation&apos;s
        health.
      </p>
    </Section>
  );
}

function LastFailure({ op }: { op: OperationStatus }) {
  return (
    <>
      <Ago iso={op.last_failure_at} />
      {op.last_error_kind && (
        <span
          className="text-muted-foreground"
          title={op.last_error ?? undefined}
        >
          {" "}
          ({op.last_error_kind})
        </span>
      )}
    </>
  );
}

/** The operations as a table, from the `sm` breakpoint up. */
function OperationsTable({ operations }: { operations: OperationStatus[] }) {
  const head = "py-2 pr-4 font-medium last:pr-0";
  const number = "py-2.5 pr-4 text-right tabular-nums";
  return (
    <div className="hidden overflow-x-auto sm:block">
      <table className="w-full text-left text-sm">
        <thead className="border-b text-muted-foreground">
          <tr>
            <th scope="col" className={head}>
              Operation
            </th>
            <th scope="col" className={head}>
              Health
            </th>
            <th scope="col" className={cn(head, "text-right")}>
              Requests
            </th>
            <th scope="col" className={cn(head, "text-right")}>
              Succeeded
            </th>
            <th scope="col" className={cn(head, "text-right")}>
              Avg time
            </th>
            <th scope="col" className={head}>
              Last success
            </th>
            <th scope="col" className={head}>
              Last failure
            </th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {operations.map((op) => (
            <tr key={op.operation}>
              <th scope="row" className="py-2.5 pr-4 font-medium">
                {operationLabel(op.operation)}
              </th>
              <td className="py-2.5 pr-4">
                <HealthBadge health={op.health} />
              </td>
              <td className={number}>{op.total}</td>
              <td className={number}>{formatPercent(op.success_rate)}</td>
              <td className={cn(number, "whitespace-nowrap")}>
                {formatMilliseconds(op.avg_duration_ms)}
              </td>
              <td className="py-2.5 pr-4 whitespace-nowrap">
                <Ago iso={op.last_success_at} />
              </td>
              <td className="py-2.5 whitespace-nowrap">
                <LastFailure op={op} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The operations as a list, below the `sm` breakpoint, where the table
 * would need scrolling sideways. */
function OperationsList({ operations }: { operations: OperationStatus[] }) {
  return (
    <ul className="flex flex-col divide-y sm:hidden" aria-label="Operations">
      {operations.map((op) => (
        <li key={op.operation} className="flex flex-col gap-2 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium">{operationLabel(op.operation)}</span>
            <HealthBadge health={op.health} />
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <Metric label="Succeeded">
              {formatPercent(op.success_rate)} of {op.total}
            </Metric>
            <Metric label="Avg time">
              {formatMilliseconds(op.avg_duration_ms)}
            </Metric>
            <Metric label="Last success">
              <Ago iso={op.last_success_at} />
            </Metric>
            <Metric label="Last failure">
              <LastFailure op={op} />
            </Metric>
          </dl>
        </li>
      ))}
    </ul>
  );
}

function Metric({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{children}</dd>
    </div>
  );
}

function RecentFailures({ failures }: { failures: FailedEvent[] }) {
  return (
    <Section id="failures-heading" title="Recent failures">
      {failures.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No failures in this window.
        </p>
      ) : (
        <ul className="flex flex-col divide-y text-sm">
          {failures.map((failure) => (
            <li key={failure.id} className="flex flex-col gap-1 py-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">
                  {operationLabel(failure.operation)}
                </span>
                <span className="shrink-0 text-muted-foreground">
                  <Ago iso={failure.at} />
                </span>
              </div>
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-muted-foreground">
                {failure.target && (
                  <code className="rounded bg-secondary px-1.5 py-0.5 text-xs break-all text-foreground">
                    {failure.target}
                  </code>
                )}
                <span>
                  {failure.error_kind ?? "error"}
                  {!failure.breakage && " (not the extractor's fault)"}
                  {failure.attempts > 1 && `, ${failure.attempts} attempts`}
                </span>
              </div>
              {failure.error && (
                <p className="break-words text-muted-foreground">
                  {failure.error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function StatusError() {
  const router = useRouter();
  const queryErrorResetBoundary = useQueryErrorResetBoundary();

  useEffect(() => {
    queryErrorResetBoundary.reset();
  }, [queryErrorResetBoundary]);

  return (
    <AppShell className="max-w-5xl">
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
    </AppShell>
  );
}
