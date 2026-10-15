import { useRef, useState } from "react";

import type { ActionStatus } from "#/lib/card-actions";

/** What is being done to which row, for the words on its button. */
export interface Pending<Action extends string> {
  /** The row: a topic's slug, a channel's id. */
  key: string;
  action: Action;
}

/** A failure with something to tell the person, as opposed to a broken request. */
export class ChangeFailed extends Error {}

interface Running<Action extends string> {
  /** Changes asked for and not finished, the one running among them. */
  count: number;
  /** The one running, or the first one asked for until it starts. */
  current: Pending<Action> | null;
}

/**
 * Runs the changes a list's rows offer, for the Taste page. `perform` does a
 * change's work and says what happened through `announce`, with the Undo the
 * work asks for, or, if it failed, so, with the message of a `ChangeFailed` or
 * else `failure`. It says so at once and then refreshes what shows the data
 * (`refresh`): after a failure too, since part of the work may have been
 * saved, but then without holding things up, as the refresh is likely to fail
 * and retry as well, and the person wants to try again.
 *
 * Changes run one after the other, in the order they were asked for, so none is
 * lost and the last one wins: a slider moved again while its last position is
 * still being saved is saved too. `pending` says which is running (null when
 * none is), for rows to hold their buttons still. Undo closures made with
 * `perform` don't depend on the row they came from, which is often gone by the
 * time they are used.
 */
export function useChanges<Action extends string>(
  announce: (status: ActionStatus) => void,
  refresh: () => Promise<unknown>,
) {
  const [running, setRunning] = useState<Running<Action>>({
    count: 0,
    current: null,
  });
  const tail = useRef<Promise<unknown>>(Promise.resolve());

  /** Returns whether the change worked. */
  function perform(
    key: string,
    action: Action,
    failure: string,
    work: () => Promise<ActionStatus>,
  ): Promise<boolean> {
    const pending: Pending<Action> = { key, action };
    setRunning(({ count, current }) => ({
      count: count + 1,
      current: current ?? pending,
    }));

    const run = async (): Promise<boolean> => {
      setRunning(({ count }) => ({ count, current: pending }));
      try {
        let worked = true;
        try {
          announce(await work());
        } catch (error) {
          worked = false;
          announce({
            ok: false,
            message:
              error instanceof ChangeFailed && error.message
                ? error.message
                : failure,
          });
        }
        const refreshed = refresh().catch(() => undefined);
        if (worked) await refreshed;
        return worked;
      } finally {
        setRunning(({ count, current }) =>
          count <= 1
            ? { count: 0, current: null }
            : { count: count - 1, current },
        );
      }
    };
    // `run` never rejects, so the chain never breaks.
    const result = tail.current.then(run);
    tail.current = result;
    return result;
  }

  return { pending: running.count > 0 ? running.current : null, perform };
}
