/**
 * End-to-end check of the Phase 1 user journey against a running stack.
 *
 *   npm run e2e:journey
 *
 * Requirements: backend on :8000 with the Supply Chain demo seeded, frontend dev server on :5173
 * and a locally installed Microsoft Edge (or set E2E_BROWSER_CHANNEL=chrome).
 * The journey edits the Supply Chain ontology; run it against a disposable database.
 *
 * Environment: E2E_BASE_URL (default http://localhost:5173), E2E_BROWSER_CHANNEL (default msedge),
 * E2E_HEADED=1 to watch the run.
 */
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))
const RUN_ID = Date.now().toString(36).slice(-5)

const NEW_CLASS = `Inventory Lot ${RUN_ID}`
const NEW_CLASS_LOCAL = `InventoryLot${RUN_ID.charAt(0).toUpperCase()}${RUN_ID.slice(1)}`
const NEW_RELATION = `held at ${RUN_ID}`
const SUPPLIER_DEFINITION = `An approved organization that provides goods or services (edited ${RUN_ID}).`

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
    console.log(`  ✔ ${String(counter).padStart(2)}. ${name} (${Date.now() - started} ms)`)
  } catch (error) {
    console.error(`  ✘ ${String(counter).padStart(2)}. ${name}`)
    await page.screenshot({ path: `${ARTIFACTS}failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}${name}.png` })
const api = (path) => page.evaluate(async (p) => (await fetch(`/api${p}`)).json(), path)
const node = (localName) => page.locator(`[data-testid="class-node-${localName}"]`)
const status = () => page.getByRole('status').filter({ hasText: /All changes saved|Unsaved changes/ }).first()

async function selectOption(triggerSelector, optionLabel) {
  await page.locator(triggerSelector).click()
  await page.getByRole('option', { name: optionLabel, exact: true }).click()
}

let revisionBeforeSave = 0
let revisionAfterSave = 0

console.log(`Ontology Lifecycle Studio - Phase 1 journey (run ${RUN_ID}) against ${BASE_URL}`)
try {
  await step('Launch the application', async () => {
    await page.goto(BASE_URL)
    await page.waitForURL(/\/projects\/[^/]+\/workspace/)
    await page.getByText('API online').waitFor()
  })

  await step('Open the Supply Chain project', async () => {
    await page.getByRole('combobox', { name: 'Select project' }).click()
    await page.getByRole('option', { name: 'Supply Chain', exact: true }).click()
    await page.getByRole('heading', { level: 1, name: 'Supply Chain' }).waitFor()
    await page.getByText('Recent activity').waitFor()
    await shot('02-project-workspace')
  })

  await step('Navigate to Ontology Studio', async () => {
    await page.locator('nav[aria-label="Primary"]').getByRole('link', { name: 'Ontology Studio' }).click()
    await page.waitForURL(/\/ontology/)
    await node('Supplier').waitFor()
  })

  await step('See the seed ontology displayed visually', async () => {
    await page.waitForTimeout(500)
    const nodes = await page.locator('.react-flow__node').count()
    const relations = await page.locator('.react-flow__edge.edge-relation').count()
    const subclasses = await page.locator('.react-flow__edge.edge-subclass').count()
    expect(nodes >= 11, `expected >= 11 class nodes, got ${nodes}`)
    expect(relations >= 12, `expected >= 12 relationship edges, got ${relations}`)
    expect(subclasses >= 5, `expected >= 5 subclass edges, got ${subclasses}`)
    const text = await status().textContent()
    revisionBeforeSave = Number(text?.match(/revision (\d+)/)?.[1])
    expect(revisionBeforeSave >= 1, `could not read draft revision from "${text}"`)
    await shot('04-seed-ontology')
  })

  await step('Add a new class through the UI', async () => {
    await page.getByRole('button', { name: 'Class', exact: true }).click()
    await page.fill('#new-class-label', NEW_CLASS)
    expect((await page.inputValue('#new-class-local-name')) === NEW_CLASS_LOCAL, 'local name is derived from the label')
    await page.fill('#new-class-description', 'A quantity of a product held at a warehouse under one batch identifier.')
    await page.locator('[role=dialog] button[type=submit]').click()
    await node(NEW_CLASS_LOCAL).waitFor()
    await page.locator('aside[aria-label="Details panel"]').getByRole('heading', { name: NEW_CLASS }).waitFor()
    expect((await status().textContent())?.includes('Unsaved changes'), 'editor shows unsaved changes')
    const newBox = await node(NEW_CLASS_LOCAL).boundingBox()
    for (const other of await page.locator('[data-testid^="class-node-"]').all()) {
      if ((await other.getAttribute('data-testid')) === `class-node-${NEW_CLASS_LOCAL}`) continue
      const box = await other.boundingBox()
      if (!box || !newBox) continue
      const overlap = newBox.x < box.x + box.width && newBox.x + newBox.width > box.x && newBox.y < box.y + box.height && newBox.y + newBox.height > box.y
      expect(!overlap, `new class must not be placed on top of ${await other.getAttribute('data-testid')}`)
    }
  })

  await step('Edit a class definition', async () => {
    await node('Supplier').click({ position: { x: 80, y: 14 } })
    const panel = page.locator('aside[aria-label="Details panel"]')
    await panel.getByRole('heading', { name: 'Supplier' }).waitFor()
    await page.fill('#class-description', SUPPLIER_DEFINITION)
    await page.fill('#class-aliases', 'Seller')
    await page.keyboard.press('Enter')
    await panel.getByText('Seller', { exact: true }).waitFor()
  })

  await step('Add a relationship between two classes', async () => {
    await page.getByRole('button', { name: 'Relationship', exact: true }).click()
    await selectOption('#new-rel-domain', NEW_CLASS)
    await selectOption('#new-rel-range', 'Warehouse')
    await page.fill('#new-rel-label', NEW_RELATION)
    await page.locator('[role=dialog] button[type=submit]').click()
    await page.locator('.react-flow__edgelabel-renderer').getByRole('button', { name: NEW_RELATION }).waitFor()
    await shot('07-unsaved-changes')
  })

  await step('Drag-to-connect opens a prefilled relationship dialog', async () => {
    await page.locator('aside[aria-label="Details panel"]').getByRole('button', { name: 'Close panel' }).click()
    await page.locator('.react-flow__controls-fitview').click()
    await page.waitForTimeout(400)
    await node('Supplier').hover()
    const handle = page.locator('.react-flow__node:has([data-testid="class-node-Supplier"]) .react-flow__handle.source')
    const from = await handle.boundingBox()
    const to = await node('Location').boundingBox()
    expect(from && to, 'handle and target are visible')
    await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2)
    await page.mouse.down()
    await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 20 })
    await page.mouse.up()
    await page.locator('#new-rel-label').waitFor()
    expect((await page.locator('#new-rel-domain').textContent())?.includes('Supplier'), 'domain prefilled with Supplier')
    expect((await page.locator('#new-rel-range').textContent())?.includes('Location'), 'range prefilled with Location')
    await page.getByRole('button', { name: 'Cancel' }).click()
  })

  await step('Save the ontology draft', async () => {
    await page.getByRole('button', { name: 'Save draft' }).click()
    await page.getByText(/Draft saved as revision \d+/).waitFor()
    const text = await status().textContent()
    revisionAfterSave = Number(text?.match(/revision (\d+)/)?.[1])
    expect(revisionAfterSave === revisionBeforeSave + 1, `revision ${revisionBeforeSave} -> ${revisionAfterSave}`)
    await shot('08-saved')
  })

  await step('Refresh the browser', async () => {
    await page.reload()
    await node('Supplier').waitFor()
  })

  await step('Verify all changes are persisted', async () => {
    await node(NEW_CLASS_LOCAL).waitFor()
    await page.locator('.react-flow__edgelabel-renderer').getByRole('button', { name: NEW_RELATION }).waitFor()
    expect((await status().textContent())?.includes(`revision ${revisionAfterSave}`), 'reloaded draft has the saved revision')
    await node('Supplier').click({ position: { x: 80, y: 14 } })
    expect((await page.inputValue('#class-description')) === SUPPLIER_DEFINITION, 'Supplier definition persisted')
    await page.locator('aside[aria-label="Details panel"]').getByText('Seller', { exact: true }).waitFor()

    const project = (await api('/projects')).find((p) => p.name === 'Supply Chain')
    const [ontology] = await api(`/projects/${project.id}/ontologies`)
    const draft = await api(`/ontologies/${ontology.id}/draft`)
    const created = draft.classes.find((c) => c.local_name === NEW_CLASS_LOCAL)
    const relation = draft.object_properties.find((p) => p.label === NEW_RELATION)
    expect(created, 'new class stored in the backend')
    expect(relation?.domain_id === created.id, 'relationship domain stored')
    expect(draft.classes.find((c) => c.id === relation.range_id)?.local_name === 'Warehouse', 'relationship range stored')
    expect(draft.layout.positions[created.id], 'new class position stored')
    await shot('10-after-refresh')
  })

  await step('Run basic structural validation', async () => {
    await page.getByRole('tab', { name: /Validation/ }).click()
    await page.getByRole('button', { name: 'Run validation' }).first().click()
    await page.getByTestId('validation-status').waitFor()
  })

  await step('Display validation results', async () => {
    const statusText = await page.getByTestId('validation-status').textContent()
    expect(statusText === 'Structurally valid', `expected a valid ontology, got "${statusText}"`)
    await page.getByText(`Revision ${revisionAfterSave}`, { exact: false }).first().waitFor()
    const finding = page.locator('ul[aria-label="Validation findings"] li').filter({ hasText: `Relationship '${NEW_RELATION}' has no definition` })
    await finding.waitFor()
    await shot('12-validation-results')
    await finding.getByRole('button', { name: 'Show' }).click()
    await page.locator('aside[aria-label="Details panel"]').getByRole('heading', { name: NEW_RELATION }).waitFor()
    await page.waitForTimeout(700)
    const canvas = await page.getByTestId('ontology-canvas').boundingBox()
    const focused = await node(NEW_CLASS_LOCAL).boundingBox()
    expect(
      canvas && focused && focused.x >= canvas.x && focused.x + focused.width <= canvas.x + canvas.width &&
        focused.y >= canvas.y && focused.y + focused.height <= canvas.y + canvas.height,
      'designer centres the element referenced by the finding',
    )
    await shot('12b-issue-in-designer')
  })

  await step('Extra: create a project through the UI (empty ontology state)', async () => {
    const name = `E2E Project ${RUN_ID}`
    await page.getByRole('combobox', { name: 'Select project' }).click()
    await page.getByRole('option', { name: /New project/ }).click()
    await page.fill('#project-name', name)
    expect((await page.inputValue('#ontology-name')) === `${name} Core`, 'ontology name derived from project name')
    expect((await page.inputValue('#ontology-namespace')).endsWith(`e2e-project-${RUN_ID}#`), 'namespace derived from project name')
    await page.locator('[role=dialog] button[type=submit]').click()
    await page.getByRole('heading', { level: 1, name }).waitFor()
    await page.locator('nav[aria-label="Primary"]').getByRole('link', { name: 'Ontology Studio' }).click()
    await page.getByText('This ontology has no classes yet').waitFor()
  })

  await step('Extra: unsaved changes block navigation until confirmed', async () => {
    await page.getByRole('button', { name: 'Add first class' }).click()
    await page.fill('#new-class-label', 'Patient')
    await page.locator('[role=dialog] button[type=submit]').click()
    await node('Patient').waitFor()
    await page.locator('nav[aria-label="Primary"]').getByRole('link', { name: 'Project Workspace' }).click()
    await page.getByRole('alertdialog').getByText('Leave with unsaved changes?').waitFor()
    await page.getByRole('button', { name: 'Stay and keep editing' }).click()
    expect(page.url().includes('/ontology'), 'navigation was cancelled')
    await node('Patient').waitFor()
    await page.locator('nav[aria-label="Primary"]').getByRole('link', { name: 'Project Workspace' }).click()
    await page.getByRole('button', { name: 'Discard and leave' }).click()
    await page.waitForURL(/\/workspace/)
  })

  const unexpected = consoleErrors.filter((e) => !e.includes('Download the React DevTools'))
  expect(unexpected.length === 0, `browser console errors: ${unexpected.join(' | ')}`)
  console.log(`\nJourney passed. Draft revision ${revisionBeforeSave} -> ${revisionAfterSave}. Screenshots: ${ARTIFACTS}`)
} finally {
  await browser.close()
}
