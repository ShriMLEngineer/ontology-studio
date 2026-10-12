/**
 * End-to-end check of Phase 4.4/4.5 multi-graph deployment:
 *   KG build deploys to the embedded Oxigraph -> Deployments tab (verified counts, compatibility
 *   report, preview for kinds without adapter) -> a real Oxigraph SPARQL 1.1 server is registered and
 *   tested in Settings -> the build is deployed to it from the UI -> read-only SPARQL console (results,
 *   updates rejected) -> Graph Explorer reads the graph back from the endpoint with provenance ->
 *   endpoint outage reported honestly.
 *
 *   npm run e2e:graphs
 *
 * Requires the backend and the frontend dev server on a fresh, seeded database, and the `oxigraph`
 * server binary (installed into the backend virtualenv by `pip install -e .[dev]`; override with
 * E2E_OXIGRAPH_BIN). No LLM is used.
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, readFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SUPPLY = fileURLToPath(new URL('../../samples/supply-chain/', import.meta.url))
const STRUCTURED = ['suppliers.csv', 'products.csv', 'purchase_orders.csv', 'supply_relationships.csv']
const REVIEWER = 'E2E Graph Engineer'
const OXIGRAPH_BIN =
  process.env.E2E_OXIGRAPH_BIN ??
  fileURLToPath(new URL(`../../backend/.venv/${process.platform === 'win32' ? 'Scripts/oxigraph.exe' : 'bin/oxigraph'}`, import.meta.url))

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

const freePort = () =>
  new Promise((resolve, reject) => {
    const server = createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })

expect(existsSync(OXIGRAPH_BIN), `oxigraph server binary at ${OXIGRAPH_BIN} (pip install oxigraph or set E2E_OXIGRAPH_BIN)`)
await mkdir(ARTIFACTS, { recursive: true })
const browser = await chromium.launch({ channel: CHANNEL, headless: process.env.E2E_HEADED !== '1' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await context.newPage()
const consoleErrors = []
page.on('console', (msg) => msg.type() === 'error' && consoleErrors.push(msg.text()))
page.on('pageerror', (err) => consoleErrors.push(err.message))

let counter = 0
async function step(name, fn) {
  counter += 1
  const started = Date.now()
  try {
    await fn()
    console.log(`  ok ${String(counter).padStart(2)}. ${name} (${Math.round((Date.now() - started) / 100) / 10}s)`)
  } catch (error) {
    console.error(`  FAILED ${String(counter).padStart(2)}. ${name}`)
    await page.screenshot({ path: `${ARTIFACTS}p44-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}p44-${name}.png`, fullPage: true })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  const type = response.headers()['content-type'] ?? ''
  return { status: response.status(), body: type.includes('json') ? await response.json() : await response.text() }
}
const tab = (name) => page.getByRole('tab', { name })

let project
let version
let build
let server
let serverUrl
let sparqlDeployment

console.log(`Ontology Lifecycle Studio - Phase 4 multi-graph journey against ${BASE_URL}`)
try {
  await step('Seeded project: publish v1.0.0, upload the supply-chain CSVs and save mappings', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists (fresh seeded database)')
    const ontology = (await api('GET', `/projects/${project.id}/ontologies`)).body[0]
    const published = await api('POST', `/ontologies/${ontology.id}/versions`, {
      published_by: REVIEWER, version: '1.0.0', release_notes: 'E2E multi-graph',
    })
    expect(published.status === 201, `published: ${JSON.stringify(published.body).slice(0, 200)}`)
    version = published.body
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph`)
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: `Reviewer: ${REVIEWER}` }).waitFor()
  })

  await step('KG build with the embedded Oxigraph as graph target deploys and verifies automatically', async () => {
    const ids = []
    const mappingIds = []
    for (const name of STRUCTURED) {
      const response = await page.request.post(`${BASE_URL}/api/projects/${project.id}/sources`, {
        multipart: { file: { name, mimeType: 'text/csv', buffer: await readFile(`${SUPPLY}${name}`) } },
      })
      const document = await response.json()
      ids.push(document.id)
      const suggestion = (await api('GET', `/sources/${document.id}/mapping-suggestion?ontology_version_id=${version.id}`)).body
      const mapping = await api('POST', `/projects/${project.id}/kg/mappings`, {
        document_id: document.id, ontology_version_id: version.id, name: `${basename(name, '.csv')} mapping`,
        spec: suggestion.spec, updated_by: REVIEWER,
      })
      mappingIds.push(mapping.body.id)
    }
    const created = await api('POST', `/projects/${project.id}/kg/builds`, {
      name: 'Multi-graph build', ontology_version_id: version.id, source_document_ids: ids, mapping_ids: mappingIds,
      requested_by: REVIEWER, start: true, settings: { graph_connection_id: 'oxigraph-embedded' },
    })
    expect(created.status === 201, `build created: ${JSON.stringify(created.body).slice(0, 300)}`)
    for (let i = 0; i < 60; i += 1) {
      build = (await api('GET', `/kg/builds/${created.body.id}`)).body
      if (build.status === 'completed' || build.status === 'failed') break
      await page.waitForTimeout(500)
    }
    expect(build.status === 'completed', `build completed: ${build.error}`)
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph?build=${build.id}`)
    const stage = page.locator('[data-stage="graph_persistence"][data-stage-status="completed"]')
    await stage.waitFor()
    await stage.getByText(/Deployed to Embedded Oxigraph: \d+ triple\(s\), verified/).waitFor()
  })

  await step('Deployments tab: canonical and Oxigraph deployments verified, compatibility report shown', async () => {
    await tab('Deployments').click()
    const rows = page.getByTestId('deployment-row')
    await rows.first().waitFor()
    expect((await rows.count()) === 2, 'local SQL and Oxigraph deployments recorded by the build')
    await page.locator('[data-testid="deployment-row"][data-kind="oxigraph"][data-status="completed"]').waitFor()
    await page.locator('[data-testid="deployment-row"][data-kind="local-sql"][data-status="completed"]').waitFor()
    const report = page.getByTestId('compatibility-report').first()
    await report.getByText('Class hierarchy (rdfs:subClassOf)').waitFor()
    await report.getByText('Lexical form of typed values').waitFor()
    await report.getByText('oxigraph/1').waitFor()
    await shot('01-deployments')
  })

  await step('Deploy panel states the target\'s capabilities; unregistered providers are not deployment targets', async () => {
    const status = page.getByTestId('deploy-target-status')
    await status.waitFor()
    const text = await status.textContent()
    expect(text.includes('Registered') && text.includes('Deployment supported'), `capabilities shown: ${text}`)
    expect(
      !(await page.getByTestId('deploy-target').locator('option', { hasText: 'Neo4j' }).count()),
      'Neo4j is not offered as a deployment target until it is registered',
    )
  })

  await step('Start a real Oxigraph SPARQL 1.1 server and register it in Settings', async () => {
    const port = await freePort()
    const location = await mkdtemp(join(tmpdir(), 'ols-e2e-oxigraph-'))
    server = spawn(OXIGRAPH_BIN, ['serve', '--location', location, '--bind', `127.0.0.1:${port}`], { stdio: 'ignore' })
    serverUrl = `http://127.0.0.1:${port}`
    for (let i = 0; i < 100; i += 1) {
      try {
        const response = await fetch(`${serverUrl}/query?query=${encodeURIComponent('ASK {}')}`)
        if (response.status < 500) break
      } catch {
        /* not up yet */
      }
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
    await page.goto(`${BASE_URL}/projects/${project.id}/settings`)
    await page.getByRole('button', { name: 'Register database' }).click()
    const dialog = page.getByTestId('graph-dialog')
    await dialog.getByLabel('Graph database provider').selectOption('sparql-http')
    await dialog.getByLabel('Configuration name').fill('Oxigraph SPARQL server')
    await dialog.getByLabel('Query endpoint URL').fill(`${serverUrl}/query`)
    await dialog.getByLabel('Update endpoint URL (required to deploy)').fill(`${serverUrl}/update`)
    await dialog.getByRole('button', { name: 'Save' }).click()
    const row = page.getByTestId('graph-row').filter({ hasText: 'Oxigraph SPARQL server' })
    await row.getByRole('button', { name: 'Test' }).click()
    await row.locator('[data-testid="connection-test"][data-ok="true"]').waitFor({ timeout: 30_000 })
  })

  await step('Deploy the build to the SPARQL endpoint from the Deployments tab', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph?build=${build.id}&tab=deployments`)
    const target = page.getByTestId('deploy-target')
    const value = await target.locator('option', { hasText: 'Oxigraph SPARQL server' }).getAttribute('value')
    await target.selectOption(value)
    await page.getByTestId('compatibility-report').first().getByText('sparql-http/1').waitFor()
    await page.getByTestId('deploy-button').click()
    const row = page.locator('[data-testid="deployment-row"][data-kind="sparql-http"][data-status="completed"]')
    await row.waitFor({ timeout: 60_000 })
    const deployments = (await api('GET', `/kg/builds/${build.id}/deployments`)).body
    sparqlDeployment = deployments.find((d) => d.target_kind === 'sparql-http' && d.status === 'completed')
    expect(JSON.stringify(sparqlDeployment.stats.expected) === JSON.stringify(sparqlDeployment.stats.verified), 'verified counts')
    // Ask the server directly, outside the application.
    const direct = await fetch(`${serverUrl}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/sparql-results+json' },
      body: new URLSearchParams({
        query: `SELECT (COUNT(*) AS ?n) WHERE { GRAPH <${sparqlDeployment.graphs.data}> { ?s ?p ?o } }`,
      }),
    }).then((r) => r.json())
    expect(Number(direct.results.bindings[0].n.value) === sparqlDeployment.stats.verified.data, 'the endpoint holds the data graph')
    await shot('02-sparql-deployed')
  })

  await step('SPARQL console: entity counts per class, updates rejected before reaching the store', async () => {
    await page.locator('[data-testid="deployment-row"][data-kind="sparql-http"][data-status="completed"]').getByTestId('open-query').click()
    await page.getByLabel('Example queries').selectOption('Entities per class')
    await page.getByTestId('sparql-run').click()
    const results = page.getByTestId('sparql-results')
    await results.waitFor()
    const cells = await results.locator('tbody tr td:nth-child(2)').allTextContents()
    const total = cells.reduce((sum, value) => sum + Number(value), 0)
    expect(total === build.stats.graph.nodes, `entities per class sum to ${build.stats.graph.nodes} (got ${total})`)
    await page.getByTestId('sparql-summary').getByText('Oxigraph SPARQL server').waitFor()
    await shot('03-sparql-console')
    await page.getByTestId('sparql-text').fill('INSERT DATA { <urn:a> <urn:b> <urn:c> }')
    await page.getByTestId('sparql-run').click()
    await page.getByTestId('sparql-error').getByText(/Only read-only SPARQL 1\.1 queries/).waitFor()
  })

  await step('Graph Explorer reads the graph back from the endpoint, with fact provenance', async () => {
    await page.locator('[data-testid="deployment-row"][data-kind="sparql-http"][data-status="completed"]').getByTestId('open-explorer').click()
    await page.getByTestId('graph-source-note').getByText('Oxigraph SPARQL server').waitFor()
    const summary = await page.getByTestId('graph-summary').textContent()
    expect(summary.includes(`of ${build.stats.graph.nodes} nodes`) && summary.includes(`of ${build.stats.graph.edges} edges`), summary)
    await page.getByRole('button', { name: 'Table', exact: true }).click()
    await page.getByTestId('graph-edge-row').first().click()
    const details = page.locator('[data-testid="graph-details"][data-kind="edge"]')
    await details.getByText('Provenance and evidence').waitFor()
    await shot('04-explorer-from-endpoint')
    await page.getByRole('button', { name: 'Close panel' }).click()
    await page.getByTestId('graph-source').selectOption('')
    await page.getByTestId('graph-source-note').waitFor({ state: 'detached' })
  })

  await step('Endpoint outage: queries report the target as unreachable, nothing is simulated', async () => {
    server.kill()
    await new Promise((resolve) => setTimeout(resolve, 500))
    await tab('Deployments').click()
    await page.locator('[data-testid="deployment-row"][data-kind="sparql-http"][data-status="completed"]').getByTestId('open-query').click()
    await page.getByTestId('sparql-text').fill('ASK { ?s ?p ?o }')
    await page.getByTestId('sparql-run').click()
    await page.getByTestId('sparql-error').getByText(/unreachable/).waitFor({ timeout: 30_000 })
    const failed = await api('POST', `/kg/builds/${build.id}/deployments`, { target_id: sparqlDeployment.target_id, requested_by: REVIEWER })
    expect(failed.status === 201 && failed.body.status === 'failed', 'deployment to a stopped endpoint is recorded as failed')
  })

  const unexpected = consoleErrors.filter(
    (e) => !e.includes('Download the React DevTools') && !e.includes('status of 503') && !e.includes('status of 422'),
  )
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nPhase 4 multi-graph journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  server?.kill()
  await browser.close()
}
