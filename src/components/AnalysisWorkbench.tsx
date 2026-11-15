import { useState } from 'react'
import type { FormEvent } from 'react'
import { runAnalysis } from '../services/analysis'
import type { AnalysisResult, ProcessingSettings } from '../types/analysis'
import ObservationViewer from './ObservationViewer'

const defaults: ProcessingSettings = {
  hdu_index: 0, filter_size: 3, box_size: 64, normalize: true,
  z_thresh: 5, min_area: 3, min_step_px: 1.5, max_step_px: 50,
}

export default function AnalysisWorkbench() {
  const [inputs, setInputs] = useState<{ file: File; time: string }[]>([])
  const [settings, setSettings] = useState(defaults)
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [selectedId, setSelectedId] = useState('')

  function move(index: number, delta: number) {
    setInputs((previous) => {
      const next = [...previous]
      const target = index + delta
      if (target >= 0 && target < next.length) [next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (inputs.length < 3 || inputs.length > 8) {
      setError('Select between 3 and 8 exposures.')
      return
    }
    if (inputs.some(({ file }) => file.size > 20 * 1024 * 1024)
      || inputs.reduce((total, { file }) => total + file.size, 0) > 100 * 1024 * 1024) {
      setError('Limit uploads to 20 MiB per exposure and 100 MiB total.')
      return
    }
    const times = inputs.map(({ time }) => time.trim())
    if (times.some(Boolean) && !times.every(Boolean)) {
      setError('Supply UTC times for every exposure, or leave all times blank to use FITS headers / frame order.')
      return
    }
    if (settings.filter_size % 2 === 0 || settings.min_step_px > settings.max_step_px) {
      setError('Median filter size must be odd and minimum step cannot exceed maximum step.')
      return
    }
    setBusy(true)
    setResult(null)
    setSelectedId('')
    try {
      setResult(await runAnalysis(inputs.map(({ file }) => file), settings, times.every(Boolean) ? times : [], source))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed.')
    } finally {
      setBusy(false)
    }
  }

  const selectedTrack = result?.tracklets.find((track) => track.id === selectedId)

  return (
    <section aria-labelledby="analysis-heading">
      <h2 id="analysis-heading">Analyze your observations</h2>
      <p>Run the team's Python mathematics on 3–8 exposures: align → clean → difference → link motion → rank candidates.</p>
      <p className="muted">Use comparable spectral data. FITS requires a celestial WCS; standard images need enough shared stars for alignment. These checks cannot certify scientific comparability.</p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <label>Observation files
            <input type="file" multiple accept=".fits,.fit,.fts,.png,.jpg,.jpeg,.tif,.tiff" onChange={(event) => setInputs(Array.from(event.target.files ?? []).map((file) => ({ file, time: '' })))} />
          </label>
          <p className="muted">At least 32×32, at most 1,048,576 pixels each. FITS times are sorted automatically when complete; otherwise arrange the upload order below. UTC overrides must be supplied for every frame.</p>
          <ol className="file-list">
            {inputs.map(({ file, time }, index) => (
              <li key={`${file.name}-${index}`}>
                <span>{file.name} ({(file.size / 1024).toFixed(0)} KiB)</span>
                <div className="row">
                  <input aria-label={`UTC time for ${file.name}`} placeholder="UTC override: 2026-01-01T00:00:00Z" value={time} onChange={(event) => setInputs((previous) => previous.map((input, i) => i === index ? { ...input, time: event.target.value } : input))} />
                  <button type="button" aria-label={`Move ${file.name} earlier`} disabled={busy || index === 0} onClick={() => move(index, -1)}>↑</button>
                  <button type="button" aria-label={`Move ${file.name} later`} disabled={busy || index === inputs.length - 1} onClick={() => move(index, 1)}>↓</button>
                </div>
              </li>
            ))}
          </ol>
          <label>Source / dataset description (user supplied)
            <input maxLength={300} value={source} onChange={(event) => setSource(event.target.value)} placeholder="Dataset/release, band selection and provenance reference" />
          </label>
          <details>
            <summary>Processing parameters</summary>
            <div className="control-grid">
              {([
                ['hdu_index', 'FITS image HDU (0 = primary)', 0, 100, 1],
                ['filter_size', 'Median filter size (odd pixels)', 1, 9, 2],
                ['box_size', 'Background mesh size (pixels)', 8, 256, 1],
                ['z_thresh', 'Detection threshold (approximate Z)', 1, 50, 0.5],
                ['min_area', 'Minimum peak area (pixels)', 1, 100, 1],
                ['min_step_px', 'Minimum inter-frame step (pixels)', 0, 100, 0.1],
                ['max_step_px', 'Maximum inter-frame step (pixels)', 0.1, 500, 0.1],
              ] as const).map(([key, label, min, max, step]) => (
                <label key={key}>{label}
                  <input type="number" required min={min} max={max} step={step} value={settings[key]} onChange={(event) => setSettings((previous) => ({ ...previous, [key]: Number(event.target.value) }))} />
                </label>
              ))}
            </div>
            <label className="check"><input type="checkbox" checked={settings.normalize} onChange={(event) => setSettings((previous) => ({ ...previous, normalize: event.target.checked }))} />Normalize bright-pixel flux to the first exposure</label>
            <p className="muted">Step bounds are displacement per consecutive image pair, not speed per day. Detection uses a median reference. Tracking tests three consecutive frames; it does not fit an orbit.</p>
          </details>
          <button className="primary" type="submit">{busy ? 'Processing…' : 'Run analysis'}</button>
        </fieldset>
      </form>
      {busy && <p role="status">Python is aligning and processing the images. This may take a moment; do not submit another run.</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {result && (
        <div className="results">
          <h3>Analysis results</h3>
          <p>{result.source} · {result.frames.length} frames · {result.candidateCount} positive residual peaks · {result.tracklets.length} three-frame tracklets</p>
          <p>Common valid sky area: {(100 * result.validPixelFraction).toFixed(1)}%. Sky coordinates {result.hasWcs ? 'derived from the reference WCS' : 'unavailable (no WCS)'}.</p>
          <ul className="notice">{result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          <ObservationViewer
            key={result.id}
            frames={result.frames.map((frame) => ({ id: frame.id, label: frame.filename, observedAt: frame.observedAt, candidates: frame.candidates, images: Object.fromEntries(Object.entries(frame.images).map(([key, path]) => [key, result.baseUrl + path])) }))}
            width={result.width} height={result.height} selectedPoints={selectedTrack?.points}
          />
          <div className="row downloads">
            <a href={result.baseUrl + result.csv} download>Download candidate CSV</a>
            <a href={result.baseUrl + 'result.json'} download>Download full results / provenance</a>
            {result.topPlot && <a href={result.baseUrl + result.topPlot} download>Download top-candidate plot</a>}
          </div>
          <h3>Ranked motion candidates</h3>
          <p className="muted">Heuristic score is 0–1, not a probability. Z is approximate. Speeds use {result.timeUnit === 'day' ? 'pixels per day from UTC epochs' : 'pixels per frame because observation times are unknown'}. Overlapping triplets may describe the same source.</p>
          {!result.tracklets.length ? <p>No tracklets passed the current criteria. This is a valid analysis result, not evidence that the sky contains no moving objects.</p> : (
            <>
              <button onClick={() => setSelectedId('')}>Show all peak overlays</button>
              <div className="table-scroll"><table>
                <thead><tr><th>Candidate</th><th>Score</th><th>Mean Z</th><th>Speed px/{result.timeUnit}</th><th>Velocity consistency</th><th>Linearity RMSE px</th><th>Start RA / Dec °</th></tr></thead>
                <tbody>{result.tracklets.slice(0, 200).map((track) => <tr key={track.id} className={selectedId === track.id ? 'selected' : ''}>
                  <td><button aria-pressed={selectedId === track.id} onClick={() => setSelectedId(track.id)}>{track.id}</button></td>
                  <td>{track.confidence.toFixed(4)}</td>
                  <td>{(track.points.reduce((sum, point) => sum + point.peak_z, 0) / track.points.length).toFixed(2)}</td>
                  <td>{track.mean_speed_px.toFixed(3)}</td><td>{track.velocity_consistency.toFixed(3)}</td><td>{track.linearity_rmse_px.toFixed(3)}</td>
                  <td>{track.points[0].ra === null ? 'Unavailable' : `${track.points[0].ra.toFixed(6)} / ${track.points[0].dec?.toFixed(6)}`}</td>
                </tr>)}</tbody>
              </table></div>
              {result.tracklets.length > 200 && <p>Showing the top 200 tracklets; the CSV contains all ranked results.</p>}
            </>
          )}
          {selectedTrack && <details open><summary>Selected tracklet: {selectedTrack.id}</summary>
            <p>Three linked detections. Flux is the sum of significance-map pixels in the extracted footprint, not calibrated source flux.</p>
            <div className="table-scroll"><table>
              <thead><tr><th>Frame</th><th>Pixel x / y</th><th>RA / Dec °</th><th>Peak Z</th><th>Integrated Z</th><th>Nearby minimum Z</th></tr></thead>
              <tbody>{selectedTrack.points.map((point) => <tr key={point.frame}>
                <td>{point.frame + 1}</td><td>{point.x.toFixed(2)} / {point.y.toFixed(2)}</td>
                <td>{point.ra === null ? 'Unavailable' : point.ra.toFixed(6) + ' / ' + point.dec?.toFixed(6)}</td>
                <td>{point.peak_z.toFixed(2)}</td><td>{point.flux.toFixed(2)}</td><td>{point.min_neg_z.toFixed(2)}</td>
              </tr>)}</tbody>
            </table></div>
          </details>}
          <details><summary>Frame noise and input provenance</summary>
            <ul>{result.frames.map((frame) => <li key={frame.id}><strong>{frame.filename}</strong> · RMS {frame.rms.toPrecision(4)} · {frame.candidates.length} peaks<br /><code>SHA-256: {frame.sha256}</code></li>)}</ul>
            <pre>{JSON.stringify(result.settings, null, 2)}</pre>
          </details>
          {result.topPlot && <figure><img src={result.baseUrl + result.topPlot} alt="Highest-ranked candidate across its three linked exposures" /><figcaption>Top heuristic-ranked tracklet, not a confirmed discovery.</figcaption></figure>}
        </div>
      )}
    </section>
  )
}
