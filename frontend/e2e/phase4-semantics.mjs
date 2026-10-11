/**
 * End-to-end check of the Phase 4 semantic journey (Ontology Studio > RDF / OWL, Registry):
 * OWL export of the draft -> lossless RDF import with report -> preserved axioms -> OWL 2 RL
 * reasoning preview -> designer deletion orphans a preserved axiom -> publication blocked ->
 * axiom resolved -> ols-semantic/2 package published with four RDF syntaxes.
 *
 *   npm run e2e:semantic
 *
 * Requires the backend and the frontend dev server on a fresh, seeded database (it imports a new
 * ontology and publishes a version). No LLM is used.
 */
import { mkdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SAMPLE = fileURLToPath(new URL('../../samples/party-ontology.ttl', import.meta.url))
const REVIEWER = 'E2E Ontologist'

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

await mkdir(ARTIFACTS, { recursive: true })
const browser = await chromium.launch({ channel: CHANNEL, headless: process.env.E2E_HEADED !== '1' })
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true })
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
    console.log(`  âœ” ${String(counter).padStart(2)}. ${name} (${Math.round((Date.now() - started) / 100) / 10}s)`)
  } catch (error) {
    console.error(`  âœ˜ ${String(counter).padStart(2)}. ${name}`)
    await page.screenshot({ path: `${ARTIFACTS}p4-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}p4-${name}.png` })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  const type = response.headers()['content-type'] ?? ''
  return { status: response.status(), body: type.includes('json') ? await response.json() : await response.text() }
}
const tab = (name) => page.getByRole('tab', { name })

let project
let imported
let report

