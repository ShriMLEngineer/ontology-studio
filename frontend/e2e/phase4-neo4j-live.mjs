/**
 * Live Neo4j (AuraDB or self-hosted) journey through the real UI - skipped unless E2E_NEO4J_URI is set:
 *   Settings: register Neo4j from the provider dropdown -> Test Connection (real, read-only) ->
 *   KG build -> Deployments tab: the target's capabilities are stated -> deploy to Neo4j (counts verified) ->
 *   Graph Explorer reads the graph back from Neo4j with provenance -> the build's scope is removed again.
 *
 *   E2E_NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io  E2E_NEO4J_PASSWORD_VAR=NEO4J_PASSWORD  npm run e2e:neo4j
 *
 * The *backend* process must have the password in the environment variable named by
 * E2E_NEO4J_PASSWORD_VAR (default NEO4J_PASSWORD) - it is never typed into the UI. Optional:
 * E2E_NEO4J_USERNAME (neo4j), E2E_NEO4J_DATABASE (neo4j). When E2E_NEO4J_PASSWORD (the value) is also set,
 * the build's scope is deleted afterwards through the Neo4j HTTP Query API; otherwise the Cypher to run is printed.
 * Requires a fresh, seeded database. Only nodes labelled OlsVertex with the build's scope are ever touched.
 */
import { mkdir, readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const NEO4J_URI = process.env.E2E_NEO4J_URI
if (!NEO4J_URI) {
  console.log('E2E_NEO4J_URI is not set; live Neo4j journey skipped.')
  process.exit(0)
}
const USERNAME = process.env.E2E_NEO4J_USERNAME ?? 'neo4j'
const DATABASE = process.env.E2E_NEO4J_DATABASE ?? 'neo4j'
const PASSWORD_VAR = process.env.E2E_NEO4J_PASSWORD_VAR ?? 'NEO4J_PASSWORD'
const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SUPPLY = fileURLToPath(new URL('../../samples/supply-chain/', import.meta.url))
const STRUCTURED = ['suppliers.csv', 'products.csv', 'purchase_orders.csv', 'supply_relationships.csv']
const REVIEWER = 'E2E Graph Engineer'
const CONNECTION = 'Neo4j (live E2E)'

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

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
    await page.screenshot({ path: `${ARTIFACTS}neo4j-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}neo4j-${name}.png`, fullPage: true })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  const type = response.headers()['content-type'] ?? ''
  return { status: response.status(), body: type.includes('json') ? await response.json() : await response.text() }
}
const tab = (name) => page.getByRole('tab', { name })

let project
let version
let build

