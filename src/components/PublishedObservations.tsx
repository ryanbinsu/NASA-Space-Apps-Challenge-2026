import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { loadObservations } from '../services/observations'
import { searchTargets } from '../services/targets'
import type { ObservationManifest, Target } from '../types/observations'
import ObservationViewer from './ObservationViewer'

export default function PublishedObservations() {
  const [manifest, setManifest] = useState<ObservationManifest | null>(null)
  const [loadError, setLoadError] = useState('')
  const [selected, setSelected] = useState<Target | null>(null)
  const [ra, setRa] = useState('')
  const [dec, setDec] = useState('')
  const [radius, setRadius] = useState('10')
  const [message, setMessage] = useState('')
  const [matches, setMatches] = useState<Target[]>([])
  const [comparisonGroup, setComparisonGroup] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    loadObservations(controller.signal).then(setManifest).catch((error) => {
      if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : 'Cannot load published observations.')
    })
    return () => controller.abort()
  }, [])

  function choose(target: Target) {
    setSelected(target)
    setComparisonGroup('')
    setRa(String(target.raDegrees))
    setDec(String(target.decDegrees))
    setMessage('')
    setMatches([])
  }

  function search(event: FormEvent) {
    event.preventDefault()
    const r = Number(ra), d = Number(dec), span = Number(radius)
    if (!ra.trim() || !dec.trim() || ![r, d, span].every(Number.isFinite) || r < 0 || r >= 360 || d < -90 || d > 90 || span <= 0 || span > 600) {
      setMessage('Enter RA in [0, 360), Dec in [-90, 90] and a radius in (0, 600] arcminutes.')
      return
    }
    const found = searchTargets(manifest?.targets ?? [], r, d, span)
    setMatches(found)
    setSelected(null)
    setMessage(found.length ? `${found.length} published target(s) within the search radius. Choose one below.` : 'No published targets match this region. No live archive query was made; you can upload exposures below.')
  }

  const ready = selected?.observations.filter((frame) => frame.status === 'ready') ?? []
  const groups = [...new Set(ready.map((frame) => frame.processing.comparisonGroup))]
  const group = groups.includes(comparisonGroup) ? comparisonGroup : groups[0]
  const comparable = ready.filter((frame) => frame.processing.comparisonGroup === group)
  const excluded = selected?.observations.filter((frame) => frame.status !== 'ready') ?? []

  return (
    <section aria-labelledby="published-heading">
      <h2 id="published-heading">Explore published observations</h2>
      <p>Choose a curated target or search the published manifest by ICRS coordinates. This search does not download images from an archive.</p>
      {loadError && <p role="alert" className="error">{loadError}</p>}
      {!manifest && !loadError && <p role="status">Loading published observations…</p>}
      {manifest && (
        <>
          {!manifest.targets.length && <p className="notice">No curated observations have been published yet. Upload your own sequence to run the connected processing pipeline.</p>}
          <label>Published target
            <select value={selected?.id ?? ''} onChange={(event) => { const target = manifest.targets.find((target) => target.id === event.target.value); if (target) choose(target); else setSelected(null) }}>
              <option value="">Choose a published target…</option>
              {manifest.targets.map((target) => <option key={target.id} value={target.id}>{target.name}</option>)}
            </select>
          </label>
          <form className="row" onSubmit={search}>
            <label>RA (degrees)<input required type="number" min={0} max={359.999999999} step="any" value={ra} onChange={(event) => setRa(event.target.value)} /></label>
            <label>Dec (degrees)<input required type="number" min={-90} max={90} step="any" value={dec} onChange={(event) => setDec(event.target.value)} /></label>
            <label>Radius (arcminutes)<input required type="number" min={0.001} max={600} step="any" value={radius} onChange={(event) => setRadius(event.target.value)} /></label>
            <button type="submit">Search published targets</button>
          </form>
          {message && <p role="status">{message}</p>}
          <div className="row">{matches.map((target) => <button key={target.id} onClick={() => choose(target)}>{target.name}</button>)}</div>
          {selected && <>
            <h3>{selected.name}</h3>
            <label>Comparison group<select value={group ?? ''} onChange={(event) => setComparisonGroup(event.target.value)}>{groups.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <ObservationViewer key={selected.id + '-' + group} frames={comparable.map((frame) => ({ id: frame.id, label: frame.id, observedAt: frame.observedAt, images: { cleaned: `${import.meta.env.BASE_URL}observations/${frame.imagePath}` } }))} />
            <details><summary>Observation metadata and exclusions</summary>
              <ul>{ready.map((frame) => <li key={frame.id}>{frame.id} · {frame.spectral.description} · {frame.spectral.wavelengthMinMicrometers}–{frame.spectral.wavelengthMaxMicrometers} μm · comparison group {frame.processing.comparisonGroup}<br />{frame.processing.description}<ul>{frame.provenance.map((source, i) => <li key={i}><a href={source.sourceUrl} target="_blank" rel="noreferrer">{source.datasetId} / {source.productId}</a></li>)}</ul></li>)}
                {excluded.map((frame) => <li key={frame.id}>{frame.id}: {frame.status} — {frame.reason}</li>)}</ul>
            </details>
          </>}
        </>
      )}
    </section>
  )
}
