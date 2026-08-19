import assert from "node:assert/strict";
import test from "node:test";

import {
  distanceAtReferenceTime,
  markerInclusiveFixedScaleBounds,
} from "../src/lib/raceLineCamera.ts";

const reference = {
  dist: [0, 100, 200],
  t: [0, 10, 20],
};

test("positive time delta places the slower lap behind the reference", () => {
  const slower = {
    dist: [0, 100, 200],
    t: [0, 15, 30],
  };

  // At 100 m: slower elapsed - reference elapsed = +5 s. At the same
  // reference instant, the slower lap has covered only 66.7 m.
  assert.equal(distanceAtReferenceTime(reference, slower, 100), 100 * (10 / 15));
});

test("negative time delta places the faster lap ahead of the reference", () => {
  const faster = {
    dist: [0, 100, 200, 300],
    t: [0, 5, 10, 15],
  };

  // At 100 m: faster elapsed - reference elapsed = -5 s. At the same
  // reference instant, the faster lap has reached 200 m.
  assert.equal(distanceAtReferenceTime(reference, faster, 100), 200);
});

test("reference-time synchronization interpolates between cursor samples", () => {
  const slower = {
    dist: [0, 100, 200],
    t: [0, 15, 30],
  };

  // Reference reaches 150 m at 15 s; the slower lap is at exactly 100 m.
  assert.equal(distanceAtReferenceTime(reference, slower, 150), 100);
});

test("reference lap remains at the cursor distance", () => {
  assert.equal(distanceAtReferenceTime(reference, reference, 137.5), 137.5);
});

test("missing elapsed-time data fails closed", () => {
  assert.equal(distanceAtReferenceTime(reference, { dist: [0, 100] }, 50), null);
  assert.equal(distanceAtReferenceTime({ dist: [0, 100] }, reference, 50), null);
});

test("marker clamp pans minimally without changing a scale that already fits", () => {
  const bounds = markerInclusiveFixedScaleBounds(
    [0, 0],
    [[0, 0], [90, 0]],
    216,
    116,
    1,
    8,
    20,
  );

  assert.deepEqual(bounds, { xMin: -90, xMax: 110, zMin: -50, zMax: 50 });
});

test("marker clamp zooms out only enough for widely separated laps", () => {
  const bounds = markerInclusiveFixedScaleBounds(
    [0, 0],
    [[-100, 0], [100, 0]],
    216,
    116,
    1,
    8,
    20,
  );

  assert.deepEqual(bounds, { xMin: -125, xMax: 125, zMin: -62.5, zMax: 62.5 });
});

test("marker clamp retains CSS-pixel padding on both axes", () => {
  const points: Array<[number, number]> = [[-160, -90], [220, 130], [20, 0]];
  const drawableWidth = 600;
  const drawableHeight = 300;
  const paddingPx = 24;
  const bounds = markerInclusiveFixedScaleBounds(
    [20, 0],
    points,
    drawableWidth + 16,
    drawableHeight + 16,
    0.25,
    8,
    paddingPx,
  );
  assert.ok(bounds);
  const metersPerPixel = (bounds.xMax - bounds.xMin) / drawableWidth;
  const verticalMetersPerPixel = (bounds.zMax - bounds.zMin) / drawableHeight;
  assert.equal(metersPerPixel, verticalMetersPerPixel);
  for (const [x, z] of points) {
    assert.ok(x >= bounds.xMin + paddingPx * metersPerPixel);
    assert.ok(x <= bounds.xMax - paddingPx * metersPerPixel);
    assert.ok(z >= bounds.zMin + paddingPx * metersPerPixel);
    assert.ok(z <= bounds.zMax - paddingPx * metersPerPixel);
  }
});
