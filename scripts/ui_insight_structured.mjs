import {
  assert,
  getHeadless,
  openInsightPage,
  printResult,
  routeInsightResponse,
  submitInsightQuery,
  withBrowser,
} from './playwright_helpers.mjs';

const payload = {
  answer: '李经理是产品负责人。[1]',
  summary: '李经理是产品负责人。[1]',
  source: 'facts',
  key_entities: ['李经理'],
  key_relations: [],
  supporting_chunks: [
    {
      id: 'person::person_extract_smoke_zh.txt::1',
      ref_index: 1,
      file_name: 'person_extract_smoke_zh.txt',
      chunk_text: '产品负责人（李经理）\n负责 AI训练平台、数据治理系统。',
      snippet: '产品负责人（李经理） 负责 AI训练平台、数据治理系统。',
      score: 1.0,
    },
  ],
  structured_evidence: [
    {
      role: '产品负责人',
      persons: ['李经理'],
      ref_indices: [1],
      file_names: ['person_extract_smoke_zh.txt'],
    },
  ],
  insufficient_evidence: false,
  decision: { conflicts: [], support_groups: null },
  debug: {},
};

const result = await withBrowser(
  async (page) => {
    await routeInsightResponse(page, payload);
    await openInsightPage(page);
    await submitInsightQuery(page, '李经理是谁？');
    await page.locator('.structured-evidence').waitFor({ state: 'visible' });

    const structuredText = await page.locator('.structured-evidence').innerText();
    await page.locator('.structured-evidence .grounded-insight__ref').click();
    await page.waitForTimeout(500);

    const activeSourceCount = await page.locator('.grounded-insight__source--active').count();
    const previewTitle = await page.locator('.grounded-insight__preview-title').innerText();
    const previewBody = await page.locator('.grounded-insight__preview-body').innerText();

    await page.locator('.structured-evidence__open').click();
    await page.waitForTimeout(500);
    const finalUrl = page.url();

    assert.match(structuredText, /产品负责人/);
    assert.equal(activeSourceCount, 1);
    assert.match(previewTitle, /\[1\] person_extract_smoke_zh\.txt/);
    assert.match(previewBody, /AI训练平台/);
    assert.match(finalUrl, /\/docs\/person_extract_smoke_zh\.txt$/);

    return {
      structuredText,
      activeSourceCount,
      previewTitle,
      previewBody,
      finalUrl,
    };
  },
  { headless: getHeadless() }
);

printResult('ui:insight-structured', result);
