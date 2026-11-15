import type { Target } from '../types/observations'

/** Great-circle distance; handles RA wrap and polar coordinates. Inputs in degrees. */
export function angularDistance(ra1: number, dec1: number, ra2: number, dec2: number): number {
  const rad = Math.PI / 180
  const a = Math.sin((dec2 - dec1) * rad / 2) ** 2
    + Math.cos(dec1 * rad) * Math.cos(dec2 * rad) * Math.sin((ra2 - ra1) * rad / 2) ** 2
  return 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a)))) / rad
}

export function searchTargets(targets: Target[], ra: number, dec: number, radiusArcminutes: number): Target[] {
  return targets.filter((target) =>
    angularDistance(ra, dec, target.raDegrees, target.decDegrees) <= radiusArcminutes / 60,
  ).sort((a, b) =>
    angularDistance(ra, dec, a.raDegrees, a.decDegrees) - angularDistance(ra, dec, b.raDegrees, b.decDegrees),
  )
}
