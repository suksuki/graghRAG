import { chromium } from 'playwright';

function getBool(name, fallback = false) {
  const raw = String(process.env[name] ?? '').trim().toLowerCase();
  if (!raw) return fallback;
  return raw === '1' || raw === 'true' || raw === 'yes';
}

async function maybeClickByText(page, text) {
  if (!text) return false;
  const locator = page.getByText(text, { exact: false }).first();
  if (await locator.count()) {
    await locator.click();
    return true;
  }
  return false;
}

async function maybeFillQuery(page, query) {
  if (!query) return false;
  const candidates = [
    page.locator('input[type="text"]').first(),
    page.locator('input:not([type])').first(),
    page.locator('textarea').first(),
  ];
  for (const locator of candidates) {
    if (await locator.count()) {
      await locator.fill(query);
      await locator.press('Enter');
      return true;
    }
  }
  return false;
}

async function main() {
  const baseUrl = process.env.BASE_URL || 'http://127.0.0.1:5173';
  const pagePath = process.env.PAGE_PATH || '/';
  const query = process.env.QUERY || '';
  const clickText = process.env.CLICK_TEXT || '';
  const screenshotPath = process.env.SCREENSHOT_PATH || '';
  const waitMs = Number(process.env.WAIT_MS || 1500);
  const headless = getBool('HEADLESS', true);

  const browser = await chromium.launch({ headless });
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });

  try {
    await page.goto(new URL(pagePath, baseUrl).toString(), { waitUntil: 'networkidle' });

    if (query) {
      await maybeFillQuery(page, query);
      await page.waitForTimeout(waitMs);
    }

    if (clickText) {
      await maybeClickByText(page, clickText);
      await page.waitForTimeout(waitMs);
    }

    if (screenshotPath) {
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`screenshot=${screenshotPath}`);
    }

    console.log(`url=${page.url()}`);
    console.log(`title=${await page.title()}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
