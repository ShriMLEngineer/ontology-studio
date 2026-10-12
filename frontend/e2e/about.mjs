/**
 * End-to-end check of the About page (read-only: nothing is created or changed):
 *   sidebar entry -> section navigation with scroll spy and URL hash -> lifecycle explorer ->
 *   product tour deep links -> architecture map (React Flow) -> technology filter ->
 *   live system status -> reload on a hash -> small-screen layout.
 *
 *   npm run e2e:about
 *
 * Requires the backend and the frontend dev server. No LLM is used.
 */
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright-core'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://localhost:5173'
const CHANNEL = process.env.E2E_BROWSER_CHANNEL ?? 'msedge'
const ARTIFACTS = fileURLToPath(new URL('./artifacts/', import.meta.url))

function expect(condition, message) {
  if (!condition) throw new Error(`Assertion failed: ${message}`)
}

await mkdir(ARTIFACTS, { recursive: true })
const browser = await chromium.launch({ channel: CHANNEL, headless: process.env.E2E_HEADED !== '1' })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
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
    await page.screenshot({ path: `${ARTIFACTS}about-failure-step-${counter}.png` }).catch(() => {})
    throw error
  }
}
const shot = (name) => page.screenshot({ path: `${ARTIFACTS}about-${name}.png` })
const testId = (id) => page.getByTestId(id)
const activeNav = () => page.locator('[data-testid^="about-nav-"][aria-current="location"]')
async function expectActive(section) {
  await page.locator(`[data-testid="about-nav-${section}"][aria-current="location"]`).waitFor({ timeout: 10_000 })
}

