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
        className="self-start underline"
        onClick={() => setShown(true)}
      >
        Show comments
      </button>
    );
  } else if (comments.isPending) {
    body = <p role="status">Loading comments…</p>;
  } else if (comments.isError) {
    body = (
      <p role="alert" className="text-red-700">
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
    body = <p className="text-gray-600">No comments, or they're turned off.</p>;
  } else {
    body = (
      <ol className="flex flex-col divide-y" aria-label="Top comments">
        {comments.data.map((comment) => (
          <CommentItem key={comment.id} comment={comment} />
        ))}
      </ol>
    );
  }

  return (
    <section aria-labelledby="comments-heading" className="flex flex-col gap-2">
      <h3 id="comments-heading" className="text-lg font-semibold">
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

  return (
    <li className="flex flex-col gap-1 py-3">
      <p className="text-sm">
        {comment.is_pinned && (
          <span className="mr-2 text-gray-600">Pinned</span>
        )}
        <strong className="font-semibold">{comment.author || "Unknown"}</strong>
        {comment.author_is_uploader && (
          <span className="ml-2 rounded bg-gray-200 px-1 text-xs">Creator</span>
        )}
        {details.length > 0 && (
          <span className="text-gray-600"> · {details.join(" · ")}</span>
        )}
      </p>
      <p className="whitespace-pre-line break-words text-gray-800">
        {comment.text}
      </p>
    </li>
  );
}
