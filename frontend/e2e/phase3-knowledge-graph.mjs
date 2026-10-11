/**
 * End-to-end check of the Phase 3 knowledge-graph lifecycle through the UI and real APIs:
 *
 *   publish v1.0.0 -> select sources + version -> configure mappings -> build (real LLM for the
 *   PDF) -> facts (reversed relationship rejected, unsupported fact quarantined) -> graph explorer
 *   with provenance -> metrics -> ontology gap -> SME proposal -> approve -> publish v1.1.0 ->
 *   rebuild with v1.1.0 while the earlier build stays intact -> compare builds.
 *
 *   npm run e2e:kg                      # includes the sample PDF (real LLM, several minutes on CPU)
 *   E2E_KG_SKIP_PDF=1 npm run e2e:kg    # structured sources only (no LLM needed)
 *
 * Requires a FRESH database (the script publishes versions and changes the ontology) plus the
 * backend and the frontend dev server.
 */
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const BUILD_TIMEOUT_MS = Number(process.env.E2E_BUILD_TIMEOUT_MS ?? 25 * 60 * 1000)
const SKIP_PDF = process.env.E2E_KG_SKIP_PDF === '1'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SAMPLES = fileURLToPath(new URL('../../samples/supply-chain/', import.meta.url))
const STRUCTURED = ['suppliers.csv', 'products.csv', 'purchase_orders.csv', 'supply_relationships.csv']
const PDF = 'supplier-performance-review.pdf'
const REVIEWER = 'E2E Knowledge Engineer'

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

await mkdir(ARTIFACTS, { recursive: true })
const browser = await chromium.launch({ channel: CHANNEL, headless: process.env.E2E_HEADED !== '1' })
const context = await browser.newContext({ viewport: { width: 1680, height: 1050 } })
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
    console.log(`  ✔ ${String(counter).padStart(2)}. ${name} (${Math.round((Date.now() - started) / 100) / 10}s)`)
  } catch (error) {
    console.error(`  ✘ ${String(counter).padStart(2)}. ${name}`)
    await page.screenshot({ path: `${ARTIFACTS}p3-failure-step-${counter}.png`, fullPage: true }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}p3-${name}.png` })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  return { status: response.status(), body: response.headers()['content-type']?.includes('json') ? await response.json() : await response.text() }
}
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const kgUrl = (query = '') => `${BASE_URL}/projects/${project.id}/knowledge-graph${query}`
const tab = (name) => page.getByRole('tab', { name })

async function publishVersion(label, notes) {
  await page.goto(`${BASE_URL}/projects/${project.id}/ontology?tab=registry`)
  await page.getByTestId('publish-validation').getByText('Validation gate passed').waitFor({ timeout: 30_000 })
  await page.getByLabel('Release notes').fill(notes)
  await page.getByRole('button', { name: `Publish v${label}` }).click()
  await page.getByText(`Published version ${label}`).waitFor()
}

async function configureMapping(filename) {
  const row = page.getByTestId(`source-${filename}`)
  await row.getByRole('button', { name: /Configure mapping|Edit mapping/ }).click()
  const dialog = page.getByTestId('mapping-editor')
  await dialog.getByTestId('mapping-preview').waitFor()
  await dialog.getByLabel('Suggestion notes').waitFor()
  await page.waitForFunction(() => {
    const save = [...document.querySelectorAll('[data-testid="mapping-editor"] button')].find((b) => b.textContent?.trim() === 'Save mapping')
    return save && !save.disabled
  })
  await dialog.getByRole('button', { name: 'Save mapping' }).click()
  await dialog.waitFor({ state: 'detached' })
  await row.getByLabel(`Mapping for ${filename}`).waitFor()
}

async function waitForBuild(number) {
  const deadline = Date.now() + BUILD_TIMEOUT_MS
  let last = ''
  for (;;) {
    const builds = (await api('GET', `/projects/${project.id}/kg/builds`)).body
    const build = builds.find((b) => b.number === number)
    if (build && (build.status === 'completed' || build.status === 'failed')) return (await api('GET', `/kg/builds/${build.id}`)).body
    const stage = build?.current_stage ?? build?.status
    if (stage !== last) {
      last = stage
      console.log(`       build #${number}: ${stage}`)
    }
    expect(Date.now() < deadline, `build #${number} finished within ${BUILD_TIMEOUT_MS / 60000} minutes`)
    await page.waitForTimeout(3000)
  }
}

