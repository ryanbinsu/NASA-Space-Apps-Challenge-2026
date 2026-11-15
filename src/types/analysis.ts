export interface Candidate {
  frame: number
  time: number
  x: number
  y: number
  ra: number | null
  dec: number | null
  peak_z: number
  flux: number
  min_neg_z: number
}

export type ImageMode = 'aligned' | 'cleaned' | 'difference' | 'significance'

export interface AnalysisFrame {
  id: string
  filename: string
  observedAt: string | null
  time: number
  rms: number
  sha256: string
  candidates: Candidate[]
  images: Record<ImageMode, string>
}

export interface Tracklet {
  id: string
  points: Candidate[]
  mean_speed_px: number
  velocity_consistency: number
  linearity_rmse_px: number
  confidence: number
}

export interface AnalysisResult {
  schemaVersion: 1
  id: string
  baseUrl: string
  source: string
  timeUnit: 'day' | 'frame'
  width: number
  height: number
  hasWcs: boolean
  frames: AnalysisFrame[]
  tracklets: Tracklet[]
  candidateCount: number
  validPixelFraction: number
  csv: string
  topPlot: string | null
  warnings: string[]
  settings: Record<string, number | boolean>
}

export interface ProcessingSettings {
  hdu_index: number
  filter_size: number
  box_size: number
  normalize: boolean
  z_thresh: number
  min_area: number
  min_step_px: number
  max_step_px: number
}
