import { EllipsisVertical, EyeOff } from "lucide-react";

import { CardActions, RateButton, useLater } from "#/components/CardActions";
import { useFeedActions } from "#/components/use-feed-actions";
import { VideoCard } from "#/components/VideoCard";
import { Button } from "#/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import type { ActionStatus } from "#/lib/card-actions";
import { DISMISS_GROUP_LABEL, DISMISS_REASONS } from "#/lib/dismiss";
import type { FeedItem } from "#/server/feeds";

/**
 * One feed item as a card: its reason, chips and quick actions (see
 * `VideoCard`), a button to rate it once it's watched, and (in a feed that
 * can be dismissed from) a menu to dismiss it.
 */
export function FeedCard({
  item,
  now,
  actions,
  announce,
  dismissible,
}: {
  item: FeedItem;
  now: Date;
  actions: ReturnType<typeof useFeedActions>;
  announce: (status: ActionStatus) => void;
  dismissible: boolean;
}) {
  const queue = useLater(item, announce);

  return (
    <VideoCard
      video={item}
      now={now}
      menu={
        dismissible && (
          <CardMenu
            title={item.title}
            onDismiss={(reason) => actions.dismiss(item, reason)}
          />
        )
      }
      rate={
        <RateButton
          title={item.title}
          rating={item.rating}
          onRate={(score) => actions.rate(item, score)}
        />
      }
      actions={
        <CardActions
          title={item.title}
          feedback={item.feedback}
          onFeedback={(pressed) => actions.toggleFeedback(item, pressed)}
          queue={queue}
        />
      }
    />
  );
}

/**
 * A card's "more actions" menu: the ways to dismiss it, grouped as "Not for
 * me", with or without a reason.
 */
function CardMenu({
  title,
  onDismiss,
}: {
  title: string;
  onDismiss: (reason: string | null) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            className="relative z-10 -mt-1 -mr-2"
          />
        }
        aria-label={`More actions for ${title}`}
      >
        <EllipsisVertical className="size-5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 py-2">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="px-3">
            {DISMISS_GROUP_LABEL}
          </DropdownMenuLabel>
          {DISMISS_REASONS.map((reason) => (
            <DropdownMenuItem
              key={reason}
              onClick={() => onDismiss(reason)}
              className="px-3 py-2"
            >
              <EyeOff />
              {reason}
            </DropdownMenuItem>
          ))}
          <DropdownMenuItem
            onClick={() => onDismiss(null)}
            className="px-3 py-2 pl-9.5 text-muted-foreground"
          >
            No reason
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
