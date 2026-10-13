import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { formatLikes } from "#/lib/comments";
import { commentsQuery, type Comment } from "#/server/video-extras";

/**
 * The video's top comments, fetched only when asked for: nothing is loaded
 * from YouTube until "Show comments" is pressed.
 */
export function Comments({ videoId }: { videoId: string }) {
  const [shown, setShown] = useState(false);
  const comments = useQuery({ ...commentsQuery(videoId), enabled: shown });

  let body;
  if (!shown) {
    body = (
      <button
        type="button"
        className="self-start inline-flex h-9 items-center justify-center rounded-full bg-secondary px-4 text-sm font-medium hover:bg-accent disabled:opacity-50"
        onClick={() => setShown(true)}
      >
        Show comments
      </button>
    );
  } else if (comments.isPending) {
    body = <p role="status">Loading comments…</p>;
  } else if (comments.isError) {
    body = (
      <p role="alert" className="text-destructive">
        Couldn't load comments
        {comments.error.message ? `: ${comments.error.message}` : ""}.{" "}
        <button
          type="button"
          className="underline"
          onClick={() => void comments.refetch()}
        >
          Try again
        </button>
      </p>
    );
  } else if (comments.data.length === 0) {
    body = (
      <p className="text-muted-foreground">
        No comments, or they're turned off.
      </p>
    );
  } else {
    body = (
      <ol className="flex flex-col gap-2" aria-label="Top comments">
        {comments.data.map((comment) => (
          <CommentItem key={comment.id} comment={comment} />
        ))}
      </ol>
    );
  }

  return (
    <section aria-labelledby="comments-heading" className="flex flex-col gap-4">
      <h3 id="comments-heading" className="text-xl font-bold">
        Comments
      </h3>
      {body}
    </section>
  );
}

function CommentItem({ comment }: { comment: Comment }) {
  const details = [
    comment.published_text,
    formatLikes(comment.like_count),
    comment.is_hearted ? "hearted by the creator" : null,
  ].filter(Boolean);

  const author = comment.author || "Unknown";

  return (
    <li className="flex gap-4 py-2">
      <span
        aria-hidden="true"
        className="flex size-10 shrink-0 items-center justify-center rounded-full bg-secondary font-medium"
      >
        {author.replace(/^@/, "").charAt(0).toUpperCase()}
      </span>
      <div className="flex min-w-0 flex-col gap-1">
        <p className="text-[0.8125rem]">
          {comment.is_pinned && (
            <span className="mr-2 text-muted-foreground">Pinned</span>
          )}
          <strong
            className={
              comment.author_is_uploader
                ? "rounded-full bg-accent px-1.5 py-0.5 font-medium"
                : "font-medium"
            }
          >
            {author}
          </strong>
          {comment.author_is_uploader && (
            <span className="sr-only"> (creator)</span>
          )}
          {details.length > 0 && (
            <span className="text-muted-foreground">
              {" "}
              · {details.join(" · ")}
            </span>
          )}
        </p>
        <p className="text-sm whitespace-pre-line break-words">
          {comment.text}
        </p>
      </div>
    </li>
  );
}
