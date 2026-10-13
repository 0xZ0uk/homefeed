import { Avatar, AvatarFallback, AvatarImage } from "#/components/ui/avatar";
import { cn } from "#/lib/utils";

/**
 * A channel's picture, or its initial in a muted circle when it has none or
 * it fails to load. yt3.googleusercontent.com answers 429 to requests that
 * carry a Referer, hence `no-referrer`.
 */
export function ChannelAvatar({
  url,
  title,
  className,
}: {
  url: string | null | undefined;
  title: string;
  className?: string;
}) {
  return (
    <Avatar aria-hidden="true" className={cn("size-10", className)}>
      {url && (
        <AvatarImage
          src={url}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
        />
      )}
      <AvatarFallback className="font-medium">
        {title.trim().charAt(0).toUpperCase()}
      </AvatarFallback>
    </Avatar>
  );
}
