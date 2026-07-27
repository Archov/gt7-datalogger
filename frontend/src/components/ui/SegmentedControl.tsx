// Segmented single-choice control built on Radix ToggleGroup — replaces the
// ad-hoc button rows for layout/alignment/page/source pickers with proper
// radio-like semantics and arrow-key navigation.

import * as ToggleGroup from "@radix-ui/react-toggle-group";

export function SegmentedControl<T extends string>({
  value,
  onValueChange,
  options,
  ariaLabel,
  disabled = false,
}: {
  value: T;
  onValueChange: (value: T) => void;
  options: { value: T; label: React.ReactNode }[];
  ariaLabel: string;
  disabled?: boolean;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(v) => {
        if (v) onValueChange(v as T); // ignore deselect — one option is always active
      }}
      aria-label={ariaLabel}
      disabled={disabled}
      className="inline-flex overflow-hidden rounded-md border border-edge"
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          className="px-3 py-1.5 text-xs text-ink-dim hover:text-ink data-[state=on]:bg-accent/15 data-[state=on]:text-accent"
        >
          {o.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
