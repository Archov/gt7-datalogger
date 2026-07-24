import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Units } from "@/lib/format";

interface SettingsState {
  units: Units;
  setUnits: (u: Units) => void;
}

export const useSettings = create<SettingsState>()(
  persist(
    (set) => ({
      units: "metric",
      setUnits: (units) => set({ units }),
    }),
    { name: "gt7-settings" },
  ),
);