let project
let ontology
let firstBuild
let firstGraph
let secondBuild

console.log(`Ontology Lifecycle Studio - Phase 3 knowledge graph journey against ${BASE_URL}${SKIP_PDF ? ' (structured sources only)' : ''}`)
try {
  await step('Open the project and identify the user', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists')
    ontology = (await api('GET', `/projects/${project.id}/ontologies`)).body[0]
    expect((await api('GET', `/projects/${project.id}/kg/builds`)).body.length === 0, 'start without KG builds (use a fresh database)')
    await page.goto(kgUrl())
    await page.getByRole('heading', { name: 'Knowledge Graph Studio' }).waitFor()
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: `Reviewer: ${REVIEWER}` }).waitFor()
    if ((await api('GET', `/ontologies/${ontology.id}/versions`)).body.length === 0) {
      await page.getByTestId('build-problems').getByText(/No published ontology version exists yet/).waitFor()
    }
  })

  await step('Publish the approved Supply Chain ontology v1.0.0 (drafts are not selectable)', async () => {
    const versions = (await api('GET', `/ontologies/${ontology.id}/versions`)).body
    if (versions.length === 0) await publishVersion('1.0.0', 'Approved baseline for knowledge graph construction.')
    await page.goto(kgUrl())
    await page.getByLabel('Published ontology version').waitFor()
    const options = await page.getByLabel('Published ontology version').locator('option').allTextContents()
    expect(options.some((o) => /Supply Chain Core v1\.0\.0/.test(o)), `published version listed: ${options.join(' | ')}`)
    expect(!options.some((o) => /draft/i.test(o)), 'no draft is offered')
  })

  await step('Select the published version and inspect the extraction schema', async () => {
    await page.getByRole('button', { name: /Available for extraction/ }).click()
    const schema = page.getByTestId('version-schema')
    await schema.getByText('Supplier', { exact: true }).waitFor()
    await schema.getByText('supplies', { exact: true }).waitFor()
  })

  await step('Upload structured data and the PDF, and select them', async () => {
    const files = SKIP_PDF ? STRUCTURED : [...STRUCTURED, PDF]
    await page.setInputFiles('[data-testid="kg-source-upload"]', files.map((f) => `${SAMPLES}${f}`))
    for (const file of files) {
      const checkbox = page.getByRole('checkbox', { name: `Use ${file}` })
      await checkbox.waitFor()
      await page.waitForFunction((name) => document.querySelector(`[aria-label="Use ${name}"]`)?.getAttribute('data-state') === 'checked', file)
    }
    await page.getByTestId('build-problems').getByText('Configure a mapping for suppliers.csv.').waitFor()
  })

  await step('Configure and save source-to-ontology mappings', async () => {
    for (const file of STRUCTURED) await configureMapping(file)
    const mappings = (await api('GET', `/projects/${project.id}/kg/mappings`)).body
    expect(mappings.length === 4, 'four mappings saved')
    const edges = mappings.find((m) => m.document_name === 'supply_relationships.csv')
    expect(edges.spec.relationships[0].predicate_column === 'relationship', 'edge list maps the relationship column')
    expect(edges.issues.length === 0, 'edge list mapping is valid')
    await page.getByTestId('build-problems').waitFor({ state: 'detached' })
    await shot('05-configured')
  })

  await step('Start the build and follow the nine pipeline stages', async () => {
    await page.getByLabel('Build name (optional)').fill('Supplier network baseline')
    await page.getByRole('button', { name: 'Start build' }).click()
    await page.getByTestId('build-status').waitFor()
    await page.getByTestId('stage-progress').waitFor()
    if (!SKIP_PDF) {
      await page.locator('[data-stage="entity_extraction"][data-stage-status="running"]').waitFor({ timeout: 60_000 }).catch(() => {})
      await shot('06-build-running')
    }
    firstBuild = await waitForBuild(1)
    expect(firstBuild.status === 'completed', `build completed: ${firstBuild.error}`)
    await page.locator('[data-stage="evaluation"][data-stage-status="completed"]').waitFor({ timeout: 30_000 })
    await page.getByTestId('build-logs').getByText(/Schema authority: Supply Chain Core 1\.0\.0/).waitFor()
    const counts = firstBuild.stats.facts.by_status
    console.log(`       ${counts.accepted} accepted, ${counts.rejected} rejected, ${counts.quarantined} quarantined facts; ` +
      `${firstBuild.stats.graph.nodes} nodes, ${firstBuild.stats.graph.edges} edges; ${firstBuild.stats.resolution.mentions} mentions`)
    if (!SKIP_PDF) {
      const extraction = firstBuild.stats.extraction
      console.log(`       LLM ${firstBuild.model}: ${extraction.batches_completed}/${extraction.batches} batch(es)`)
      expect(extraction.batches_completed > 0, 'the LLM returned valid output')
    }
    expect((await page.getByTestId('count-accepted').textContent()).includes(String(counts.accepted)), 'accepted count displayed')
    await shot('07-build-completed')
  })

  await step('Reject an intentionally reversed relationship', async () => {
    await tab(/Fact Validation/).click()
    await page.getByTestId('fact-filter-rejected').click()
    const row = page.getByTestId('fact-row').filter({ hasText: 'Steel Bracket SB-200 → supplies → Contoso Metals GmbH' })
    await row.first().click()
    await page.getByText(/Direction reversed: the ontology defines Supplier → supplies → Product/).first().waitFor()
    await page.getByTestId('source-record').first().getByText('Product', { exact: true }).waitFor()
    await shot('08-rejected-reversed')
    await page.getByRole('button', { name: 'Close panel' }).click()
  })

  await step('Quarantine a fact with inadequate evidence', async () => {
    await page.getByTestId('fact-filter-quarantined').click()
    await page.getByTestId('fact-row').filter({ hasText: 'Fabrikam Plastics Inc → supplies → P-999' }).first().click()
    await page.getByText(/is not established by any source record/).first().waitFor()
    const quarantined = (await api('GET', `/kg/builds/${firstBuild.id}/facts?status=quarantined`)).body.items
    expect(quarantined.every((f) => f.structural_passed), 'quarantined facts are structurally valid but not adequately supported')
    if (!SKIP_PDF) {
      const text = (await api('GET', `/kg/builds/${firstBuild.id}/facts`)).body.items.filter((f) => f.origin === 'llm')
      console.log(`       LLM facts: ${text.length} (${['accepted', 'rejected', 'quarantined'].map((s) => `${text.filter((f) => f.status === s).length} ${s}`).join(', ')})`)
    }
    await page.getByRole('button', { name: 'Close panel' }).click()
  })

  await step('Persisted graph is rendered from the graph store', async () => {
    firstGraph = (await api('GET', `/kg/builds/${firstBuild.id}/graph`)).body
    await tab('Graph Explorer').click()
    await page.getByTestId('graph-canvas').waitFor()
    await page.waitForFunction((n) => window.__kgCy && window.__kgCy.nodes().length === n, firstGraph.nodes.length)
    const rendered = await page.evaluate(() => ({ nodes: window.__kgCy.nodes().length, edges: window.__kgCy.edges().length }))
    expect(rendered.nodes === firstGraph.total_nodes && rendered.edges === firstGraph.total_edges, `canvas shows ${JSON.stringify(rendered)}`)
    const names = firstGraph.nodes.map((n) => n.name)
    expect(!names.includes('P-999') && !names.includes('A-01'), 'rejected/quarantined entities are not in the graph')
    await shot('09-graph')
  })

  await step('Filter, search and select an entity', async () => {
    await page.getByTestId('facet-cls-supplier').click()
    await page.waitForFunction(() => window.__kgCy.nodes().every((n) => n.data('classId') === 'cls-supplier'))
    await page.getByTestId('facet-cls-supplier').click()
    await page.waitForFunction((n) => window.__kgCy.nodes().length === n, firstGraph.nodes.length)
    await page.getByLabel('Search entities').fill('Contoso Metals')
    await page.getByTestId('search-results').getByRole('button', { name: /Contoso Metals GmbH/ }).click()
    const details = page.getByTestId('graph-details')
    await details.waitFor()
    expect((await details.getAttribute('data-kind')) === 'node', 'entity details shown')
    await details.getByText('Relationships', { exact: false }).first().waitFor()
  })

  await step('Click a relationship to inspect its source evidence', async () => {
    const byName = Object.fromEntries(firstGraph.nodes.map((n) => [n.id, n.name]))
    const edge = firstGraph.edges.find(
      (e) => byName[e.source] === 'Northwind Components Ltd' && e.predicate_label === 'supplies' && byName[e.target] === 'Hydraulic Pump HP-100',
    )
    expect(edge, 'Northwind supplies Hydraulic Pump edge exists')
    await page.evaluate((id) => window.__kgCy.getElementById(id).emit('tap'), edge.id)
    const details = page.getByTestId('graph-details')
    await page.waitForFunction(() => document.querySelector('[data-testid="graph-details"]')?.getAttribute('data-kind') === 'edge')
    const t0 = Date.now()
    await page.getByRole('heading', { name: 'Northwind Components Ltd → supplies → Hydraulic Pump HP-100' }).waitFor()
    const t1 = Date.now()
    await details.getByTestId('details-version').getByText('v1.0.0').waitFor()
    const sources = await details.getByTestId('fact-source').allTextContents()
    if (process.env.E2E_DEBUG) console.log(`       heading ${t1 - t0} ms, sources ${Date.now() - t1} ms`)
    expect(sources.some((s) => s.includes('products.csv')) && sources.some((s) => s.includes('supply_relationships.csv')), 'record provenance shown')
    expect(edge.fact_count >= 2, 'duplicate facts from several sources share one edge')
    if (sources.some((s) => s.includes(PDF))) console.log('       the PDF also supports this relationship (page text shown)')
    await shot('11-edge-provenance')
    await page.getByRole('button', { name: 'Close panel' }).click()
  })

  await step('View quality metrics with explicit definitions', async () => {
    await tab('Evaluation & Feedback').click()
    const rate = page.getByTestId('metric-acceptance_rate')
    await rate.waitFor()
    const evaluation = (await api('GET', `/kg/builds/${firstBuild.id}/evaluation`)).body
    const metric = evaluation.sections.flatMap((s) => s.metrics).find((m) => m.key === 'acceptance_rate')
    expect((await rate.textContent()).includes(`${metric.numerator} / ${metric.denominator}`), 'numerator and denominator displayed')
    await page.getByText(/do not measure factual precision or recall/).waitFor()
    await shot('12-metrics')
  })

  await step('Identify the ontology gap and send it to SME review', async () => {
    const gapRow = page.locator('[data-testid="gap-row"][data-gap-type="unknown_relationship"][data-gap-label="certified by"]').first()
    await gapRow.waitFor()
    await gapRow.getByRole('checkbox').click()
    await page.getByRole('button', { name: /Create change proposals \(1\)/ }).click()
    await page.getByLabel('Comment for reviewers').fill('Partner data and the supplier review report certification by auditors.')
    await page.getByRole('button', { name: 'Create proposals' }).click()
    await page.getByTestId('proposal-result').getByText(/2 proposal\(s\) awaiting SME review/).waitFor()
    const proposals = (await api('GET', `/ontologies/${ontology.id}/proposals?origin=kg_build`)).body
    expect(proposals.length === 2 && proposals.every((p) => p.status === 'pending'), 'two pending KG-origin proposals')
    expect((await api('GET', `/ontologies/${ontology.id}/versions`)).body.length === 1, 'nothing was published automatically')
    await shot('13-gap-proposed')
  })

  await step('Review and approve the change through the existing governance process', async () => {
    await page.getByTestId('proposal-result').getByRole('link', { name: /Open SME Review/ }).click()
    await page.getByTestId('proposal-list').waitFor()
    const proposals = (await api('GET', `/ontologies/${ontology.id}/proposals?origin=kg_build`)).body
    const ordered = [...proposals].sort((a) => (a.element_kind === 'class' ? -1 : 1))
    for (const proposal of ordered) {
      await page.getByTestId('proposal-list').getByRole('button', { name: new RegExp(escape(proposal.title)) }).click()
      await page.waitForFunction((id) => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-proposal-id') === id, proposal.id)
      await page.getByTestId('proposal-detail').getByText('From knowledge graph build feedback').waitFor()
      await page.getByTestId('proposal-detail').getByLabel('Decision comment').fill('Confirmed with the supplier quality team.')
      await page.getByTestId('proposal-detail').getByRole('button', { name: 'Approve' }).click()
      await page.waitForFunction(() => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-status') === 'approved')
    }
    await page.getByRole('button', { name: /Apply 2 approved to draft/ }).click()
    await page.getByText(/Applied 2 proposals - draft revision/).waitFor()
  })

  await step('Publish the new ontology version v1.1.0', async () => {
    await publishVersion('1.1.0', 'Adds Auditor and certified by, identified during knowledge graph construction.')
    const versions = (await api('GET', `/projects/${project.id}/kg/ontology-versions`)).body
    expect(versions[0].version === '1.1.0' && versions[0].is_latest, 'v1.1.0 is available for KG builds')
  })

  await step('Rebuild with v1.1.0 without losing the earlier build', async () => {
    await page.goto(kgUrl(`?build=${firstBuild.id}`))
    await page.getByTestId('rebuild').getByLabel('Rebuild version').selectOption({ label: 'v1.1.0 (latest)' })
    await page.getByTestId('rebuild').getByRole('button', { name: 'Configure rebuild' }).click()
    await page.getByTestId('build-config').getByText('Configure build #2').waitFor()
    if (!SKIP_PDF && process.env.E2E_KG_REBUILD_PDF !== '1') {
      await page.getByRole('checkbox', { name: `Use ${PDF}` }).click()
    }
    await page.setInputFiles('[data-testid="kg-source-upload"]', `${SAMPLES}auditors.csv`)
    await page.getByRole('checkbox', { name: 'Use auditors.csv' }).waitFor()
    await page.waitForFunction(() => document.querySelector('[aria-label="Use auditors.csv"]')?.getAttribute('data-state') === 'checked')
    await configureMapping('auditors.csv')
    await page.getByRole('button', { name: 'Start build' }).click()
    secondBuild = await waitForBuild(2)
    expect(secondBuild.status === 'completed' && secondBuild.ontology_version === '1.1.0', `rebuild completed: ${secondBuild.error}`)
    expect(secondBuild.parent_build_id === firstBuild.id, 'rebuild is linked to the earlier build')
    const facts = (await api('GET', `/kg/builds/${secondBuild.id}/facts?kind=relationship&status=accepted`)).body.items
    expect(
      facts.some((f) => f.subject_label === 'Contoso Metals GmbH' && f.predicate_label === 'certified by' && f.object_label === 'Bureau Veritas Certification'),
      'the new relationship is accepted under v1.1.0',
    )
    const earlier = (await api('GET', `/kg/builds/${firstBuild.id}/graph`)).body
    expect(earlier.total_nodes === firstGraph.total_nodes && earlier.total_edges === firstGraph.total_edges, 'the earlier graph is unchanged')
    expect((await api('GET', `/kg/builds/${firstBuild.id}`)).body.ontology_version === '1.0.0', 'the earlier build keeps v1.0.0')
    await page.getByTestId('build-version').getByText('Supply Chain Core v1.1.0').waitFor()
    await shot('16-rebuild-completed')
  })

  await step('Compare the two builds', async () => {
    await page.getByTestId('build-history').getByRole('button', { name: 'Compare builds' }).click()
    const comparison = page.getByTestId('build-comparison')
    await comparison.getByText(/certifiedBy → Bureau Veritas Certification/).waitFor()
    await shot('17-comparison')
    await page.keyboard.press('Escape')
    await tab('Graph Explorer').click()
    const graph = (await api('GET', `/kg/builds/${secondBuild.id}/graph`)).body
    await page.waitForFunction((n) => window.__kgCy && window.__kgCy.nodes().length === n, graph.nodes.length)
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nKnowledge graph journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
