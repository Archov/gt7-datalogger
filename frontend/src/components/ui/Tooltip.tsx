// Themed tooltip built on Radix — replaces title="…" attributes, which are
// invisible on touch devices, slow to appear, and unthemable.

import * as TooltipPrimitive from "@radix-ui/react-tooltip";

// Mount once in App so all tooltips share one delay/skip context.
export const TooltipProvider = TooltipPrimitive.Provider;

export function Tip({
  content,
  children,
}: {
  content: React.ReactNode;
  children: React.ReactNode; // must be a single focusable element
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-64 rounded-md border border-edge bg-panel px-2.5 py-1.5 text-xs text-ink shadow-lg shadow-black/40"
        >
          {content}
          <TooltipPrimitive.Arrow className="fill-panel" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
