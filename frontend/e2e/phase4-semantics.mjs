/**
 * End-to-end check of the Phase 4 semantic journey:
 * 4.1  OWL export of the draft -> lossless RDF import with report -> preserved axioms -> OWL 2 RL
 *      reasoning preview -> designer deletion orphans a preserved axiom -> publication blocked ->
 *      axiom resolved -> ols-semantic/2 package published with four RDF syntaxes.
 * 4.2  SHACL Shapes tab -> authored shape -> sample-data validation -> shapes.ttl in the package ->
 *      KG build under a SHACL validation policy -> per-fact SHACL lane in Fact Validation.
 * 4.3  Inspector "Advanced semantics": locked IRI after publication, disjointness and a restriction,
 *      canvas badges, OWL export; Validation tab with separate SHACL and OWL 2 RL lanes.
 * Settings: fourth navigation section -> register and really test an LLM (local Ollama by default,
 *      E2E_LLM_BASE_URL / E2E_LLM_MODEL) -> built-in Oxigraph -> unreachable SPARQL endpoint reported ->
 *      project default resolved by discovery.
 *
 *   npm run e2e:semantic
 *
 * Requires the backend and the frontend dev server on a fresh, seeded database (it imports a new
 * ontology and publishes a version). No LLM is used.
 */
