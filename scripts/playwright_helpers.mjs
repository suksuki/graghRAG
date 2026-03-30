import assert from 'node:assert/strict';
import { chromium } from 'playwright';

export async function withBrowser(run, { headless = true } = {}) {
  const browser = await chromium.launch({ headless });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
  try {
    return await run(page);
  } finally {
    await browser.close();
  }
}

export function getBaseUrl() {
  return process.env.BASE_URL || 'http://127.0.0.1:5173';
}

export function getHeadless() {
  const raw = String(process.env.HEADLESS ?? 'true').trim().toLowerCase();
  return !(raw === '0' || raw === 'false' || raw === 'no');
}

export async function openInsightPage(page) {
  await page.goto(getBaseUrl(), { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: /Insight/i }).click();
  await page.waitForURL(/\/insight$/);
}

export async function submitInsightQuery(page, query) {
  await page.getByRole('textbox').fill(query);
  await page.getByRole('button', { name: /Generate grounded summary/i }).click();
}

export async function routeInsightResponse(page, payload) {
  await page.route('**/api/v1/insights/document', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });
}

export function buildInsightPayload(overrides = {}) {
  return {
    answer: '',
    summary: '',
    source: 'rag',
    key_entities: [],
    key_relations: [],
    supporting_chunks: [],
    structured_evidence: [],
    insufficient_evidence: false,
    decision: { conflicts: [], support_groups: null },
    debug: {},
    ...overrides,
  };
}

export function printResult(name, result) {
  console.log(JSON.stringify({ check: name, ok: true, ...result }, null, 2));
}

export { assert };