try {
  await step('open the About page from the sidebar', async () => {
    await page.goto(BASE_URL, { waitUntil: 'networkidle' })
    await page.locator('nav[aria-label="Primary"] a', { hasText: 'About' }).click()
    await testId('about-page').waitFor()
    expect(/\/projects\/[^/]+\/about$/.test(new URL(page.url()).pathname), `unexpected URL ${page.url()}`)
    expect((await page.locator('h1', { hasText: 'Ontology Lifecycle Studio' }).count()) === 1, 'hero title')
    await expectActive('overview')
    await shot('01-hero')
  })

  await step('section navigation scrolls, highlights and updates the hash', async () => {
    for (const section of ['lifecycle', 'tour', 'architecture', 'technology', 'system']) {
      await testId(`about-nav-${section}`).click()
      await expectActive(section)
      await page.waitForFunction((id) => location.hash === `#${id}`, section)
      const top = await page.locator(`#${section}`).evaluate((el) => Math.round(el.getBoundingClientRect().top))
      await page.waitForTimeout(1200)
      const settled = await page.locator(`#${section}`).evaluate((el) => Math.round(el.getBoundingClientRect().top))
      // The last section is short, so the page cannot scroll it all the way to the top.
      const limit = section === 'system' ? 700 : 450
      expect(settled < limit, `section ${section} should be near the top after scrolling (was ${top}, now ${settled})`)
      expect((await activeNav().count()) === 1, 'exactly one active nav item')
    }
    await page.getByRole('button', { name: 'Back to top' }).click()
    await expectActive('overview')
    await page.waitForTimeout(1200)
  })

  await step('scrolling by hand moves the active section', async () => {
    await page.locator('#architecture').scrollIntoViewIfNeeded()
    await page.mouse.move(700, 500)
    await page.evaluate(() => document.getElementById('technology').scrollIntoView({ behavior: 'instant', block: 'start' }))
    await expectActive('technology')
    await page.evaluate(() => document.getElementById('about-end').scrollIntoView({ behavior: 'instant', block: 'end' }))
    await expectActive('system')
  })

  await step('role picker switches the suggested path', async () => {
    await testId('about-nav-overview').click()
    await expectActive('overview')
    await testId('about-role-sme').click()
    const panel = testId('about-roles')
    await panel.getByText('Decides what the ontology means.').waitFor()
    const href = await panel.getByRole('link', { name: 'Open SME Review' }).getAttribute('href')
    expect(href?.endsWith('/ontology?tab=review'), `SME link ${href}`)
    await shot('02-overview')
  })

  await step('lifecycle explorer selects, steps and deep-links', async () => {
    await testId('about-nav-lifecycle').click()
    await expectActive('lifecycle')
    await testId('about-stage-kg_build').click()
    expect((await testId('about-stage-detail').getAttribute('data-stage')) === 'kg_build', 'kg_build selected')
    await testId('about-stage-detail').getByRole('button', { name: 'Next' }).click()
    expect((await testId('about-stage-detail').getAttribute('data-stage')) === 'deployment', 'next step is deployment')
    await testId('about-stage-detail').getByRole('button', { name: 'Previous' }).click()
    expect((await testId('about-stage-detail').getAttribute('data-stage')) === 'kg_build', 'previous step is kg_build')
    await page.getByRole('button', { name: /Feedback loop/ }).click()
    expect((await testId('about-stage-detail').getAttribute('data-stage')) === 'review', 'feedback loop selects SME review')
    await page.waitForTimeout(400)
    await shot('03-lifecycle')
    await testId('about-stage-evaluation').click()
    await testId('about-stage-detail').getByRole('link', { name: 'Open Evaluation & Feedback' }).click()
    await page.waitForURL(/\/knowledge-graph\?tab=evaluation/)
    await page.goBack()
    await testId('about-page').waitFor()
  })

  await step('product tour tabs and deep links', async () => {
    await testId('about-nav-tour').click()
    await expectActive('tour')
    await testId('about-tour-knowledge-graph').click()
    const explorer = testId('about-tour').getByRole('link', { name: /Graph Explorer/ })
    await explorer.waitFor()
    expect((await explorer.getAttribute('href'))?.endsWith('/knowledge-graph?tab=explorer'), 'explorer deep link')
    await testId('about-tour-settings').click()
    await testId('about-tour').getByRole('link', { name: /LLM models/ }).waitFor()
    await testId('about-tour-ontology').click()
    const registry = testId('about-tour').getByRole('link', { name: /Registry/ })
    expect((await registry.getAttribute('href'))?.endsWith('/ontology?tab=registry'), 'registry deep link')
    await shot('04-tour')
  })

  await step('architecture map: canvas click, button row, technology hand-off', async () => {
    await testId('about-nav-architecture').click()
    await expectActive('architecture')
    await testId('about-arch-flow').waitFor()
    expect((await testId('about-arch-detail').getAttribute('data-node')) === 'governance', 'default selection')
    await testId('about-arch-node-kg').click()
    expect((await testId('about-arch-detail').getAttribute('data-node')) === 'kg', 'canvas click selects kg')
    await testId('about-arch-pick-graphdb').click()
    expect((await testId('about-arch-detail').getAttribute('data-node')) === 'graphdb', 'button row selects graphdb')
    await testId('about-arch-pick-explorer').click()
    await page.waitForTimeout(500)
    await shot('05-architecture')
    await testId('about-arch-detail').getByRole('button', { name: 'Cytoscape.js' }).click()
    await expectActive('technology')
    await page.waitForFunction(() => document.querySelector('[data-testid="about-tech-count"]')?.textContent?.includes('Showing 1 of'))
    expect((await testId('about-tech-card').count()) === 1, 'one technology card after hand-off')
    expect(((await testId('about-tech-search').inputValue()) === 'Cytoscape.js'), 'search box holds the technology name')
  })

  await step('collapsing the sidebar re-fits the architecture map', async () => {
    const everyNodeInside = () =>
      page.evaluate(() => {
        const box = document.querySelector('[data-testid="about-arch-flow"]').getBoundingClientRect()
        const nodes = [...document.querySelectorAll('[data-testid^="about-arch-node-"]')]
        return (
          nodes.length === 9 &&
          nodes.every((node) => {
            const r = node.getBoundingClientRect()
            return r.left >= box.left - 1 && r.right <= box.right + 1 && r.top >= box.top - 1 && r.bottom <= box.bottom + 1
          })
        )
      })
    await testId('about-nav-architecture').click()
    await expectActive('architecture')
    await page.waitForTimeout(1200)
    expect(await everyNodeInside(), 'all nine components fit the canvas before collapsing')
    await page.getByRole('button', { name: 'Collapse sidebar' }).click()
    await page.waitForTimeout(800)
    expect(await everyNodeInside(), 'all nine components still fit the canvas after collapsing')
    await shot('05b-architecture-collapsed')
  })

  await step('technology search and category filters', async () => {
    await testId('about-tech-search').fill('')
    await testId('about-tech-filter-all').click()
    const total = await testId('about-tech-card').count()
    expect(total >= 30, `expected the full catalogue, got ${total}`)
    await testId('about-tech-filter-canvas').click()
    expect((await testId('about-tech-card').count()) === 2, 'canvas category lists React Flow and Cytoscape.js')
    await testId('about-tech-search').fill('react flow')
    expect((await testId('about-tech-card').count()) === 1, 'search narrows to React Flow')
    await testId('about-tech-search').fill('zzz-no-match')
    await page.getByText('No technology matches the current filter.').waitFor()
    await page.getByRole('button', { name: 'Clear filters' }).click()
    expect((await testId('about-tech-card').count()) === total, 'clearing restores the catalogue')
    await testId('about-tech-filter-backend').click()
    await page.waitForTimeout(1200)
    await shot('06-technology')
    await testId('about-tech-filter-all').click()
  })

  await step('live system reflects the running backend', async () => {
    await testId('about-nav-system').click()
    await expectActive('system')
    await page.locator('[data-testid="about-system-api"]', { hasText: 'Online' }).waitFor({ timeout: 15_000 })
    await page.locator('[data-testid="about-system-db"]', { hasText: 'Healthy' }).waitFor()
    await testId('about-system-ai').waitFor()
    await page.waitForTimeout(1200)
    await shot('07-system')
  })

  await step('a section hash is followed on edit and survives a reload', async () => {
    const url = new URL(page.url())
    await page.goto(`${url.origin}${url.pathname}#tour`, { waitUntil: 'networkidle' })
    await expectActive('tour')
    await page.goto(`${url.origin}${url.pathname}#technology`, { waitUntil: 'networkidle' })
    await page.reload({ waitUntil: 'networkidle' })
    await testId('about-page').waitFor()
    await expectActive('technology')
    expect(new URL(page.url()).hash === '#technology', 'hash kept after reload')
  })

  await step('narrow windows get a chip bar and no canvas', async () => {
    await page.setViewportSize({ width: 700, height: 900 })
    await page.goto(`${new URL(page.url()).origin}${new URL(page.url()).pathname}`, { waitUntil: 'networkidle' })
    await testId('about-nav').waitFor()
    expect(!(await testId('about-arch-flow').isVisible()), 'canvas hidden on narrow windows')
    const overflow = await page.evaluate(() => {
      const main = document.querySelector('main')
      return main.scrollWidth - main.clientWidth
    })
    expect(overflow <= 1, `no horizontal overflow in the page area (was ${overflow}px)`)
    await testId('about-nav-architecture').click()
    await expectActive('architecture')
    await testId('about-arch-pick-llm').click()
    expect((await testId('about-arch-detail').getAttribute('data-node')) === 'llm', 'button row works on narrow windows')
    await page.waitForTimeout(1200)
    await shot('08-narrow')
  })

  // Leave the persisted sidebar preference as the user had it.
  await page.evaluate(() => localStorage.removeItem('ols.sidebarCollapsed'))

  expect(consoleErrors.length === 0, `console errors: ${consoleErrors.join(' | ')}`)
  console.log('\nAbout page journey passed.')
} finally {
  await browser.close()
}
