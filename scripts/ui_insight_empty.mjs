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
  answer: 'No structured result.',
  summary: 'No structured result.',
  source: 'rag',
  insufficient_evidence: true,
});

const result = await withBrowser(
  async (page) => {
    await routeInsightResponse(page, payload);
    await openInsightPage(page);
    await submitInsightQuery(page, 'empty check');
    await page.waitForTimeout(800);

    const structuredCount = await page.locator('.structured-evidence').count();
    const bodyText = await page.locator('body').innerText();

    assert.equal(structuredCount, 0);
    assert.equal(bodyText.includes('Parsed structure from excerpts'), false);

    return {
      structuredCount,
      hasEmptyShellText: bodyText.includes('Parsed structure from excerpts'),
    };
  },
  { headless: getHeadless() }
);

printResult('ui:insight-empty', result);
