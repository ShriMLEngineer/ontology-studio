/**
 * End-to-end check of the Project Lifecycle Navigator (Project Workspace):
 *   iteration 1 statuses follow real work (publication, mappings, KG build, deployment) ->
 *   a new source makes the build outdated -> a new iteration starts at "KG build" from the dialog,
 *   reusing the earlier outputs -> iteration 1 stays frozen -> a build in iteration 2 completes the
 *   stage -> the stage detail links to the work in Knowledge Graph Studio.
 *
 *   npm run e2e:lifecycle
 *
 * Requires the backend and the frontend dev server on a fresh, seeded database. No LLM is used.
 */
import { mkdir, readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SUPPLY = fileURLToPath(new URL('../../samples/supply-chain/', import.meta.url))
const STRUCTURED = ['suppliers.csv', 'products.csv', 'purchase_orders.csv', 'supply_relationships.csv']
const REVIEWER = 'E2E Lifecycle Lead'

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

await mkdir(ARTIFACTS, { recursive: true })
const browser = await chromium.launch({ channel: CHANNEL, headless: process.env.E2E_HEADED !== '1' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1100 } })
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
    await page.screenshot({ path: `${ARTIFACTS}lifecycle-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}lifecycle-${name}.png`, fullPage: true })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  const type = response.headers()['content-type'] ?? ''
  return { status: response.status(), body: type.includes('json') ? await response.json() : await response.text() }
}
const stage = (key) => page.getByTestId(`lifecycle-stage-${key}`)
const statusOf = async (key) => stage(key).getAttribute('data-status')
async function waitStatus(key, status) {
  await page.locator(`[data-testid="lifecycle-stage-${key}"][data-status="${status}"]`).waitFor({ timeout: 15_000 })
}

let project
let version
const documentIds = []
const mappingIds = []

async function build(name) {
  const created = await api('POST', `/projects/${project.id}/kg/builds`, {
    name, ontology_version_id: version.id, source_document_ids: documentIds, mapping_ids: mappingIds,
    requested_by: REVIEWER, start: true, settings: { graph_connection_id: 'oxigraph-embedded' },
  })
  expect(created.status === 201, `build created: ${JSON.stringify(created.body).slice(0, 300)}`)
  let result
  for (let i = 0; i < 60; i += 1) {
    result = (await api('GET', `/kg/builds/${created.body.id}`)).body
    if (result.status === 'completed' || result.status === 'failed') break
    await page.waitForTimeout(500)
  }
  expect(result.status === 'completed', `build completed: ${result.error}`)
  return result
}

