const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const output = process.argv[2] || '/tmp/goai_reference_audit';
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const requests = [];
  page.on('request', request => {
    const requestUrl = new URL(request.url());
    if (requestUrl.origin === 'https://shapan.hdu.edu.cn') {
      requests.push({ method: request.method(), path: requestUrl.pathname });
    }
  });
  await page.goto('https://shapan.hdu.edu.cn/Login.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.screenshot({ path: path.join(output, '01_login.png'), fullPage: true });
  const before = await page.locator('body').innerText();
  fs.writeFileSync(path.join(output, '01_login.txt'), before);

  const inputs = page.locator('input');
  const count = await inputs.count();
  if (count < 2) throw new Error(`Expected login inputs, got ${count}`);
  const userInput = page.locator('input[type="text"], input:not([type])').first();
  const passwordInput = page.locator('input[type="password"]').first();
  await userInput.fill(process.env.REFERENCE_USER || '');
  await passwordInput.fill(process.env.REFERENCE_PASSWORD || '');
  const submit = page.locator('.dl');
  await submit.click();
  await page.waitForLoadState('networkidle', { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(output, '02_after_login.png'), fullPage: true });
  fs.writeFileSync(path.join(output, '02_after_login.txt'), await page.locator('body').innerText());

  const links = await page.locator('a').evaluateAll(rows => rows.map(row => ({ text: row.innerText.trim(), href: row.href })).filter(row => row.text || row.href));
  const buttons = await page.locator('button').evaluateAll(rows => rows.map(row => ({ text: row.innerText.trim(), disabled: row.disabled })));
  const forms = await page.locator('form').evaluateAll(rows => rows.map(row => ({ action: row.action, method: row.method, text: row.innerText.trim().slice(0, 500) })));
  fs.writeFileSync(path.join(output, 'dom.json'), JSON.stringify({ url: page.url(), title: await page.title(), links, buttons, forms, requests }, null, 2));
  await browser.close();
})();
