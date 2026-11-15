import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
if (!existsSync(python)) {
  console.error('Python environment missing. See README.md: create .venv and install requirements.lock.txt.')
  process.exit(1)
}
const children = []
let stopping = false
function stop(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) child.kill('SIGTERM')
  process.exitCode = code
}
function start(command, args) {
  const child = spawn(command, args, { cwd: root, stdio: 'inherit' })
  children.push(child)
  child.on('error', (error) => { console.error(error.message); stop(1) })
  child.on('exit', (code) => { if (!stopping) stop(code || 1) })
  return child
}
process.on('SIGINT', () => stop())
process.on('SIGTERM', () => stop())

const api = start(python, ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', '8000'])
let ready = false
for (let attempt = 0; attempt < 120 && !stopping; attempt++) {
  if (api.exitCode !== null) break
  try {
    const response = await fetch('http://127.0.0.1:8000/api/health', { signal: AbortSignal.timeout(500) })
    if (response.ok && !stopping) { ready = true; break }
  } catch { /* API may still be importing the scientific libraries. */ }
  await new Promise((resolve) => setTimeout(resolve, 250))
}
if (ready && !stopping) {
  start(process.execPath, [path.join(root, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5173', '--strictPort'])
} else if (!stopping) {
  console.error('Processing API did not become ready. Check the server error above and whether port 8000 is in use.')
  stop(1)
}
