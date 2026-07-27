// Last analysis selection, shared across views: Sessions/Live write it via
// deep links, AnalysisView keeps it current, and re-entering the Analysis tab
// (which remounts the view) restores it instead of resetting to latest-vs-best.

import { create } from "zustand";

export interface AnalysisSelection {
  sessionId: number | null;
  selectedLapIds: number[];
  refLapId: number | null;
}

interface AnalysisSelectionState extends AnalysisSelection {
  setSelection: (s: AnalysisSelection) => void;
}

export const useAnalysisSelection = create<AnalysisSelectionState>((set) => ({
  sessionId: null,
  selectedLapIds: [],
  refLapId: null,
  setSelection: (s) => set(s),
}));
