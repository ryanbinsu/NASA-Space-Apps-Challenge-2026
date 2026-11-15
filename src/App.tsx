import { useEffect, useState } from 'react'
import AnalysisWorkbench from './components/AnalysisWorkbench'
import PublishedObservations from './components/PublishedObservations'
import { checkBackend } from './services/analysis'

export default function App() {
  const [backend, setBackend] = useState<'checking' | 'online' | 'offline'>('checking')

  async function check() {
    try {
      await checkBackend()
      setBackend('online')
    } catch {
      setBackend('offline')
    }
  }

  useEffect(() => {
    let active = true
    checkBackend().then(() => { if (active) setBackend('online') }).catch(() => { if (active) setBackend('offline') })
    return () => { active = false }
  }, [])

  return (
    <main>
      <header>
        <p className="eyebrow">NASA Space Apps Challenge 2026 · Team Phys***</p>
        <h1>SPHEREx Motion Explorer</h1>
        <p>Compare observations over time and inspect candidate motion with the team's image-processing pipeline.</p>
        <div className="row">
          <span className={`status ${backend}`} role="status">Processing API: {backend}</span>
          <button onClick={check}>Check connection</button>
        </div>
        {backend === 'offline' && <p className="notice">Local processing is unavailable. Start the frontend and Python API together with <code>npm run dev:full</code>, then check the connection again.</p>}
      </header>
      <PublishedObservations />
      <AnalysisWorkbench />
      <footer>
        <p>Exploratory analysis, not a Planet X detection service. Candidate rankings require scientific review.</p>
        <p>Coordinate search covers published targets only. Uploaded images are not automatically verified as SPHEREx observations.</p>
      </footer>
    </main>
  )
}
