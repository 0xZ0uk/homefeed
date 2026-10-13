import { Combobox } from "@base-ui/react/combobox";
import { CheckIcon, ChevronDownIcon } from "lucide-react";
import { useMemo } from "react";

import {
  supportedTimezones,
  timezoneItems,
  type TimezoneItem,
} from "#/lib/settings";

/**
 * A searchable list of time zones, "System default (…)" first. `value` is an
 * IANA name, or "" for the system's time zone.
 */
export function TimezonePicker({
  id,
  value,
  system,
  disabled,
  describedBy,
  onChange,
}: {
  id: string;
  value: string;
  /** The server's time zone, used while none is picked. */
  system: string | null;
  disabled?: boolean;
  describedBy?: string;
  onChange: (value: string) => void;
}) {
  const items = useMemo(
    () => timezoneItems(supportedTimezones(), system, value || null),
    [system, value],
  );
  const selected = items.find((item) => item.value === value) ?? items[0];

  return (
    <Combobox.Root
      items={items}
      value={selected}
      disabled={disabled}
      autoHighlight
      isItemEqualToValue={(item: TimezoneItem, current: TimezoneItem) =>
        item.value === current.value
      }
      onValueChange={(item: TimezoneItem | null) => {
        if (item) onChange(item.value);
      }}
    >
      <Combobox.InputGroup className="relative flex h-8 w-full max-w-sm items-center rounded-lg border border-input transition-colors focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50 has-disabled:opacity-50 dark:bg-input/30">
        <Combobox.Input
          id={id}
          aria-describedby={describedBy}
          placeholder="Search time zones"
          className="h-full w-full min-w-0 bg-transparent pr-8 pl-2.5 text-base outline-none placeholder:text-muted-foreground md:text-sm"
        />
        <Combobox.Trigger
          aria-label="Show time zones"
          className="absolute right-0 flex h-full w-8 items-center justify-center text-muted-foreground"
        >
          <ChevronDownIcon className="size-4" aria-hidden />
        </Combobox.Trigger>
      </Combobox.InputGroup>
      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} className="isolate z-50">
          <Combobox.Popup className="max-h-[min(20rem,var(--available-height))] w-(--anchor-width) overflow-hidden rounded-lg bg-popover text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10">
            <Combobox.Empty className="p-3 text-muted-foreground empty:hidden">
              No time zone matches.
            </Combobox.Empty>
            <Combobox.List className="max-h-[min(20rem,var(--available-height))] overflow-y-auto overscroll-contain p-1 data-empty:p-0">
              {(item: TimezoneItem) => (
                <Combobox.Item
                  key={item.value}
                  value={item}
                  className="grid cursor-default grid-cols-[1rem_1fr] items-center gap-2 rounded-md px-2 py-1.5 outline-none select-none data-highlighted:bg-muted"
                >
                  <Combobox.ItemIndicator className="col-start-1">
                    <CheckIcon className="size-4" aria-hidden />
                  </Combobox.ItemIndicator>
                  <span className="col-start-2">{item.label}</span>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
