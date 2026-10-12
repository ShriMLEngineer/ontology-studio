/**
 * End-to-end check of the governance journey with a REAL configured LLM:
 * upload source -> AI discovery -> SME review (comment, refinement, edit, approve, reject)
 * -> apply to draft -> validate -> publish immutable version -> compare -> export Turtle.
 *
 *   npm run e2e:governance
 *
 * Requires the backend (with OLS_LLM_BASE_URL / OLS_LLM_MODEL configured) and the frontend dev
 * server. Model output varies between runs, so the script selects proposals by type and impact
 * instead of expecting exact findings. Local CPU models can take several minutes.
 * It changes the Supply Chain ontology and publishes a version: use a disposable database.
 */
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const RUN_TIMEOUT_MS = Number(process.env.E2E_DISCOVERY_TIMEOUT_MS ?? 20 * 60 * 1000)
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const SAMPLE = fileURLToPath(new URL('../../samples/supplier-quality-handbook.md', import.meta.url))
const REVIEWER = 'E2E Reviewer'

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
    console.log(`  ✔ ${String(counter).padStart(2)}. ${name} (${Math.round((Date.now() - started) / 100) / 10}s)`)
  } catch (error) {
    console.error(`  ✘ ${String(counter).padStart(2)}. ${name}`)
    await page.screenshot({ path: `${ARTIFACTS}p2-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}p2-${name}.png` })
const api = async (method, path, body) => {
  const response = await page.request.fetch(`${BASE_URL}/api${path}`, { method, data: body })
  return { status: response.status(), body: response.headers()['content-type']?.includes('json') ? await response.json() : await response.text() }
}
const tab = (name) => page.getByRole('tab', { name })
const detail = () => page.getByTestId('proposal-detail')

let project
let ontology
let approvedClass
let rejectedId
let version

console.log(`Ontology Lifecycle Studio - governance journey against ${BASE_URL}`)
try {
  await step('Open Ontology Studio and identify the reviewer', async () => {
    project = (await api('GET', '/projects')).body.find((p) => p.name === 'Supply Chain')
    expect(project, 'Supply Chain project exists')
    ontology = (await api('GET', `/projects/${project.id}/ontologies`)).body[0]
    expect(!ontology.latest_version, 'start from an ontology that has never been published (use a fresh database)')
    await page.goto(`${BASE_URL}/projects/${project.id}/ontology?tab=discovery`)
    await page.getByRole('button', { name: /Set reviewer name|Reviewer:/ }).click()
    await page.getByLabel('Reviewer name').fill(REVIEWER)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await page.getByRole('button', { name: `Reviewer: ${REVIEWER}` }).waitFor()
  })

  await step('AI provider is configured and reachable', async () => {
    await page.getByText('Endpoint reachable').waitFor({ timeout: 30_000 })
  })

  await step('Upload a source document', async () => {
    await page.setInputFiles('[data-testid="source-upload-input"]', SAMPLE)
    const checkbox = page.getByRole('checkbox', { name: 'Use supplier-quality-handbook.md' })
    await checkbox.waitFor()
    expect((await checkbox.getAttribute('data-state')) === 'checked', 'uploaded document is selected for the run')
  })

  await step('Run AI discovery with the real LLM (may take several minutes)', async () => {
    await page.getByLabel('SME focus (optional)').fill('Focus on supplier qualification, inventory lots and quality inspection.')
    await page.getByRole('button', { name: /Analyse 1 document/ }).click()
    await page.locator('[data-testid="discovery-run"][data-status="running"], [data-testid="discovery-run"][data-status="queued"]').first().waitFor()
    await shot('04-discovery-running')
    const finished = page.locator('[data-testid="discovery-run"][data-status="completed"], [data-testid="discovery-run"][data-status="failed"]').first()
    await finished.waitFor({ timeout: RUN_TIMEOUT_MS })
    expect((await finished.getAttribute('data-status')) === 'completed', `run completed: ${await finished.textContent()}`)
    const runs = (await api('GET', `/ontologies/${ontology.id}/discovery-runs`)).body
    expect(runs[0].stats.proposals > 0, 'the run produced proposals')
    console.log(`       model ${runs[0].model}: ${runs[0].stats.findings} findings -> ${runs[0].stats.proposals} proposals, ${runs[0].stats.discarded} discarded`)
    await shot('04-discovery-completed')
  })

  await step('Open the review queue for the run', async () => {
    await page.getByRole('button', { name: /Review proposals/ }).first().click()
    await page.getByText('From one discovery run').waitFor()
    await page.getByTestId('proposal-list').getByRole('button').first().waitFor()
  })

  await step('Inspect evidence and validation impact of an ADD class proposal', async () => {
    const proposals = (await api('GET', `/ontologies/${ontology.id}/proposals`)).body
    const candidates = []
    for (const p of proposals.filter((x) => x.proposal_type === 'add' && x.element_kind === 'class')) {
      const full = (await api('GET', `/proposals/${p.id}`)).body
      if (full.impact?.applicable && !full.impact.blocking) candidates.push(full)
    }
    expect(candidates.length > 0, 'at least one applicable ADD class proposal')
    approvedClass = candidates[0]
    await page.getByTestId('proposal-list').getByRole('button', { name: new RegExp(approvedClass.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click()
    await page.waitForFunction((id) => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-proposal-id') === id, approvedClass.id)
    await detail().getByText('Verified in source').first().waitFor()
    await detail().getByTestId('proposal-impact').waitFor()
    expect(approvedClass.evidence.every((e) => e.verified), 'all stored evidence is verified against the source')
    await shot('06-proposal-evidence')
  })

  await step('Comment, request refinement, edit and approve', async () => {
    await detail().getByLabel('Add a comment').fill('Checked against the supplier quality handbook.')
    await detail().getByRole('button', { name: 'Comment' }).click()
    await detail().getByText('Checked against the supplier quality handbook.').waitFor()

    await detail().getByLabel('Decision comment').fill('Please tighten the definition.')
    await detail().getByRole('button', { name: 'Request refinement' }).click()
    await page.waitForFunction(() => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-status') === 'needs_refinement')

    await detail().getByRole('button', { name: 'Edit' }).click()
    await page.locator('#edit-description').fill(`${approvedClass.new_element.description} (Reviewed by SME.)`)
    await page.locator('#edit-comment').fill('Definition tightened.')
    await page.getByRole('button', { name: 'Save changes' }).click()
    await page.waitForFunction(() => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-status') === 'pending')
    await detail().getByText('Edited by SME').waitFor()

    await detail().getByLabel('Decision comment').fill('Approved for the next release.')
    await detail().getByRole('button', { name: 'Approve' }).click()
    await page.getByText('Proposal approved').waitFor()
    const stored = (await api('GET', `/proposals/${approvedClass.id}`)).body
    expect(stored.status === 'approved', 'approval persisted')
    expect(
      JSON.stringify(stored.events.map((e) => e.event_type)) ===
        JSON.stringify(['created', 'commented', 'refinement_requested', 'edited', 'approved']),
      `decision trail persisted: ${stored.events.map((e) => e.event_type).join(', ')}`,
    )
    expect(stored.events.slice(1).every((e) => e.actor === REVIEWER), 'reviewer recorded on every decision')
    expect(stored.llm_output.label, 'original model output retained')
  })

  await step('Reject a proposal with a reason', async () => {
    const pending = (await api('GET', `/ontologies/${ontology.id}/proposals`)).body.filter((p) => p.status === 'pending')
    expect(pending.length > 0, 'another pending proposal exists')
    rejectedId = pending[0].id
    await page.getByTestId('proposal-list').getByRole('button', { name: new RegExp(pending[0].title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).first().click()
    await page.waitForFunction((id) => document.querySelector('[data-testid="proposal-detail"]')?.getAttribute('data-proposal-id') === id, rejectedId)
    await detail().getByRole('button', { name: 'Reject' }).click()
    await detail().getByText('Please record a comment').waitFor()
    await detail().getByLabel('Decision comment').fill('Out of scope for this release.')
    await detail().getByRole('button', { name: 'Reject' }).click()
    await page.getByText('Proposal rejected').waitFor()
    expect((await api('GET', `/proposals/${rejectedId}`)).body.status === 'rejected', 'rejection persisted')
  })

  await step('Apply approved proposals to the draft (never to a published version)', async () => {
    const before = (await api('GET', `/ontologies/${ontology.id}/draft`)).body
    await page.getByRole('button', { name: /Apply 1 approved to draft/ }).click()
    await page.getByText(/Applied 1 proposal - draft revision/).waitFor()
    const after = (await api('GET', `/ontologies/${ontology.id}/draft`)).body
    expect(after.draft_revision === before.draft_revision + 1, 'draft revision incremented')
    const added = after.classes.find((c) => c.id === approvedClass.new_element.id)
    expect(added && added.description.endsWith('(Reviewed by SME.)'), 'edited definition applied to the draft')
    expect((await api('GET', `/proposals/${approvedClass.id}`)).body.status === 'applied', 'proposal marked applied')
    await shot('09-applied')
  })

  await step('The applied class appears in the designer', async () => {
    await tab('Ontology Designer').click()
    await page.locator(`[data-testid="class-node-${approvedClass.new_element.local_name}"]`).waitFor()
  })

  await step('Validate the draft', async () => {
    await tab(/Validation/).click()
    await page.getByRole('button', { name: 'Run validation' }).first().click()
    await page.getByTestId('validation-status').waitFor()
    expect((await page.getByTestId('validation-status').textContent()) === 'Structurally valid', 'draft is publishable')
  })

  await step('Publish an immutable version from the Registry', async () => {
    await tab('Registry').click()
    await page.getByTestId('publish-validation').getByText('Validation gate passed').waitFor()
    await page.getByLabel('Release notes').fill('First governed release including AI-assisted additions.')
    await page.getByRole('button', { name: 'Publish v1.0.0' }).click()
    await page.getByText('Published version 1.0.0').waitFor()
    await page.getByTestId('version-row').first().waitFor()
    await page.getByTestId('header-published-version').getByText('Published v1.0.0').waitFor()
    version = (await api('GET', `/ontologies/${ontology.id}/versions`)).body[0]
    expect(version.version === '1.0.0' && version.published_by === REVIEWER, 'version and publisher recorded')
    await shot('11-published')
  })

  await step('Compare the published version with the draft', async () => {
    await page.getByTestId('compare-card').getByText(/No differences between v1\.0\.0 and Draft r\d+/).waitFor()
  })

  await step('Export Turtle and verify integrity', async () => {
    const link = page.getByRole('link', { name: 'Turtle (.ttl)' }).first()
    const response = await page.request.get(new URL(await link.getAttribute('href'), BASE_URL).toString())
    const turtle = await response.text()
    expect(response.ok() && response.headers()['content-type'].startsWith('text/turtle'), 'turtle export served')
    expect(turtle.includes('owl:Ontology') && turtle.includes('owl:versionInfo "1.0.0"'), 'versioned OWL ontology header')
    expect(turtle.includes(approvedClass.new_element.local_name), 'applied class is part of the published artifact')
    expect(response.headers()['x-content-sha256'] === version.artifacts.find((a) => a.format === 'turtle').sha256, 'checksum header matches')
  })

  await step('Published versions cannot be modified', async () => {
    const url = `/ontologies/${ontology.id}/versions/${version.id}`
    expect((await api('PATCH', url, { version: '9.9.9' })).status === 405, 'no update endpoint')
    expect((await api('DELETE', url)).status === 405, 'no delete endpoint')
    const deletion = await api('DELETE', `/ontologies/${ontology.id}`)
    expect(deletion.status === 409 && deletion.body.error.code === 'ONTOLOGY_HAS_PUBLISHED_VERSIONS', 'ontology with versions cannot be deleted')
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nGovernance journey passed. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
