const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');

(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const errors = [];
  for (const viewport of [{ width: 1440, height: 900, name: 'desktop' }, { width: 390, height: 844, name: 'mobile' }]) {
    const context = await browser.newContext({ viewport });
    const page = await context.newPage();
    page.on('console', message => { if (message.type() === 'error') errors.push(`${viewport.name}: ${message.text()}`); });
    page.on('pageerror', error => errors.push(`${viewport.name}: ${error.message}`));
    await page.goto('http://127.0.0.1:8766', { waitUntil: 'networkidle' });
    await page.locator('#open-guide').click();
    if (!await page.locator('#guide-modal').isVisible()) throw new Error(`${viewport.name}: guide did not open`);
    await page.locator('#guide-start').click();
    await page.locator('#create-form input[name="name"]').fill('人机协同演示赛');
    await page.locator('#create-form').evaluate(form => form.requestSubmit());
    await page.waitForSelector('#game-view:not(.hidden)');
    if ((await page.locator('#match-mode').innerText()) !== '人机对抗') throw new Error(`${viewport.name}: match mode missing`);
    await page.locator('#start-match').click();
    await page.locator('[data-add="loan"]').click();
    const planText = await page.locator('#plan-list').innerText();
    if (!planText.includes('借入 100 万')) throw new Error(`${viewport.name}: readable loan summary missing`);
    if (planText.includes('{') || planText.includes('"principal_wan"')) throw new Error(`${viewport.name}: JSON leaked into plan`);
    await page.locator('[data-screen="ranking"]').click();
    const rankingText = await page.locator('#screen-ranking').innerText();
    if (!rankingText.includes('人类') || !rankingText.includes('Agent')) throw new Error(`${viewport.name}: participant labels missing`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    if (overflow) throw new Error(`${viewport.name}: horizontal overflow`);
    await page.screenshot({ path: `/tmp/goai_guided_${viewport.name}.png`, fullPage: true });
    await context.close();
  }
  await browser.close();
  if (errors.length) throw new Error(errors.join('\n'));
  console.log('guided UI verified on desktop and mobile');
})();
