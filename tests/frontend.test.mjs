import assert from 'node:assert/strict'
import test from 'node:test'
import { angularDistance, searchTargets } from '../src/services/targets.ts'
import { parseAnalysis } from '../src/services/analysis.ts'
import { parseManifest } from '../src/services/observations.ts'

test('coordinate matching handles RA wrap and the poles', () => {
  assert.ok(Math.abs(angularDistance(359.9, 0, 0.1, 0) - 0.2) < 1e-9)
  assert.ok(angularDistance(0, 90, 180, 90) < 1e-9)
  const target = { id: 'test-only', raDegrees: 0.1, decDegrees: 0 }
  assert.equal(searchTargets([target], 359.9, 0, 13).length, 1)
  assert.equal(searchTargets([target], 359.9, 0, 5).length, 0)
})

test('manifest distinguishes valid empty data from invalid data', () => {
  assert.deepEqual(parseManifest({ schemaVersion: 1, targets: [] }).targets, [])
  assert.throws(() => parseManifest({ schemaVersion: 2, targets: [] }))
  assert.throws(() => parseManifest({ schemaVersion: 1, targets: null }))
})

test('analysis parser rejects incompatible responses and cross-origin artifact paths', () => {
  assert.throws(() => parseAnalysis({}))
  assert.throws(() => parseAnalysis({ schemaVersion: 1, id: 'a'.repeat(32), baseUrl: 'https://example.org/' }))
})
