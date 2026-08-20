export type CameraSeries = Record<string, number[]> & { dist: number[] };

export interface CameraBounds {
  xMin: number;
  xMax: number;
  zMin: number;
  zMax: number;
}

export type DistanceInterval = readonly [number, number];
export type MapPosition = [number, number];

export const MAP_GRID_PADDING_PX = 8;
export const MAP_MARKER_PADDING_PX = 24;

export function lowerBound(values: number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

export function upperBound(values: number[], target: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (values[middle] <= target) low = middle + 1;
    else high = middle;
  }
  return low;
}

export function nearestDistanceIndex(values: number[], target: number): number | null {
  if (values.length === 0 || !Number.isFinite(target)) return null;
  const right = lowerBound(values, target);
  if (right <= 0) return 0;
  if (right >= values.length) return values.length - 1;
  return target - values[right - 1] <= values[right] - target ? right - 1 : right;
}

export function positionAtDistance(
  series: CameraSeries,
  target: number,
): MapPosition | null {
  const distances = series.dist;
  const posX = series.pos_x;
  const posZ = series.pos_z;
  if (
    distances.length === 0 ||
    !Number.isFinite(target) ||
    !Array.isArray(posX) ||
    !Array.isArray(posZ) ||
    posX.length !== distances.length ||
    posZ.length !== distances.length
  ) {
    return null;
  }

  const right = lowerBound(distances, target);
  if (right <= 0) {
    return Number.isFinite(posX[0]) && Number.isFinite(posZ[0])
      ? [posX[0], posZ[0]]
      : null;
  }
  if (right >= distances.length) {
    const last = distances.length - 1;
    return Number.isFinite(posX[last]) && Number.isFinite(posZ[last])
      ? [posX[last], posZ[last]]
      : null;
  }

  const left = right - 1;
  const x0 = posX[left];
  const z0 = posZ[left];
  const x1 = posX[right];
  const z1 = posZ[right];
  if (![x0, z0, x1, z1].every(Number.isFinite)) return null;
  const span = distances[right] - distances[left];
  if (!(span > 0)) return [x1, z1];
  const fraction = Math.max(0, Math.min(1, (target - distances[left]) / span));
  return [x0 + (x1 - x0) * fraction, z0 + (z1 - z0) * fraction];
}

function interpolateAligned(
  coordinates: number[],
  values: number[],
  target: number,
): number | null {
  if (
    coordinates.length === 0 ||
    coordinates.length !== values.length ||
    !Number.isFinite(target)
  ) {
    return null;
  }
  const right = lowerBound(coordinates, target);
  if (right <= 0) return Number.isFinite(values[0]) ? values[0] : null;
  if (right >= coordinates.length) {
    const last = values[values.length - 1];
    return Number.isFinite(last) ? last : null;
  }
  const left = right - 1;
  const x0 = coordinates[left];
  const x1 = coordinates[right];
  const y0 = values[left];
  const y1 = values[right];
  if (![x0, x1, y0, y1].every(Number.isFinite)) return null;
  const span = x1 - x0;
  if (!(span > 0)) return y1;
  const fraction = Math.max(0, Math.min(1, (target - x0) / span));
  return y0 + (y1 - y0) * fraction;
}

/**
 * Locate a lap at the instant when the reference reaches `referenceDistance`.
 * This makes map-marker separation agree with the distance-based time delta:
 * positive delta (slower) appears behind, negative delta (faster) ahead.
 */
export function distanceAtReferenceTime(
  reference: CameraSeries,
  lap: CameraSeries,
  referenceDistance: number,
): number | null {
  const referenceTime = interpolateAligned(
    reference.dist,
    reference.t ?? [],
    referenceDistance,
  );
  if (referenceTime == null) return null;
  return interpolateAligned(lap.t ?? [], lap.dist, referenceTime);
}

export function fixedScaleBounds(
  center: MapPosition,
  pixelWidth: number,
  pixelHeight: number,
  metersPerPixel: number,
  gridPaddingPx = MAP_GRID_PADDING_PX,
): CameraBounds | null {
  if (
    !center.every(Number.isFinite) ||
    !(pixelWidth > gridPaddingPx * 2) ||
    !(pixelHeight > gridPaddingPx * 2) ||
    !(metersPerPixel > 0) ||
    !Number.isFinite(metersPerPixel)
  ) {
    return null;
  }
  const worldWidth = (pixelWidth - gridPaddingPx * 2) * metersPerPixel;
  const worldHeight = (pixelHeight - gridPaddingPx * 2) * metersPerPixel;
  return {
    xMin: center[0] - worldWidth / 2,
    xMax: center[0] + worldWidth / 2,
    zMin: center[1] - worldHeight / 2,
    zMax: center[1] + worldHeight / 2,
  };
}

/**
 * Preserve the requested scale as a minimum while keeping marker centers
 * inside a fixed CSS-pixel inset. Pan minimally first; zoom out only when
 * their spatial spread cannot fit at the requested scale.
 */