async function cleanup() {
  if (!build) return
  const statement = 'MATCH (n:OlsVertex {_ols_scope: $scope}) DETACH DELETE n'
  const password = process.env.E2E_NEO4J_PASSWORD
  if (!password) {
    console.log(`  Remove the test data with: ${statement}  (scope = ${build.id})`)
    return
  }
  const host = new URL(NEO4J_URI.replace(/^neo4j\+s|^bolt\+s/, 'https')).host
  const response = await fetch(`https://${host}/db/${DATABASE}/query/v2`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Basic ${Buffer.from(`${USERNAME}:${password}`).toString('base64')}`,
    },
    body: JSON.stringify({ statement, parameters: { scope: build.id } }),
  })
  console.log(response.ok ? `  Test scope ${build.id} removed from Neo4j.` : `  Cleanup failed (HTTP ${response.status}); run: ${statement}`)
}

console.log(`Ontology Lifecycle Studio - live Neo4j journey against ${BASE_URL} (${NEO4J_URI})`)
try {
  await step('Seeded project: publish v1.0.0, upload the supply-chain CSVs, build the knowledge graph locally', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists (fresh seeded database)')
    const ontology = (await api('GET', `/projects/${project.id}/ontologies`)).body[0]
    const published = await api('POST', `/ontologies/${ontology.id}/versions`, {
      published_by: REVIEWER, version: '1.0.0', release_notes: 'E2E live Neo4j',
    })
    expect(published.status === 201, `published: ${JSON.stringify(published.body).slice(0, 200)}`)
    version = published.body
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
      name: 'Live Neo4j build', ontology_version_id: version.id, source_document_ids: ids, mapping_ids: mappingIds,
      requested_by: REVIEWER, start: true,
    })
    expect(created.status === 201, `build created: ${JSON.stringify(created.body).slice(0, 300)}`)
    for (let i = 0; i < 60; i += 1) {
      build = (await api('GET', `/kg/builds/${created.body.id}`)).body
      if (build.status === 'completed' || build.status === 'failed') break
      await page.waitForTimeout(500)
    }
    expect(build.status === 'completed', `build completed: ${build.error}`)
  })

  await step('Settings: register Neo4j from the provider dropdown and run the real connection test', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph`)
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: `Reviewer: ${REVIEWER}` }).waitFor()
    await page.goto(`${BASE_URL}/projects/${project.id}/settings`)
    await page.getByRole('button', { name: 'Register database' }).click()
    const dialog = page.getByTestId('graph-dialog')
    await dialog.getByLabel('Graph database provider').selectOption('neo4j')
    await dialog.getByLabel('Configuration name').fill(CONNECTION)
    await dialog.getByLabel('Bolt URI').fill(NEO4J_URI)
    await dialog.getByLabel('Database name').fill(DATABASE)
    await dialog.getByLabel('User name').fill(USERNAME)
    await dialog.getByLabel('Password (environment variable name)').fill(PASSWORD_VAR)
    await dialog.getByRole('button', { name: 'Save' }).click()
    const row = page.getByTestId('graph-row').filter({ hasText: CONNECTION })
    await row.waitFor()
    expect((await row.getByTestId('graph-status').textContent()) === 'Not tested', 'a new registration is not tested')
    await row.getByRole('button', { name: 'Test' }).click()
    await row.locator('[data-testid="connection-test"][data-ok="true"]').waitFor({ timeout: 60_000 })
    expect((await row.getByTestId('graph-status').textContent()) === 'Connected', 'status Connected')
    const chips = await row.getByTestId('graph-capabilities').textContent()
    expect(chips.includes('Deployment supported') && chips.includes('Adapter live-tested'), `capabilities: ${chips}`)
    expect(!(await row.locator('[data-testid="graph-capabilities"] >> text=Deployment verified').evaluate((el) => el.className.includes('emerald'))),
      'connected is not deployment verified')
    await shot('01-settings')
  })

  await step('Deployments tab: capabilities are stated, then deploy to Neo4j with verified counts', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph?build=${build.id}&tab=deployments`)
    const target = page.getByTestId('deploy-target')
    const value = await target.locator('option', { hasText: CONNECTION }).getAttribute('value')
    await target.selectOption(value)
    const status = page.getByTestId('deploy-target-status')
    await status.getByTestId('graph-status').filter({ hasText: 'Connected' }).waitFor()
    await page.getByTestId('compatibility-report').first().getByText('neo4j/2').waitFor()
    await page.getByTestId('deploy-button').click()
    const row = page.locator('[data-testid="deployment-row"][data-kind="neo4j"][data-status="completed"]')
    await row.waitFor({ timeout: 120_000 })
    const deployments = (await api('GET', `/kg/builds/${build.id}/deployments`)).body
    const deployment = deployments.find((d) => d.target_kind === 'neo4j' && d.status === 'completed')
    expect(JSON.stringify(deployment.stats.expected) === JSON.stringify(deployment.stats.verified), 'verified counts equal expected')
    expect(deployment.stats.verified.vertices === build.stats.graph.nodes, 'every node is in Neo4j')
    await shot('02-deployed')
  })

  await step('Graph Explorer reads the graph back from Neo4j, with fact provenance', async () => {
    await page.locator('[data-testid="deployment-row"][data-kind="neo4j"][data-status="completed"]').getByTestId('open-explorer').click()
    await page.getByTestId('graph-source-note').getByText(CONNECTION).waitFor()
    const summary = await page.getByTestId('graph-summary').textContent()
    expect(summary.includes(`of ${build.stats.graph.nodes} nodes`) && summary.includes(`of ${build.stats.graph.edges} edges`), summary)
    await page.getByRole('button', { name: 'Table', exact: true }).click()
    await page.getByTestId('graph-edge-row').first().click()
    await page.locator('[data-testid="graph-details"][data-kind="edge"]').getByText('Provenance and evidence').waitFor()
    await shot('03-explorer-from-neo4j')
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log('\nLive Neo4j journey passed.')
} finally {
  await cleanup().catch((error) => console.log(`  Cleanup error: ${error.message}`))
  await browser.close()
}
