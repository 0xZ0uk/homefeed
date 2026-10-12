import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({ component: Home });

function Home() {
  return (
    <main className="p-8">
      <h1 className="text-4xl font-bold">Homefeed</h1>
    </main>
  );
}