import { mkdir, readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SAMPLE = fileURLToPath(new URL('../../samples/party-ontology.ttl', import.meta.url))
const SUPPLY = fileURLToPath(new URL('../../samples/supply-chain/', import.meta.url))
const STRUCTURED = ['suppliers.csv', 'products.csv', 'purchase_orders.csv', 'supply_relationships.csv']
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
let supplyChain
let build

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

  // ------------------------------------------------------------------ milestone 4.2: SHACL

  await step('SHACL Shapes tab: generated shapes are well formed', async () => {
    supplyChain = (await api('GET', `/projects/${project.id}/ontologies`)).body.find((o) => o.name === 'Supply Chain Core')
    await page.goto(`${BASE_URL}/projects/${project.id}/ontology?ontology=${supplyChain.id}&tab=shapes`)
    await page.getByTestId('shapes-well-formed').waitFor()
    await page.getByTestId('generated-shapes').locator('summary').filter({ hasText: /^Product/ }).waitFor()
  })

  await step('Author a SHACL shape in the form editor', async () => {
    await page.getByRole('button', { name: 'New shape' }).click()
    const dialog = page.getByTestId('shape-dialog')
    await dialog.getByLabel('Label').fill('Supplier naming')
    await dialog.locator('#shape-target').click()
    await page.getByRole('option', { name: 'Supplier', exact: true }).click()
    await dialog.getByLabel('Message shown for results').fill("Legal names must start with 'Zz'.")
    await dialog.getByRole('combobox', { name: 'Constraint 1 property' }).click()
    await page.getByRole('option', { name: /^legal name . attribute of Organization/ }).click()
    await dialog.getByLabel('Pattern (regular expression)').fill('^Zz')
    await dialog.getByRole('button', { name: 'Save shape' }).click()
    await page.getByTestId('authored-shape-row').filter({ hasText: 'Supplier naming' }).waitFor()
    expect((await page.getByTestId('authored-shape-row').textContent()).includes('pattern /^Zz/'), 'constraint summary')
  })

  await step('Validate sample data against the draft shapes (no inference)', async () => {
    const sample = `@prefix sc: <https://example.com/ontology/supply-chain#> . @prefix d: <https://example.org/d/> .
d:s1 a sc:Supplier ; sc:legalName "Contoso" .`
    await page.getByLabel('Sample data (Turtle)').fill(sample)
    await page.getByRole('button', { name: 'Validate', exact: true }).click()
    const result = page.getByTestId('shacl-report')
    await result.getByText('Does not conform').waitFor()
    const text = await result.textContent()
    expect(text.includes('Pattern') && text.includes('authored'), 'authored pattern violation reported')
    await shot('05-shapes')
  })

  await step('Publish Supply Chain v1.0.0: the package includes shapes.ttl', async () => {
    await tab('Registry').click()
    await page.getByTestId('publish-validation').filter({ hasText: 'Validation gate passed' }).waitFor()
    await page.getByRole('button', { name: /^Publish v1\.0\.0/ }).click()
    await page.getByTestId('version-row').first().getByRole('link', { name: 'SHACL shapes' }).waitFor()
    const version = (await api('GET', `/ontologies/${supplyChain.id}/versions`)).body[0]
    const shapes = await api('GET', `/ontologies/${supplyChain.id}/versions/${version.id}/export?format=shapes`)
    expect(shapes.body.includes('sh:pattern "^Zz"'), 'authored shape materialised in the version package')
    supplyChain.version = version
  })

  await step('Advanced semantics in the inspector: locked IRI, disjointness, a restriction; canvas badges', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/ontology?ontology=${supplyChain.id}&tab=designer`)
    await page.locator('[data-testid="class-node-Supplier"]').click()
    await page.getByTestId('iri-status').getByText('IRI locked (published in v1.0.0)').waitFor()
    const section = page.getByTestId('class-semantics')
    await section.getByRole('button', { name: /Advanced semantics/ }).click()
    await section.locator('#cls-disjoint').selectOption({ label: 'Product' })
    await section.getByRole('button', { name: 'Add restriction' }).click()
    const restriction = section.getByTestId('restriction-editor')
    await restriction.getByLabel('Restricted property').selectOption({ label: 'supplies' })
    await restriction.getByLabel('Restriction kind').selectOption('some')
    await restriction.getByText("Every Supplier has at least one 'supplies' that is a Product.").waitFor()
    await shot('05a-advanced-semantics')
    await page.getByRole('button', { name: 'Save draft' }).click()
    await page.getByText('Unsaved changes').first().waitFor({ state: 'detached' })
    const marks = page.locator('[data-testid="class-node-Supplier"] [data-testid="semantic-marks"]')
    await marks.getByText('⊥').waitFor()
    await marks.getByText('∃1').waitFor()
    const turtle = (await api('GET', `/ontologies/${supplyChain.id}/rdf?format=turtle`)).body
    expect(turtle.includes('owl:disjointWith') && turtle.includes('owl:someValuesFrom'), 'OWL export contains the new axioms')
  })

  await step('Validation tab reports SHACL and OWL reasoning as separate lanes', async () => {
    await tab(/^Validation/).click()
    await page.getByTestId('lane-shacl-status').getByText('Well-formed').waitFor()
    await page.getByTestId('lane-reasoning-run').click()
    await page.getByTestId('lane-reasoning-status').getByText('No inconsistency found').waitFor({ timeout: 60_000 })
    await page.getByTestId('lane-evidence').waitFor()
    await shot('05b-validation-lanes')
  })

  await step('Knowledge Graph Studio offers the validation policies', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph`)
    const select = page.getByLabel('Validation policy', { exact: true })
    await select.locator('option').nth(2).waitFor({ state: 'attached' })
    const options = await select.locator('option').allTextContents()
    expect(options.some((o) => o.includes('application-strict/1') && o.includes('default')), 'default policy listed')
    expect(options.some((o) => o.includes('shacl-signature/1')) && options.some((o) => o.includes('infer-and-flag/1')), 'all policies')
  })

  await step('Build the KG under shacl-signature/1: ten stages including SHACL validation', async () => {
    const ids = []
    const mappingIds = []
    for (const name of STRUCTURED) {
      const response = await page.request.post(`${BASE_URL}/api/projects/${project.id}/sources`, {
        multipart: { file: { name, mimeType: 'text/csv', buffer: await readFile(`${SUPPLY}${name}`) } },
      })
      const document = await response.json()
      ids.push(document.id)
      const suggestion = (await api('GET', `/sources/${document.id}/mapping-suggestion?ontology_version_id=${supplyChain.version.id}`)).body
      const mapping = await api('POST', `/projects/${project.id}/kg/mappings`, {
        document_id: document.id, ontology_version_id: supplyChain.version.id, name: `${basename(name, '.csv')} mapping`,
        spec: suggestion.spec, updated_by: REVIEWER,
      })
      mappingIds.push(mapping.body.id)
    }
    const created = await api('POST', `/projects/${project.id}/kg/builds`, {
      name: 'SHACL signature policy', ontology_version_id: supplyChain.version.id, source_document_ids: ids,
      mapping_ids: mappingIds, requested_by: REVIEWER, start: true, settings: { validation_policy: 'shacl-signature/1' },
    })
    expect(created.status === 201, `build created: ${JSON.stringify(created.body).slice(0, 300)}`)
    for (let i = 0; i < 60; i += 1) {
      build = (await api('GET', `/kg/builds/${created.body.id}`)).body
      if (build.status === 'completed' || build.status === 'failed') break
      await page.waitForTimeout(500)
    }
    expect(build.status === 'completed', `build completed: ${build.error}`)
    expect(build.stages.length === 10 && build.stats.shacl.shapes_source.startsWith('version package'), 'shapes from the package')
    await page.goto(`${BASE_URL}/projects/${project.id}/knowledge-graph?build=${build.id}`)
    await page.locator('[data-stage="shacl_validation"][data-stage-status="completed"]').waitFor()
  })

  await step('Fact Validation shows the SHACL lane, the policy and relaxed application checks', async () => {
    await tab(/Fact Validation/).click()
    await page.getByTestId('fact-filter-rejected').click()
    await page.getByTestId('fact-row').filter({ hasText: 'Steel Bracket SB-200 → supplies → Contoso Metals GmbH' }).first().click()
    const lanes = page.getByTestId('fact-lanes')
    await lanes.getByText(/policy SHACL signatures \(shacl-signature\/1\)/).waitFor()
    await lanes.getByText("Subjects of 'supplies' must be instances of Supplier.").waitFor()
    await lanes.getByText(/Application checks reported as information/).waitFor()
    await shot('06-fact-shacl-lane')
    await page.getByRole('button', { name: 'Close panel' }).click()
    await page.getByLabel('Fact kind').selectOption('attribute')
    const legalName = page.getByTestId('fact-row').filter({ hasText: 'legal name' }).first()
    await legalName.waitFor()
    expect((await legalName.getByTestId('shacl-badge').textContent()) === 'Violation', 'authored shape rejected legal names')
  })

  // ------------------------------------------------------------------ Settings section

  await step('Settings is the fourth primary section', async () => {
    await page.goto(`${BASE_URL}/projects/${project.id}/settings`)
    await page.getByTestId('settings-page').waitFor()
    const items = await page.getByRole('navigation', { name: 'Primary' }).getByRole('link').allTextContents()
    expect(
      JSON.stringify(items) === JSON.stringify(['Project Workspace', 'Ontology Studio', 'Knowledge Graph Studio', 'Settings']),
      `navigation: ${items.join(' | ')}`,
    )
  })

  await step('Register an LLM model and test it against the real endpoint', async () => {
    await page.getByRole('button', { name: 'Register LLM' }).click()
    const dialog = page.getByTestId('llm-dialog')
    await dialog.getByLabel('Name', { exact: true }).fill('Local Ollama (registered)')
    await dialog.getByLabel('Base URL').fill(process.env.E2E_LLM_BASE_URL ?? 'http://localhost:11434/v1')
    await dialog.getByLabel('Model').fill(process.env.E2E_LLM_MODEL ?? 'qwen2.5:7b')
    await dialog.getByRole('button', { name: 'Save' }).click()
    const row = page.getByTestId('llm-row').filter({ hasText: 'Local Ollama (registered)' })
    await row.waitFor()
    await row.getByRole('button', { name: 'Test' }).click()
    const result = row.getByTestId('connection-test')
    await result.waitFor({ timeout: 30_000 })
    expect((await result.getAttribute('data-ok')) === 'true', `real connection test: ${await result.textContent()}`)
  })

  await step('Graph databases: built-in Oxigraph tested, unavailable kinds explained, failures reported honestly', async () => {
    const oxigraph = page.getByTestId('graph-row').filter({ hasText: 'Embedded Oxigraph' })
    await oxigraph.getByRole('button', { name: 'Test' }).click()
    await oxigraph.locator('[data-testid="connection-test"][data-ok="true"]').waitFor()
    expect((await page.getByTestId('unavailable-kinds').textContent()).includes('Neo4j'), 'Neo4j listed as not available')
    await page.getByRole('button', { name: 'Register database' }).click()
    const dialog = page.getByTestId('graph-dialog')
    await dialog.getByLabel('Name', { exact: true }).fill('Unreachable SPARQL endpoint')
    await dialog.getByLabel('Query endpoint URL').fill('http://127.0.0.1:9/sparql')
    await dialog.getByRole('button', { name: 'Save' }).click()
    const row = page.getByTestId('graph-row').filter({ hasText: 'Unreachable SPARQL endpoint' })
    await row.getByRole('button', { name: 'Test' }).click()
    const result = row.locator('[data-testid="connection-test"][data-ok="false"]')
    await result.waitFor({ timeout: 30_000 })
    expect((await result.textContent()).includes('unreachable'), 'connection failure is reported, not simulated')
    await shot('07-settings')
  })

  await step('Project defaults use the registered LLM; discovery and KG builds resolve it', async () => {
    const llmOption = await page.locator('#default-llm option', { hasText: 'Local Ollama (registered)' }).getAttribute('value')
    await page.locator('#default-llm').selectOption(llmOption)
    await page.getByRole('button', { name: 'Save defaults' }).click()
    await page.getByText('Project defaults saved').waitFor()
    await page.goto(`${BASE_URL}/projects/${project.id}/ontology?tab=discovery`)
    const select = page.getByLabel('LLM configuration')
    await select.locator('option').first().waitFor({ state: 'attached' })
    expect((await select.locator('option').first().textContent()).includes('Local Ollama (registered)'), 'project default shown')
    await page.getByText('Endpoint reachable').first().waitFor({ timeout: 30_000 })
    const status = (await api('GET', `/llm/status?project_id=${project.id}`)).body
    expect(status.config_name === 'Local Ollama (registered)', `effective configuration: ${status.config_name}`)
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nPhase 4 semantic journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
