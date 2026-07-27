// Toast stack renderer — mounted once in App, fed by store/toasts.

import { useToasts } from "@/store/toasts";

const KIND_CLASSES = {
  info: "border-accent/40 text-accent",
  success: "border-throttle/40 text-throttle",
  error: "border-brake/40 text-brake",
} as const;

export function Toasts() {
  const { toasts, dismiss } = useToasts();
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-72 flex-col gap-2">
      {toasts.map((t) => (
        <button
          key={t.id}
          onClick={() => dismiss(t.id)}
          className={`pointer-events-auto rounded-lg border bg-panel px-3 py-2 text-left text-sm shadow-lg shadow-black/30 ${KIND_CLASSES[t.kind]}`}
        >
          {t.text}
        </button>
      ))}
    </div>
  );
}
