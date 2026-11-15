"use client";

import { useState, useEffect } from "react";
import { observations, targets } from "./data";

export default function Home() {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);

  const [ra, setRa] = useState("");
  const [dec, setDec] = useState("");
  const [error, setError] = useState("");
  const [searched, setSearched] = useState("");

  const [obs] = useState(observations);

  function handleTargetChange(name: string) {
    const t = targets.find((t) => t.name === name);
    if (t) {
      setRa(String(t.ra));
      setDec(String(t.dec));
      setError("");
    }
  }

  function handleSearch() {
    const r = Number(ra);
    const d = Number(dec);

    if (ra.trim() === "" || dec.trim() === "" || isNaN(r) || isNaN(d)) {
      setError("Enter a number for both RA and Dec.");
    } else if (r < 0 || r > 360) {
      setError("RA must be between 0 and 360.");
    } else if (d < -90 || d > 90) {
      setError("Dec must be between -90 and 90.");
    } else {
      setError("");
      setSearched(`RA ${r}, Dec ${d}`);
      setI(0);
      // Later: fetch real images for this position from the backend
    }
  }

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(
      () => setI((prev) => (prev + 1) % obs.length),
      700
    );
    return () => clearInterval(id);
  }, [playing, obs.length]);

  const current = obs[i];

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-2xl p-6">
        <h1 className="text-2xl font-bold">SPHEREx Sky Viewer</h1>
        <p className="mt-1 mb-6 text-sm text-slate-400">
          Pick a target or enter coordinates, then step through observations to
          see how that patch of sky changes over time.
        </p>

        <label className="block text-sm text-slate-300 mb-1" htmlFor="target">
          Target
        </label>
        <select
          id="target"
          defaultValue=""
          onChange={(e) => handleTargetChange(e.target.value)}
          className="mb-4 w-full rounded border border-slate-700 bg-slate-900 p-2"
        >
          <option value="">Choose a target...</option>
          {targets.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>

        <div className="flex gap-2">
          <input
            value={ra}
            onChange={(e) => setRa(e.target.value)}
            placeholder="RA (0 to 360)"
            inputMode="decimal"
            aria-label="Right ascension in degrees"
            className="w-1/3 rounded border border-slate-700 bg-slate-900 p-2"
          />
          <input
            value={dec}
            onChange={(e) => setDec(e.target.value)}
            placeholder="Dec (-90 to 90)"
            inputMode="decimal"
            aria-label="Declination in degrees"
            className="w-1/3 rounded border border-slate-700 bg-slate-900 p-2"
          />
          <button
            onClick={handleSearch}
            className="rounded bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-500"
          >
            Search
          </button>
        </div>

        {error && <p className="mt-2 text-red-400">{error}</p>}
        {searched && !error && (
          <p className="mt-2 text-sm text-slate-400">Showing {searched}</p>
        )}

        <img
          src={current.image}
          alt={`Sky on ${current.date}`}
          className="mt-6 w-full rounded"
        />
        <p className="mt-2">Date: {current.date}</p>
        <p className="text-xs text-amber-400">
          Test data. Real SPHEREx images are not connected yet.
        </p>

        <input
          type="range"
          min={0}
          max={obs.length - 1}
          value={i}
          onChange={(e) => setI(Number(e.target.value))}
          aria-label="Observation date"
          className="mt-3 w-full"
        />
        <button
          onClick={() => setPlaying(!playing)}
          className="mt-3 rounded bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-500"
        >
          {playing ? "Pause" : "Play"}
        </button>
      </div>
    </main>
  );
}
