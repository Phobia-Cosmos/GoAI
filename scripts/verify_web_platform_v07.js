const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome' });
  const results = [];
  for (const viewport of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    const opponentText = await page.locator('#opponent-help').innerText();
    await page.locator('[name="human_slots"]').fill('6');
    await page.locator('[name="team_count"]').fill('6');
    await page.locator('#create-form button[type="submit"]').click();
    await page.waitForSelector('#game-view:not(.hidden)');
    const waitingText = await page.locator('#game-message').innerText();
    const startDisabled = await page.locator('#start-match').isDisabled();
    await page.locator('#view-rules').click();
    const rulesText = await page.locator('#screen-rules').innerText();
    await page.locator('[data-screen="command"]').click();
    await page.waitForTimeout(100);
    const emptyLineText = await page.locator('#asset-line').textContent();
    const convertDisabled = await page.locator('[data-add="convert-line"]').isDisabled();
    const metricText = await page.locator('#metrics').innerText();
    const viewportOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    await page.screenshot({ path: `/tmp/qice-v07-${viewport.name}.png`, fullPage: true });
    results.push({ viewport: viewport.name, bodyOverflow, viewportOverflow, opponentText, waitingText, startDisabled, rulesComplete: rulesText.includes('生产线参数') && rulesText.includes('评分公式'), emptyLineText, convertDisabled, metricText });
    await context.close();
  }
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
