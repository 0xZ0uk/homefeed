import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";

import type { DisplayPrefs } from "#/lib/display";
import { displayPrefsQuery, saveDisplayPrefs } from "#/server/display";

const TOGGLES: { key: keyof DisplayPrefs; label: string }[] = [
  { key: "thumbnails", label: "Thumbnails" },
  { key: "viewCounts", label: "View counts" },
];

/** Show or hide thumbnails and view counts; remembered in this browser. */
export function DisplayToggles() {
  const queryClient = useQueryClient();
  const { data: prefs } = useSuspenseQuery(displayPrefsQuery);
  const save = useMutation({
    mutationFn: (next: DisplayPrefs) => saveDisplayPrefs({ data: next }),
    onMutate: (next) => {
      const previous = prefs;
      queryClient.setQueryData(displayPrefsQuery.queryKey, next);
      return { previous };
    },
    onError: (_error, _next, context) => {
      if (context) {
        queryClient.setQueryData(displayPrefsQuery.queryKey, context.previous);
      }
    },
  });

  return (
    <fieldset className="flex flex-wrap items-center gap-4 text-sm">
      <legend className="sr-only">Display</legend>
      {TOGGLES.map(({ key, label }) => (
        <label key={key} className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={prefs[key]}
            onChange={(event) =>
              save.mutate({ ...prefs, [key]: event.target.checked })
            }
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}
