import assert from "node:assert/strict";
import test from "node:test";

import {
  screenRotationFromVector,
  vehicleMarkerHeadings,
} from "../src/lib/vehicleOrientation.ts";

const HALF_SQRT_TWO = Math.SQRT1_2;

const RENDERED_CARDINAL_ROTATIONS = {
  north: 0,
  south: 180,
  east: 270,
  west: 90,
} as const;

function samplesForQuaternion(quaternion: readonly [number, number, number, number]) {
  return {
    dist: [0],
    orientation_x: [quaternion[0]],
    orientation_y: [quaternion[1]],
    orientation_z: [quaternion[2]],
    orientation_w: [quaternion[3]],
  };
}

test("world X/Z cardinals map to ECharts counterclockwise symbolRotate", () => {
  assert.equal(screenRotationFromVector([0, -1]), RENDERED_CARDINAL_ROTATIONS.north);
  assert.equal(screenRotationFromVector([0, 1]), RENDERED_CARDINAL_ROTATIONS.south);
  assert.equal(screenRotationFromVector([1, 0]), RENDERED_CARDINAL_ROTATIONS.east);
  assert.equal(screenRotationFromVector([-1, 0]), RENDERED_CARDINAL_ROTATIONS.west);
});

test("quaternion-derived chassis cardinals match the rendered map", () => {
  const cases = [
    ["north", [0, 0, 0, 1]],
    ["south", [0, 1, 0, 0]],
    ["east", [0, -HALF_SQRT_TWO, 0, HALF_SQRT_TWO]],
    ["west", [0, HALF_SQRT_TWO, 0, HALF_SQRT_TWO]],
  ] as const;

  for (const [direction, quaternion] of cases) {
    assert.equal(
      vehicleMarkerHeadings(samplesForQuaternion(quaternion), 0).chassisRotationDeg,
      RENDERED_CARDINAL_ROTATIONS[direction],
    );
  }
});

test("native travel-velocity cardinals match the rendered map", () => {
  const cases = [
    ["north", 0, -1],
    ["south", 0, 1],
    ["east", 1, 0],
    ["west", -1, 0],
  ] as const;

  for (const [direction, velocityX, velocityZ] of cases) {
    assert.equal(
      vehicleMarkerHeadings(
        { dist: [0], velocity_x: [velocityX], velocity_z: [velocityZ] },
        0,
      ).travelRotationDeg,
      RENDERED_CARDINAL_ROTATIONS[direction],
    );
  }
});
