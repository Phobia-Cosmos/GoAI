const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');

const base = process.argv[2] || 'http://127.0.0.1:8765';

(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  const errors = [];
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.locator('input[name="name"]').fill('StratPilot v0.8 验收赛');
  await page.locator('input[name="team_count"]').fill('3');
  await page.locator('input[name="human_slots"]').fill('1');
  await page.locator('#create-form button[type="submit"]').click();
  await page.locator('#start-match').click();
  await page.waitForFunction(() => document.querySelector('#status-pill')?.textContent.includes('比赛中'));
  await page.locator('[data-screen="global-orders"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#orders-table tr').length >= 700);
  const initial = await page.evaluate(() => ({
    globalRows: document.querySelectorAll('#orders-table tr').length,
    claimable: document.querySelectorAll('#orders-table input[data-order]:not(:disabled)').length,
    ownedVisible: !document.querySelector('#screen-owned-orders').classList.contains('hidden'),
  }));
  if (initial.globalRows !== 800 || initial.claimable !== 0) throw new Error(`unexpected initial order visibility ${JSON.stringify(initial)}`);
  await page.locator('[data-screen="command"]').click();
  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#strategy-alternatives .strategy-card').length === 3);
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#period')?.textContent === 'Y1Q2');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#autopilot-player').click();
  await page.waitForFunction(() => document.querySelector('#status-pill')?.textContent.includes('已结束'), null, { timeout: 120000 });
  await page.waitForFunction(() => !document.querySelector('#screen-evaluation').classList.contains('hidden'));
  const final = await page.evaluate(() => ({
    period: document.querySelector('#period')?.textContent,
    evaluationText: document.querySelector('#agent-evaluation-view')?.textContent,
    oldSecondPhase: document.body.textContent.includes('提交获单后履约方案'),
  }));
  if (!final.evaluationText.includes('年度与季度决策依据') || final.oldSecondPhase) throw new Error(`unexpected final UI ${JSON.stringify(final)}`);
  if (errors.length) throw new Error(`browser errors: ${errors.join(' | ')}`);
  console.log(JSON.stringify({ status: 'ok', initial, final: { period: final.period }, alternatives: 3, singleSubmit: true }));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
