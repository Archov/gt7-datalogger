// Themed select built on Radix (shadcn-style owned wrapper): keyboard
// navigation, type-ahead, proper listbox semantics — replaces native
// <select>, which can't be themed to match the dark panel UI.

import * as SelectPrimitive from "@radix-ui/react-select";

export interface SelectOption {
  value: string;
  label: React.ReactNode;
}

export function Select({
  value,
  onValueChange,
  options,
  className = "",
  ariaLabel,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  className?: string; // sizing/typography for the trigger
  ariaLabel?: string;
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger
        aria-label={ariaLabel}
        className={`inline-flex items-center justify-between gap-2 rounded-md border border-edge bg-panel-2 text-ink hover:border-accent/50 data-[placeholder]:text-ink-dim ${className}`}
      >
        <span className="truncate">
          <SelectPrimitive.Value />
        </span>
        <SelectPrimitive.Icon className="text-ink-dim">▾</SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-y-auto rounded-md border border-edge bg-panel py-1 shadow-lg shadow-black/40"
        >
          <SelectPrimitive.Viewport>
            {options.map((o) => (
              <SelectPrimitive.Item
                key={o.value}
                value={o.value}
                className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-xs text-ink outline-none data-[highlighted]:bg-panel-2 data-[state=checked]:text-accent"
              >
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="ml-auto text-accent">
                  ✓
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
