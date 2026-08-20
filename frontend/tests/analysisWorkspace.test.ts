import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_ANALYSIS_WORKSPACE,
  parseWorkspacePreferences,
} from "../src/lib/analysisWorkspace.ts";

test("older workspace versions migrate with marker clamping enabled", () => {
  const versions = [
    {
      version: 1,
      inspectorWidth: 360,
      mapHeight: 420,
      timelineDensity: "normal",
      followCursor: true,
      mapWindowMeters: 600,
    },
    {
      version: 2,
      inspectorWidth: 360,
      mapHeight: 420,
      timelineDensity: "normal",
      followCursor: true,
      mapMetersPerPixel: 0.25,
    },
    {
      version: 3,
      inspectorWidth: 360,
      mapHeight: 420,
      timelineDensity: "normal",
      followCursor: true,
      showTravelDirection: false,
      mapMetersPerPixel: 0.5,
    },
  ];

  for (const legacy of versions) {
    const migrated = parseWorkspacePreferences(JSON.stringify(legacy));
    assert.equal(migrated.version, 4);
    assert.equal(migrated.keepLapMarkersVisible, true);
  }
});

test("version 4 preserves the marker-clamp toggle", () => {
  const disabled = parseWorkspacePreferences(
    JSON.stringify({ ...DEFAULT_ANALYSIS_WORKSPACE, keepLapMarkersVisible: false }),
  );

  assert.equal(disabled.version, 4);
  assert.equal(disabled.keepLapMarkersVisible, false);
});
