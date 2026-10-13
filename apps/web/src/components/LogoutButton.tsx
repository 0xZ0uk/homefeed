import { LogOut } from "lucide-react";

import { Button } from "#/components/ui/button";

/** Ends the session. A plain form post so it works without client JS. */
export function LogoutButton() {
  return (
    <form method="post" action="/logout">
      <Button
        type="submit"
        variant="outline"
        className="h-9 gap-2 px-3 sm:pr-4"
        aria-label="Log out"
      >
        <LogOut />
        <span aria-hidden="true" className="hidden sm:inline">
          Log out
        </span>
      </Button>
    </form>
  );
}
