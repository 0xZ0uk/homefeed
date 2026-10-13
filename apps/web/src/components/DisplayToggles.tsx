import {
  useMutation,
  useQueryClient,
  useSuspenseQuery,
} from "@tanstack/react-query";

import type { DisplayPrefs } from "#/lib/display";
import { displayPrefsQuery, saveDisplayPrefs } from "#/server/display";

const TOGGLES: { key: keyof DisplayPrefs; label: string }[] = [
  { key: "textOnly", label: "Text only" },
  { key: "thumbnails", label: "Thumbnails" },
  { key: "viewCounts", label: "View counts" },
];

/**
 * Text-only mode, and showing thumbnails and view counts; remembered in this
 * browser. Text-only mode hides every image, so it turns the thumbnails
 * toggle off (and disables it) while on.
 */
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
    <fieldset className="flex flex-wrap items-center gap-2 text-sm">
      <legend className="float-left mr-2 font-medium">Display</legend>
      {TOGGLES.map(({ key, label }) => {
        const disabled = key === "thumbnails" && prefs.textOnly;
        return (
          <label
            key={key}
            className="flex h-8 cursor-pointer items-center gap-1.5 rounded-lg bg-secondary px-3 font-medium transition-colors select-none hover:bg-accent has-checked:bg-primary has-checked:text-primary-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/50 has-disabled:cursor-not-allowed has-disabled:opacity-50"
          >
            <input
              type="checkbox"
              className="sr-only"
              checked={prefs[key] && !disabled}
              disabled={disabled}
              onChange={(event) =>
                save.mutate({ ...prefs, [key]: event.target.checked })
              }
            />
            {label}
          </label>
        );
      })}
    </fieldset>
  );
}
