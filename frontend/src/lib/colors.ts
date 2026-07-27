// Series palette shared by charts, the race line map, and lap chips.
// A lap's color is keyed to its id so the same lap keeps the same color in
// every view (Sessions table, Live feed, Analysis charts/map). Two laps whose
// ids collide mod the palette length share a color — acceptable for the small
// selections we chart, in exchange for a stable cross-view identity.

export const SERIES_COLORS = [
  "#38bdf8",
  "#f472b6",
  "#a3e635",
  "#facc15",
  "#c084fc",
  "#fb923c",
] as const;

export function lapColor(lapId: number): string {
  return SERIES_COLORS[Math.abs(lapId) % SERIES_COLORS.length];
}