console.log(`Ontology Lifecycle Studio - lifecycle navigator journey against ${BASE_URL}`)
try {
  await step('Workspace shows iteration 1 with the lifecycle as a graphical workflow', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists (fresh seeded database)')
    await page.goto(`${BASE_URL}/projects/${project.id}`)
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByTestId('lifecycle-navigator').waitFor()
    await page.getByTestId('iteration-1').waitFor()
    expect((await page.locator('[data-testid^="lifecycle-stage-"][data-status]').count()) === 9, 'nine stages')
    expect((await statusOf('publication')) === 'pending', 'nothing published yet')
    expect((await statusOf('kg_build')) === 'pending', 'no build yet')
  })

  await step('Publication, sources and mappings complete their stages', async () => {
    const ontology = (await api('GET', `/projects/${project.id}/ontologies`)).body[0]
    version = (await api('POST', `/ontologies/${ontology.id}/versions`, {
      published_by: REVIEWER, version: '1.0.0', release_notes: 'E2E lifecycle',
    })).body
    for (const name of STRUCTURED) {
      const response = await page.request.post(`${BASE_URL}/api/projects/${project.id}/sources`, {
        multipart: { file: { name, mimeType: 'text/csv', buffer: await readFile(`${SUPPLY}${name}`) } },
      })
      const document = await response.json()
      documentIds.push(document.id)
      const suggestion = (await api('GET', `/sources/${document.id}/mapping-suggestion?ontology_version_id=${version.id}`)).body
      const mapping = await api('POST', `/projects/${project.id}/kg/mappings`, {
        document_id: document.id, ontology_version_id: version.id, name: `${basename(name, '.csv')} mapping`,
        spec: suggestion.spec, updated_by: REVIEWER,
      })
      mappingIds.push(mapping.body.id)
    }
    await page.reload()
    await waitStatus('sources', 'completed')
    await waitStatus('publication', 'completed')
    await waitStatus('mapping', 'completed')
    await waitStatus('kg_build', 'pending')
  })

  await step('A KG build completes the build and deployment stages', async () => {
    await build('Iteration 1 build')
    await page.reload()
    await waitStatus('kg_build', 'completed')
    await waitStatus('deployment', 'completed')
    await stage('deployment').click()
    await page.getByTestId('lifecycle-stage-summary').getByText(/verified in Embedded Oxigraph/).waitFor()
    await shot('01-iteration-1')
  })

  await step('A new source outdates the build; the stage explains why', async () => {
    await page.request.post(`${BASE_URL}/api/projects/${project.id}/sources`, {
      multipart: { file: { name: 'warehouses.csv', mimeType: 'text/csv', buffer: Buffer.from('id,name\nW-1,North hub\n') } },
    })
    await page.reload()
    await waitStatus('kg_build', 'outdated')
    await waitStatus('deployment', 'outdated')
    await stage('kg_build').click()
    await page.getByTestId('lifecycle-stage-summary').getByText(/1 source\(s\) uploaded after build #1/).waitFor()
  })

  await step('Start iteration 2 at "KG build" from the dialog, reusing earlier outputs', async () => {
    await page.getByTestId('new-iteration').click()
    const dialog = page.getByTestId('iteration-dialog')
    await dialog.getByRole('radio', { name: 'KG build' }).check()
    await dialog.getByTestId('iteration-reuses').getByText('Publication: published v1.0.0.').waitFor()
    await dialog.getByLabel('Name').fill('Refresh the graph')
    await dialog.getByLabel('Goal').fill('Rebuild with the new warehouse data')
    await shot('02-start-dialog')
    await dialog.getByTestId('iteration-start').click()
    await page.getByTestId('iteration-2').waitFor()
    expect((await page.getByTestId('iteration-2').getAttribute('aria-selected')) === 'true', 'iteration 2 selected')
    for (const key of ['sources', 'validation', 'publication']) await waitStatus(key, 'reused')
    await waitStatus('kg_build', 'pending')
    await stage('publication').click()
    await page.getByTestId('lifecycle-stage-detail').getByText('Output of iteration #1: published v1.0.0.').waitFor()
    await page.getByTestId('iteration-meta').getByText('continues iteration #1').waitFor()
  })

  await step('Iteration 1 is closed and frozen exactly as it ended', async () => {
    await page.getByTestId('iteration-1').click()
    await page.getByTestId('iteration-frozen').waitFor()
    await waitStatus('kg_build', 'outdated')
    await waitStatus('publication', 'completed')
    await stage('kg_build').click()
    await page.getByTestId('lifecycle-stage-detail').waitFor()
    expect(!(await page.getByTestId('lifecycle-stage-detail').getByRole('link', { name: 'Open' }).count()), 'no actions on history')
    await shot('03-iteration-1-frozen')
  })

  await step('A build in iteration 2 completes its stages; iteration 1 is unchanged', async () => {
    await build('Iteration 2 build')
    await page.getByTestId('iteration-2').click()
    await page.reload()
    await waitStatus('kg_build', 'completed')
    await waitStatus('deployment', 'completed')
    await stage('kg_build').click()
    const detail = page.getByTestId('lifecycle-stage-detail')
    await detail.getByText(/Build #2/).first().waitFor()
    await shot('04-iteration-2')
    await page.getByTestId('iteration-1').click()
    await page.getByTestId('iteration-frozen').waitFor()
    await waitStatus('kg_build', 'outdated')
  })

  await step('Stage detail opens the place where the work happens', async () => {
    await page.getByTestId('iteration-2').click()
    await waitStatus('kg_build', 'completed')
    await stage('deployment').click()
    await page.getByTestId('lifecycle-stage-detail').getByRole('link', { name: 'Open' }).click()
    await page.waitForURL(/knowledge-graph\?tab=deployments&build=/)
    await page.getByTestId('deployments-table').waitFor()
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nLifecycle navigator journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
