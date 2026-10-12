import { health } from "@homefeed/api-client";
import { queryOptions, useSuspenseQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { createServerFn } from "@tanstack/react-start";

import { apiClient } from "#/server/api";

const getHealth = createServerFn({ method: "GET" }).handler(async () => {
  const { data } = await health({ client: apiClient(), throwOnError: true });
  return data;
});

const healthQuery = queryOptions({
  queryKey: ["health"],
  queryFn: () => getHealth(),
});

export const Route = createFileRoute("/")({
  loader: ({ context }) => context.queryClient.ensureQueryData(healthQuery),
  component: Home,
  errorComponent: () => <ApiStatus status="unreachable" />,
});

function Home() {
  const { data } = useSuspenseQuery(healthQuery);
  return <ApiStatus status={data.status} />;
}

function ApiStatus({ status }: { status: string }) {
  return (
    <main className="p-8">
      <h1 className="text-4xl font-bold">Homefeed</h1>
      <p className="mt-4">API: {status}</p>
    </main>
  );
}
