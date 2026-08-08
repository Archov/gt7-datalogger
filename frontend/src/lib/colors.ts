// Series palette shared by charts, the race line map, and lap chips.
//
// Values are validated (dataviz palette method) for the dark surfaces
// #14171c / #0b0d10: OKLCH lightness band, chroma floor, WCAG >= 3:1 contrast,
// and — in this slot order — adjacent-pair colorblind separation (worst
// protan/deutan ΔE 12.7, above the ≥8 target) and normal-vision floor. Keep
// the order fixed when using slots by index; re-run the validator if any hex
// changes.
//
// A lap's color is keyed to its id so the same lap keeps the same color in
// every view (Sessions table, Live feed, Analysis charts/map). Id-keying means
// any pair of slots can co-occur, and no 6-hue palette can make ALL pairs
// CVD-safe (amber↔orange is the weakest here) — which is why every colored
// mark ships with a text label (lap number / legend entry) beside it; color is
// never the only identity channel.
//
// Id-keying also means laps 6 apart share a slot — and "latest vs best" pairs
// them routinely. Views that show a *set* of laps side by side use
// lapColorMap(), which keeps each lap's id-keyed color unless it collides
// within that set; the colliding lap (larger id) moves to the next free slot.

export const SERIES_COLORS = [
  "#0284c7", // sky
  "#d97706", // amber
  "#a855f7", // purple
  "#65a30d", // lime
  "#ec4899", // pink
  "#ea580c", // orange
] as const;

export function lapColor(lapId: number): string {
  return SERIES_COLORS[Math.abs(lapId) % SERIES_COLORS.length];
}

/**
 * Collision-free colors for a set of laps shown together. Two passes: every
 * lap that can hold its canonical lapColor() slot keeps it (oldest lap wins a
 * contested slot), and only the losers move to the next free slot — a
 * displaced lap must never steal a slot another lap holds canonically. The
 * same set always yields the same assignment. Past six laps the palette is
 * exhausted and slots repeat (labels disambiguate).
 */
export function lapColorMap(lapIds: Iterable<number>): Map<number, string> {
  const n = SERIES_COLORS.length;
  const ids = [...new Set(lapIds)].sort((a, b) => a - b);
  const assigned = new Map<number, string>();
  const used = new Set<number>();
  const displaced: number[] = [];
  for (const id of ids) {
    const slot = Math.abs(id) % n;
    if (used.has(slot)) {
      displaced.push(id);
    } else {
      assigned.set(id, SERIES_COLORS[slot]);
      used.add(slot);
    }
  }
  for (const id of displaced) {
    let slot = Math.abs(id) % n;
    for (let i = 0; i < n && used.has(slot); i++) slot = (slot + 1) % n;
    assigned.set(id, SERIES_COLORS[slot]);
    used.add(slot);
  }
  return assigned;
}
