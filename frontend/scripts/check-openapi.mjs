import { readFileSync, rmSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const frontendDir = resolve(import.meta.dirname, '..')
const files = ['openapi.json', 'src/api/generated/schema.d.ts']
const before = new Map(files.map((file) => [file, readFileSync(resolve(frontendDir, file), 'utf8')]))
// Keep the temporary path below the workspace. Some Windows OpenAPI tooling does not
// decode non-ASCII characters in file:// URLs used for the user's system temp path.
const generatedOpenApi = resolve(frontendDir, `openapi.check.${process.pid}.json`)
const generatedSchema = resolve(frontendDir, `schema.check.${process.pid}.d.ts`)

try {
  const exportResult = spawnSync(
    process.execPath,
    ['scripts/export-openapi.mjs', generatedOpenApi],
    { cwd: frontendDir, stdio: 'inherit' },
  )
  if (exportResult.error) throw exportResult.error
  if (exportResult.status !== 0) process.exit(exportResult.status ?? 1)

  const generateResult = spawnSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', generatedOpenApi, '-o', generatedSchema],
    { cwd: frontendDir, stdio: 'inherit' },
  )
  if (generateResult.error) throw generateResult.error
  if (generateResult.status !== 0) process.exit(generateResult.status ?? 1)

  const generated = new Map([
    ['openapi.json', readFileSync(generatedOpenApi, 'utf8')],
    ['src/api/generated/schema.d.ts', readFileSync(generatedSchema, 'utf8')],
  ])
  const changed = files.filter((file) => before.get(file) !== generated.get(file))
  if (changed.length) {
    console.error(`OpenAPI contract drift detected: ${changed.join(', ')}`)
    console.error('Commit the regenerated contract files after reviewing frontend compatibility.')
    process.exitCode = 1
  } else {
    console.log('OpenAPI contract is up to date.')
  }
} finally {
  rmSync(generatedOpenApi, { force: true })
  rmSync(generatedSchema, { force: true })
}
