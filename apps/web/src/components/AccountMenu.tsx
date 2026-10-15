import { Link, getRouteApi } from "@tanstack/react-router";
import { Activity, LogOut, Settings, UserRound } from "lucide-react";

import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLinkItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";

const rootRoute = getRouteApi("__root__");

/**
 * The account menu at the end of the masthead: a round button that opens
 * Settings, Status and Log out, so the masthead keeps one control for the
 * things you rarely need.
 *
 * Log out is a plain form post (the menu item submits a form that sits beside
 * the menu, so it survives the menu closing). In desktop mode it's left out:
 * the session comes from the shell and can't be restored from a login page.
 */
export function AccountMenu() {
  const mode = rootRoute.useLoaderData();
  const canLogOut = mode !== "desktop";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="secondary"
              size="icon-lg"
              aria-label="Account menu"
            />
          }
        >
          <UserRound className="size-5" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56 py-2">
          <DropdownMenuLinkItem
            render={<Link to="/settings" />}
            className="px-3 py-2"
          >
            <Settings />
            Settings
          </DropdownMenuLinkItem>
          <DropdownMenuLinkItem
            render={<Link to="/status" />}
            className="px-3 py-2"
          >
            <Activity />
            Status
          </DropdownMenuLinkItem>
          {canLogOut && (
            <>
              <DropdownMenuSeparator className="my-2" />
              <DropdownMenuItem
                nativeButton
                render={<button type="submit" form="logout-form" />}
                className="px-3 py-2"
              >
                <LogOut />
                Log out
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {canLogOut && <form id="logout-form" method="post" action="/logout" />}
    </>
  );
}
