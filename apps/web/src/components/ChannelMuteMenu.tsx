import { CalendarClock, ChevronDown, Eye, EyeOff } from "lucide-react";

import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import type { MuteState } from "#/lib/channels";

/**
 * A channel's mute as a menu: the button says whether it's muted, and the menu
 * offers what makes sense from there: Mute (for good), Mute for a month (it
 * comes back by itself) and Unmute.
 */
export function ChannelMuteMenu({
  title,
  state,
  disabled,
  onMute,
  onMuteForAMonth,
  onUnmute,
}: {
  /** The channel's title, to tell the menus of a list apart. */
  title: string;
  state: MuteState;
  disabled?: boolean;
  onMute: () => void;
  onMuteForAMonth: () => void;
  onUnmute: () => void;
}) {
  const label = state.kind === "off" ? "Mute" : "Muted";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="px-3"
            disabled={disabled}
            aria-label={`${label}: ${title}`}
          />
        }
      >
        {label}
        <ChevronDown />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        {state.kind !== "forever" && (
          <DropdownMenuItem onClick={onMute}>
            <EyeOff />
            Mute
          </DropdownMenuItem>
        )}
        {state.kind !== "until" && (
          <DropdownMenuItem onClick={onMuteForAMonth}>
            <CalendarClock />
            Mute for a month
          </DropdownMenuItem>
        )}
        {state.kind !== "off" && (
          <DropdownMenuItem onClick={onUnmute}>
            <Eye />
            Unmute
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
