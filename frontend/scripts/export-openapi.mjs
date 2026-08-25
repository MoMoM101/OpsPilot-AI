import { existsSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const frontendDir = resolve(import.meta.dirname, '..')
const workspaceDir = resolve(frontendDir, '..')
const backendDir = resolve(workspaceDir, 'backend')
const outputPath = process.argv[2]
  ? resolve(frontendDir, process.argv[2])
  : resolve(frontendDir, 'openapi.json')
const candidates = process.platform === 'win32'
  ? [resolve(workspaceDir, '.venv', 'Scripts', 'python.exe'), 'python']
  : [resolve(workspaceDir, '.venv', 'bin', 'python'), 'python3', 'python']
const python = candidates.find((candidate) => !candidate.includes('/') && !candidate.includes('\\') || existsSync(candidate))

if (!python) throw new Error('Python runtime not found; activate the backend virtual environment first.')

const result = spawnSync(python, ['scripts/export_openapi.py', '-'], {
  cwd: backendDir,
  encoding: 'utf8',
})
if (result.error) throw result.error
if (result.status !== 0) {
  process.stderr.write(result.stderr)
  process.exit(result.status ?? 1)
}
writeFileSync(outputPath, result.stdout, 'utf8')
