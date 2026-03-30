import {
  assert,
  buildInsightPayload,
  getHeadless,
  openInsightPage,
  printResult,
  routeInsightResponse,
  submitInsightQuery,
  withBrowser,
} from './playwright_helpers.mjs';

const payload = buildInsightPayload({
  answer: 'Li Jingli is the product lead.[1]',
  summary: 'Li Jingli is the product lead.[1]',
  source: 'facts',
  key_entities: ['Li Jingli'],
  key_relations: [],
  supporting_chunks: [
    {
      id: 'person::person_extract_smoke_zh.txt::1',
      ref_index: 1,
      file_name: 'person_extract_smoke_zh.txt',
      chunk_text: 'Product lead (Li Jingli)\nOwns AI training platform and data governance.',
      snippet: 'Product lead (Li Jingli) Owns AI training platform and data governance.',
      score: 1.0,
    },
  ],
  structured_evidence: [
    {
      role: 'Product lead',
      persons: ['Li Jingli', 'Wang Supervisor'],
      ref_indices: [1],
      file_names: ['person_extract_smoke_zh.txt'],
    },
  ],
});

const result = await withBrowser(
  async (page) => {
    await routeInsightResponse(page, payload);
    await openInsightPage(page);
    await page.locator('select').first().selectOption('en');
    await page.waitForTimeout(300);
    await submitInsightQuery(page, 'Who is Li Jingli?');
    await page.locator('.structured-evidence').waitFor({ state: 'visible' });

    const title = await page.locator('.structured-evidence__title').innerText();
    const hint = await page.locator('.structured-evidence__hint').innerText();
    const line = await page.locator('.structured-evidence__line').innerText();
    const refsLabel = await page.locator('.structured-evidence__meta-label').first().innerText();

    assert.match(title, /Parsed structure from excerpts/);
    assert.match(hint, /Preview only/);
    assert.match(line, /Product lead\s*:\s*Li Jingli, Wang Supervisor/);
    assert.match(refsLabel, /Refs/i);

    return { title, hint, line, refsLabel };
  },
  { headless: getHeadless() }
);

printResult('ui:insight-i18n', result);