export function markerInclusiveFixedScaleBounds(
  preferredCenter: MapPosition,
  points: MapPosition[],
  pixelWidth: number,
  pixelHeight: number,
  minimumMetersPerPixel: number,
  gridPaddingPx = MAP_GRID_PADDING_PX,
  markerPaddingPx = MAP_MARKER_PADDING_PX,
): CameraBounds | null {
  const drawableWidth = pixelWidth - gridPaddingPx * 2;
  const drawableHeight = pixelHeight - gridPaddingPx * 2;
  if (
    !preferredCenter.every(Number.isFinite) ||
    !(drawableWidth > markerPaddingPx * 2) ||
    !(drawableHeight > markerPaddingPx * 2) ||
    !(minimumMetersPerPixel > 0) ||
    !Number.isFinite(minimumMetersPerPixel)
  ) {
    return null;
  }
  const finitePoints = points.filter((point) => point.every(Number.isFinite));
  if (finitePoints.length === 0) {
    return fixedScaleBounds(
      preferredCenter,
      pixelWidth,
      pixelHeight,
      minimumMetersPerPixel,
      gridPaddingPx,
    );
  }
  const xs = finitePoints.map((point) => point[0]);
  const zs = finitePoints.map((point) => point[1]);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const zMin = Math.min(...zs);
  const zMax = Math.max(...zs);
  const metersPerPixel = Math.max(
    minimumMetersPerPixel,
    (xMax - xMin) / (drawableWidth - markerPaddingPx * 2),
    (zMax - zMin) / (drawableHeight - markerPaddingPx * 2),
  );
  const halfWidth = (drawableWidth * metersPerPixel) / 2;
  const halfHeight = (drawableHeight * metersPerPixel) / 2;
  const markerMargin = markerPaddingPx * metersPerPixel;
  const minimumCenterX = xMax + markerMargin - halfWidth;
  const maximumCenterX = xMin - markerMargin + halfWidth;
  const minimumCenterZ = zMax + markerMargin - halfHeight;
  const maximumCenterZ = zMin - markerMargin + halfHeight;
  const centerX =
    minimumCenterX <= maximumCenterX
      ? Math.min(Math.max(preferredCenter[0], minimumCenterX), maximumCenterX)
      : (minimumCenterX + maximumCenterX) / 2;
  const centerZ =
    minimumCenterZ <= maximumCenterZ
      ? Math.min(Math.max(preferredCenter[1], minimumCenterZ), maximumCenterZ)
      : (minimumCenterZ + maximumCenterZ) / 2;
  return {
    xMin: centerX - halfWidth,
    xMax: centerX + halfWidth,
    zMin: centerZ - halfHeight,
    zMax: centerZ + halfHeight,
  };
}

export function zoomWindowIntervals(
  distances: number[],
  zoomRange: [number, number] | null | undefined,
): DistanceInterval[] {
  if (distances.length === 0) return [];
  const first = distances[0];
  const last = distances[distances.length - 1];
  if (!zoomRange) return [[first, last]];
  const start = Math.max(first, Math.min(zoomRange[0], zoomRange[1]));
  const end = Math.min(last, Math.max(zoomRange[0], zoomRange[1]));
  return start <= end ? [[start, end]] : [[first, last]];
}

export function cameraBounds(
  series: CameraSeries,
  intervals: DistanceInterval[],
  pixelWidth: number,
  pixelHeight: number,
): CameraBounds | null {
  const posX = series.pos_x;
  const posZ = series.pos_z;
  if (
    series.dist.length === 0 ||
    !Array.isArray(posX) ||
    !Array.isArray(posZ) ||
    posX.length !== series.dist.length ||
    posZ.length !== series.dist.length
  ) {
    return null;
  }
  let xMin = Number.POSITIVE_INFINITY;
  let xMax = Number.NEGATIVE_INFINITY;
  let zMin = Number.POSITIVE_INFINITY;
  let zMax = Number.NEGATIVE_INFINITY;
  let count = 0;
  for (const [start, end] of intervals) {
    const left = Math.max(0, lowerBound(series.dist, start) - 1);
    const right = Math.min(series.dist.length, upperBound(series.dist, end) + 1);
    for (let index = left; index < right; index++) {
      const x = posX[index];
      const z = posZ[index];
      if (!Number.isFinite(x) || !Number.isFinite(z)) continue;
      xMin = Math.min(xMin, x);
      xMax = Math.max(xMax, x);
      zMin = Math.min(zMin, z);
      zMax = Math.max(zMax, z);
      count++;
    }
  }
  if (count === 0) return null;

  const minimumExtent = 16;
  const rawWidth = Math.max(minimumExtent, xMax - xMin);
  const rawHeight = Math.max(minimumExtent, zMax - zMin);
  let worldWidth = rawWidth * 1.3;
  let worldHeight = rawHeight * 1.3;
  const viewportAspect = pixelWidth > 0 && pixelHeight > 0 ? pixelWidth / pixelHeight : 1;
  if (worldWidth / worldHeight < viewportAspect) worldWidth = worldHeight * viewportAspect;
  else worldHeight = worldWidth / viewportAspect;
  const centerX = (xMin + xMax) / 2;
  const centerZ = (zMin + zMax) / 2;
  return {
    xMin: centerX - worldWidth / 2,
    xMax: centerX + worldWidth / 2,
    zMin: centerZ - worldHeight / 2,
    zMax: centerZ + worldHeight / 2,
  };
}
