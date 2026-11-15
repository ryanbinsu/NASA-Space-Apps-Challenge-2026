import { useEffect, useState } from 'react'
import type { Candidate, ImageMode } from '../types/analysis'

export interface ViewerFrame {
  id: string
  label: string
  observedAt: string | null
  images: Partial<Record<ImageMode, string>>
  candidates?: Candidate[]
}

interface Props {
  frames: ViewerFrame[]
  width?: number
  height?: number
  selectedPoints?: Candidate[]
}

const labels: Record<ImageMode, string> = {
  aligned: 'Aligned input', cleaned: 'Cleaned intensity',
  difference: 'Difference from median reference', significance: 'Approximate Z significance',
}

export default function ObservationViewer({ frames, width, height, selectedPoints = [] }: Props) {
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [delay, setDelay] = useState(700)
  const [mode, setMode] = useState<ImageMode>('cleaned')
  const [overlays, setOverlays] = useState(true)
  const [failedUrl, setFailedUrl] = useState('')

  useEffect(() => {
    if (!playing || frames.length < 2) return
    const timer = window.setInterval(() => setIndex((previous) => (previous + 1) % frames.length), delay)
    return () => window.clearInterval(timer)
  }, [playing, delay, frames.length])

  if (!frames.length) return <p>No displayable observations in this sequence.</p>
  const frame = frames[index] ?? frames[0]
  const url = frame.images[mode] ?? frame.images.cleaned
  const points = selectedPoints.length ? selectedPoints.filter((point) => point.frame === index) : frame.candidates ?? []

  return (
    <section aria-label="Observation viewer">
      <div className="row">
        <label>Image layer
          <select value={mode} onChange={(event) => setMode(event.target.value as ImageMode)}>
            {(Object.keys(labels) as ImageMode[]).filter((key) => frame.images[key]).map((key) =>
              <option key={key} value={key}>{labels[key]}</option>,
            )}
          </select>
        </label>
        <label>Playback interval
          <select value={delay} onChange={(event) => setDelay(Number(event.target.value))}>
            <option value={1400}>1.4 seconds</option><option value={700}>0.7 seconds</option><option value={250}>0.25 seconds</option>
          </select>
        </label>
        {width && <label className="check"><input type="checkbox" checked={overlays} onChange={(event) => setOverlays(event.target.checked)} />Candidate overlays</label>}
      </div>
      <div className="image-stage" style={width && height ? { width: "min(100%, calc(65vh * " + width / height + "))" } : undefined}>
        {url && <img src={url} alt={`${labels[mode]} — ${frame.label}`} onError={() => { setFailedUrl(url); setPlaying(false) }} />}
        {failedUrl === url && <p role="alert" className="image-error">This image could not be loaded. Check its exported path or rerun the analysis.</p>}
        {overlays && width && height && (
          <svg className="overlays" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-label={`${points.length} candidate positions`}>
            {points.map((point, i) => <circle key={i} cx={point.x} cy={height - 1 - point.y} r={Math.max(width / 70, 4)} fill="none" stroke={selectedPoints.length ? '#ffdb75' : '#6df1d3'} strokeWidth={Math.max(width / 400, 1)} />)}
          </svg>
        )}
      </div>
      <p><strong>Frame {index + 1} / {frames.length}</strong> · {frame.label}</p>
      <p>{frame.observedAt ? `UTC: ${frame.observedAt}` : 'Observation time unavailable — frame order only.'}</p>
      <input className="timeline" type="range" min={0} max={frames.length - 1} value={index} onChange={(event) => { setPlaying(false); setIndex(Number(event.target.value)) }} aria-label="Observation frame" />
      <div className="row">
        <button disabled={frames.length < 2} onClick={() => { setPlaying(false); setIndex((index + frames.length - 1) % frames.length) }}>Previous</button>
        <button className="primary" disabled={frames.length < 2 || failedUrl === url} onClick={() => setPlaying(!playing)}>{playing ? 'Pause' : 'Play'}</button>
        <button disabled={frames.length < 2} onClick={() => { setPlaying(false); setIndex((index + 1) % frames.length) }}>Next</button>
      </div>
      {mode === 'significance' && <p className="muted">Blue: negative; red: positive residual. Display clipped at ±10 Z. Approximate model, not a calibrated detection significance.</p>}
      {mode === 'difference' && <p className="muted">Science minus median reference. Symmetric color limits are shared across frames; red is positive and blue negative.</p>}
    </section>
  )
}
