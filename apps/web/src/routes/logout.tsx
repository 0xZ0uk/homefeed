import { createFileRoute } from "@tanstack/react-router";

import { LOGIN_PATH, logOut } from "#/server/auth";

export const Route = createFileRoute("/logout")({
  server: {
    handlers: {
      POST: async () => {
        await logOut();
        return new Response(null, {
          status: 303,
          headers: { Location: LOGIN_PATH },
        });
      },
    },
  },
});