console.log(`Ontology Lifecycle Studio - Phase 4 semantic journey against ${BASE_URL}`)
try {
  await step('Open the RDF / OWL tab of Ontology Studio and identify the reviewer', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists')
    await page.goto(`${BASE_URL}/projects/${project.id}/ontology?tab=semantics`)
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: `Reviewer: ${REVIEWER}` }).waitFor()
    await tab('RDF / OWL').waitFor()
  })

  await step('Draft OWL export: required/single-value switches are not OWL axioms (D2)', async () => {
    const preview = page.getByTestId('rdf-preview')
    await preview.waitFor()
    const turtle = await preview.textContent()
    expect(turtle.includes('owl:Class') && turtle.includes('sc:Supplier'), 'Turtle preview lists classes')
    expect(!turtle.includes('owl:FunctionalProperty'), 'no derived owl:FunctionalProperty in the v2 profile')
    expect(!turtle.includes('owl:minCardinality'), 'no derived owl:minCardinality in the v2 profile')
    await page.getByRole('combobox', { name: 'Preview format' }).click()
    await page.getByRole('option', { name: 'RDF/XML' }).click()
    await page.getByTestId('rdf-preview').filter({ hasText: 'rdf:RDF' }).waitFor()
    await shot('01-export')
  })

  await step('Import an OWL ontology without semantic loss', async () => {
    await page.locator('#rdf-file').setInputFiles(SAMPLE)
    await page.getByRole('button', { name: 'Import as new ontology' }).click()
    const reportView = page.getByTestId('rdf-import-card').getByTestId('import-report')
    await reportView.waitFor({ timeout: 30_000 })
    const text = await reportView.textContent()
    expect(text.includes('No semantic loss'), 'import reports no semantic loss')
    expect(text.includes('owl-class-expression') && text.includes('shacl-shape'), 'preserved constructs are classified')
    const ontologies = (await api('GET', `/projects/${project.id}/ontologies`)).body
    imported = ontologies.find((o) => o.name === 'Party Model')
    expect(imported && imported.ontology_iri === 'https://example.org/party', 'imported ontology keeps its ontology IRI')
    report = (await api('GET', `/ontologies/${imported.id}/imports`)).body[0].report
    expect(report.lossless && report.superseded_triples === 1, 'versionInfo is the only superseded triple')
    await shot('02-import-report')
  })

  await step('Open the imported ontology: preserved axioms are listed', async () => {
    await page.getByRole('button', { name: 'Open imported ontology' }).click()
    await page.getByRole('heading', { name: 'Party Model' }).waitFor()
    await page.getByRole('combobox', { name: 'Switch ontology' }).waitFor()
    const rows = page.getByTestId('axiom-row')
    await rows.first().waitFor()
    expect((await rows.count()) === report.preserved_axioms, `${report.preserved_axioms} preserved axioms listed`)
    expect((await page.getByTestId('axioms-card').getByText('Orphaned').count()) === 0, 'no orphaned axioms after import')
  })

  await step('OWL 2 RL reasoning preview is informational and consistent', async () => {
    await page.getByRole('button', { name: /Run reasoner/ }).click()
    await page.getByTestId('reasoner-consistent').waitFor({ timeout: 30_000 })
    const entailments = await page.getByRole('list', { name: 'Entailments' }).textContent()
    expect(entailments.includes('ex:acme rdf:type ex:Party'), 'individual typed via the class hierarchy')
    const draft = (await api('GET', `/ontologies/${imported.id}/draft`)).body
    expect(draft.draft_revision === imported.draft_revision, 'reasoning did not change the draft')
    await shot('03-axioms-reasoning')
  })

  await step('Deleting a class in the designer orphans its preserved axiom', async () => {
    await tab('Ontology Designer').click()
    await page.locator('[data-testid="class-node-KeyParty"]').click()
    await page.getByRole('button', { name: 'Delete class' }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Delete class' }).click()
    await page.getByRole('button', { name: 'Save draft' }).click()
    await page.getByText('Unsaved changes').first().waitFor({ state: 'detached' })
    await tab('RDF / OWL').click()
    await page.getByTestId('axioms-card').getByText('Orphaned').waitFor()
  })

  await step('Publication is blocked by the orphaned axiom', async () => {
    await tab('Registry').click()
    const gate = page.getByTestId('publish-validation')
    await gate.filter({ hasText: 'Blocked by' }).waitFor()
    expect((await gate.textContent()).includes('Preserved axiom'), 'blocking issue names the preserved axiom')
    expect(await page.getByRole('button', { name: /^Publish v/ }).isDisabled(), 'publish button disabled')
  })

  await step('The SME removes the orphaned axiom (audited)', async () => {
    await tab('RDF / OWL').click()
    const orphan = page.getByTestId('axiom-row').filter({ hasText: 'Orphaned' })
    await orphan.getByRole('button', { name: /Remove axiom/ }).click()
    await page.getByRole('alertdialog').getByRole('button', { name: 'Remove axiom' }).click()
    await page.getByTestId('axioms-card').getByText('Orphaned').waitFor({ state: 'detached' })
    const activity = (await api('GET', `/projects/${project.id}/activity?limit=5`)).body
    expect(activity.some((e) => e.event_type === 'ontology.axiom_removed'), 'removal recorded in the activity log')
  })

  await step('Publish an ols-semantic/2 package with four RDF syntaxes', async () => {
    await tab('Registry').click()
    await page.getByTestId('publish-validation').filter({ hasText: 'Validation gate passed' }).waitFor()
    await page.getByLabel('Release notes').fill('Imported party model')
    await page.getByRole('button', { name: /^Publish v1\.0\.0/ }).click()
    const row = page.getByTestId('version-row').first()
    await row.getByText('ols-semantic/2').waitFor()
    for (const label of ['Turtle (.ttl)', 'RDF/XML', 'JSON-LD', 'N-Triples', 'Manifest']) {
      await row.getByRole('link', { name: label }).waitFor()
    }
    const version = (await api('GET', `/ontologies/${imported.id}/versions`)).body[0]
    const turtle = await api('GET', `/ontologies/${imported.id}/versions/${version.id}/export?format=turtle`)
    expect(turtle.body.includes('ex:steward') && turtle.body.includes('owl:unionOf') === false, 'preserved axioms published; removed axiom not')
    expect(turtle.body.includes('owl:versionInfo "1.0.0"'), 'registry version header')
    await shot('04-published-package')
  })

  await step('Original sample triples survive the full round trip', async () => {
    const version = (await api('GET', `/ontologies/${imported.id}/versions`)).body[0]
    const ntriples = (await api('GET', `/ontologies/${imported.id}/versions/${version.id}/export?format=ntriples`)).body
    const source = await readFile(SAMPLE, 'utf8')
    expect(source.includes('Master data team') && ntriples.includes('"Master data team"'), 'custom annotation survives')
    expect(ntriples.includes('"Partei"@de'), 'second-language label survives')
    expect(ntriples.includes('<http://www.w3.org/2002/07/owl#minQualifiedCardinality>'), 'qualified restriction survives')
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nPhase 4 semantic journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
