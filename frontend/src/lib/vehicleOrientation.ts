export const MIN_TRAVEL_SPEED_MPS = 0.1;

type Quaternion = [number, number, number, number];
type Vector2 = [number, number];
type Samples = Record<string, number[]>;

const ORIENTATION_CHANNELS = [
  "orientation_x",
  "orientation_y",
  "orientation_z",
  "orientation_w",
] as const;

function lowerBound(values: number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = low + Math.floor((high - low) / 2);
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function normalizeQuaternion(values: readonly number[]): Quaternion | null {
  if (values.length !== 4 || !values.every(Number.isFinite)) return null;
  const norm = Math.hypot(...values);
  if (!(norm > 0) || Math.abs(norm - 1) > 0.05) return null;
  return values.map((value) => value / norm) as Quaternion;
}

function slerp(left: readonly number[], right: readonly number[], fraction: number): Quaternion | null {
  const q0 = normalizeQuaternion(left);
  const normalizedRight = normalizeQuaternion(right);
  if (!q0 || !normalizedRight) return null;
  let q1: Quaternion = normalizedRight;
  let dot = q0.reduce((sum, value, index) => sum + value * q1[index], 0);
  if (dot < 0) {
    q1 = q1.map((value) => -value) as Quaternion;
    dot = -dot;
  }
  dot = Math.min(1, Math.max(-1, dot));
  if (dot > 0.9995) {
    return normalizeQuaternion(q0.map((value, index) => value + fraction * (q1[index] - value)));
  }
  const angle = Math.acos(dot);
  const scale = Math.sin(angle);
  if (scale === 0) return q0;
  const leftWeight = Math.sin((1 - fraction) * angle) / scale;
  const rightWeight = Math.sin(fraction * angle) / scale;
  return normalizeQuaternion(
    q0.map((value, index) => leftWeight * value + rightWeight * q1[index]),
  );
}

function bracket(distances: number[], target: number): [number, number, number] | null {
  if (distances.length === 0 || !Number.isFinite(target)) return null;
  const right = lowerBound(distances, target);
  if (right <= 0) return [0, 0, 0];
  if (right >= distances.length) {
    const last = distances.length - 1;
    return [last, last, 0];
  }
  if (distances[right] === target) return [right, right, 0];
  const left = right - 1;
  const span = distances[right] - distances[left];
  if (!(span > 0)) return [left, left, 0];
  return [left, right, Math.max(0, Math.min(1, (target - distances[left]) / span))];
}

function scalarAtDistance(
  samples: Samples,
  channel: string,
  indices: [number, number, number],
): number | null {
  const values = samples[channel];
  if (!Array.isArray(values) || values.length !== samples.dist.length) return null;
  const [left, right, fraction] = indices;
  const a = values[left];
  const b = values[right];
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return a + (b - a) * fraction;
}

function quaternionAtDistance(
  samples: Samples,
  indices: [number, number, number],
): Quaternion | null {
  const arrays = ORIENTATION_CHANNELS.map((channel) => samples[channel]);
  if (arrays.some((values) => !Array.isArray(values) || values.length !== samples.dist.length)) {
    return null;
  }
  const [left, right, fraction] = indices;
  const q0 = arrays.map((values) => values[left]);
  if (left === right) return normalizeQuaternion(q0);
  return slerp(q0, arrays.map((values) => values[right]), fraction);
}

export function screenRotationFromVector([x, z]: Vector2): number | null {
  if (!Number.isFinite(x) || !Number.isFinite(z) || Math.hypot(x, z) === 0) return null;
  // The custom symbol points north/up at zero degrees. ZRender, which applies
  // ECharts symbolRotate, defines positive rotation as counterclockwise even
  // though screen Y points down. Negate the clockwise X/Z map heading so
  // east/right is 270 degrees and west/left is 90 degrees.
  const degrees = -((Math.atan2(z, x) * 180) / Math.PI + 90);
  return ((degrees % 360) + 360) % 360;
}

export interface VehicleMarkerHeadings {
  chassisRotationDeg: number | null;
  travelRotationDeg: number | null;
}

export function vehicleMarkerHeadings(
  samples: Samples,
  distance: number,
): VehicleMarkerHeadings {
  const indices = bracket(samples.dist, distance);
  if (!indices) return { chassisRotationDeg: null, travelRotationDeg: null };

  const quaternion = quaternionAtDistance(samples, indices);
  let chassisRotationDeg: number | null = null;
  if (quaternion) {
    const [x, y, z, w] = quaternion;
    chassisRotationDeg = screenRotationFromVector([
      -2 * (x * z + y * w),
      -(1 - 2 * (x * x + y * y)),
    ]);
  }

  const velocityX = scalarAtDistance(samples, "velocity_x", indices);
  const velocityZ = scalarAtDistance(samples, "velocity_z", indices);
  const travelRotationDeg =
    velocityX != null &&
    velocityZ != null &&
    Math.hypot(velocityX, velocityZ) >= MIN_TRAVEL_SPEED_MPS
      ? screenRotationFromVector([velocityX, velocityZ])
      : null;

  return { chassisRotationDeg, travelRotationDeg };
}
