import type { AnalysisResult, Candidate, ProcessingSettings } from '../types/analysis'

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid API response.')
  return value as Record<string, unknown>
}

function number(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function candidate(value: unknown): value is Candidate {
  const point = record(value)
  return ['frame', 'time', 'x', 'y', 'peak_z', 'flux', 'min_neg_z'].every((key) => number(point[key]))
    && (point.ra === null || number(point.ra)) && (point.dec === null || number(point.dec))
}

function asset(value: unknown): value is string {
  return typeof value === 'string' && /^[a-zA-Z0-9_-]+\.(png|csv|json)$/.test(value)
}

export function parseAnalysis(value: unknown): AnalysisResult {
  const result = record(value)
  if (result.schemaVersion !== 1 || typeof result.id !== 'string'
    || !/^[a-f0-9]{32}$/.test(result.id) || result.baseUrl !== `/api/runs/${result.id}/`
    || typeof result.source !== 'string' || !['day', 'frame'].includes(String(result.timeUnit))
    || !number(result.width) || !number(result.height) || result.width <= 0 || result.height <= 0
    || typeof result.hasWcs !== 'boolean' || !number(result.candidateCount)
    || !number(result.validPixelFraction) || !asset(result.csv)
    || (result.topPlot !== null && !asset(result.topPlot))
    || !Array.isArray(result.warnings) || !result.warnings.every((item) => typeof item === 'string')
    || !Array.isArray(result.frames) || result.frames.length < 3 || !Array.isArray(result.tracklets)) {
    throw new Error('The processing API returned an incompatible result.')
  }
  record(result.settings)
  for (const entry of result.frames) {
    const frame = record(entry)
    const images = record(frame.images)
    if (typeof frame.id !== 'string' || typeof frame.filename !== 'string'
      || (frame.observedAt !== null && typeof frame.observedAt !== 'string')
      || !number(frame.time) || !number(frame.rms) || typeof frame.sha256 !== 'string'
      || !Array.isArray(frame.candidates) || !frame.candidates.every(candidate)
      || !['aligned', 'cleaned', 'difference', 'significance'].every((key) => asset(images[key]))) {
      throw new Error('Invalid frame metadata returned by the processing API.')
    }
  }
  for (const entry of result.tracklets) {
    const track = record(entry)
    if (typeof track.id !== 'string' || !Array.isArray(track.points) || track.points.length !== 3
      || !track.points.every(candidate)
      || !['mean_speed_px', 'velocity_consistency', 'linearity_rmse_px', 'confidence'].every((key) => number(track[key]))) {
      throw new Error('Invalid tracklet metadata returned by the processing API.')
    }
  }
  return value as AnalysisResult
}

export async function checkBackend(): Promise<void> {
  const response = await fetch('/api/health')
  if (!response.ok || (await response.json()).status !== 'ok') throw new Error('Processing API is unavailable.')
}

export async function runAnalysis(
  files: File[], settings: ProcessingSettings, timestamps: string[], source: string,
): Promise<AnalysisResult> {
  const body = new FormData()
  files.forEach((file) => body.append('files', file))
  Object.entries(settings).forEach(([key, value]) => body.append(key, String(value)))
  body.append('timestamps', JSON.stringify(timestamps))
  body.append('source', source)
  let response: Response
  try {
    response = await fetch('/api/analyze', { method: 'POST', body })
  } catch {
    throw new Error('Cannot reach the processing API. Start npm run dev:full and retry.')
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(typeof detail === 'string' ? detail : `Analysis rejected (HTTP ${response.status}). Check the settings and server terminal.`)
  }
  return parseAnalysis(await response.json())
}
