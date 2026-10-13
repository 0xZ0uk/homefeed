import { createFileRoute } from "@tanstack/react-router";

import { logIn, safeRedirectTarget } from "#/server/auth";

interface LoginSearch {
  redirect?: string;
  error?: boolean;
}

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: typeof search.redirect === "string" ? search.redirect : undefined,
    error: search.error === true ? true : undefined,
  }),
  head: () => ({ meta: [{ title: "Log in · Homefeed" }] }),
  server: {
    handlers: {
      // A plain form post, so logging in works before the client hydrates.
      POST: async ({ request }) => {
        const form = await request.formData();
        const password = form.get("password");
        const target = safeRedirectTarget(form.get("redirect"));

        if (typeof password === "string" && (await logIn(password))) {
          return seeOther(target);
        }
        // Matches how the router serializes `LoginSearch`, so it doesn't
        // redirect to a normalized URL.
        const params = new URLSearchParams({ error: "true" });
        if (target !== "/") params.set("redirect", target);
        return seeOther(`/login?${params}`);
      },
    },
  },
  component: Login,
});

function seeOther(location: string) {
  return new Response(null, { status: 303, headers: { Location: location } });
}

function Login() {
  const { redirect, error } = Route.useSearch();

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <form method="post" className="flex w-full max-w-xs flex-col gap-4">
        <h1 className="text-2xl font-bold">Homefeed</h1>
        <label className="flex flex-col gap-1">
          <span>Password</span>
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
            autoFocus
            aria-invalid={error}
            aria-describedby={error ? "login-error" : undefined}
            className="rounded-lg border border-input bg-transparent outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 px-3 py-2"
          />
        </label>
        {error && (
          <p id="login-error" role="alert" className="text-destructive">
            Wrong password. Try again.
          </p>
        )}
        {redirect && <input type="hidden" name="redirect" value={redirect} />}
        <button
          type="submit"
          className="inline-flex items-center justify-center rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/85"
        >
          Log in
        </button>
      </form>
    </main>
  );
}
