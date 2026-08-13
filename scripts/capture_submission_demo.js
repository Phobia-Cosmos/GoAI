const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const base = 'http://127.0.0.1:8765';
const output = path.resolve(process.argv[2] || 'artifact/submission/demo');
fs.mkdirSync(output, { recursive: true });

const scenes = [];
const addScene = async (page, name, caption, duration = 5) => {
  const file = path.join(output, `${String(scenes.length + 1).padStart(2, '0')}_${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  scenes.push({ file, caption, duration });
};

const clickRecommendationAndSubmit = async (page) => {
  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => !document.querySelector('#submit-plan').disabled);
};

(async () => {
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });

  await page.goto(base, { waitUntil: 'networkidle' });
  await addScene(page, 'lobby', '创建可重复的企业经营比赛：支持人机、多人、纯用户和纯 Agent。', 6);

  await page.locator('input[name="name"]').fill('GoAI 脱敏演示赛');
  await page.locator('input[name="team_count"]').fill('6');
  await page.locator('input[name="human_slots"]').fill('1');
  await page.locator('select[name="bot_policy"]').selectOption('mixed');
  await page.locator('input[name="creator_name"]').fill('TEAM_01');
  await page.locator('input[name="seed"]').fill('20260817');
  await page.locator('#create-form button[type="submit"]').click();
  await page.waitForSelector('#game-view:not(.hidden)');
  await page.locator('#start-match').click();
  await page.waitForFunction(() => document.querySelector('#status-pill').textContent.includes('比赛中'));
  await addScene(page, 'initial_state', '系统只展示我方企业状态和规则允许的公开信息；裁判真值不由 Agent 修改。', 7);

  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length >= 1);
  await addScene(page, 'agent_plan', '六个专业模块生成一份联合动作包，用户可以删除、增加或修改后再提交。', 7);
  const firstRemove = page.locator('#plan-list [data-remove]').first();
  if (await firstRemove.count()) await firstRemove.click();
  await addScene(page, 'human_edit', '人工删除一项建议，证明 Agent 提供候选方案而不是绕过最终确认。', 5);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#phase-pill').textContent.includes('获单后履约'));
  await addScene(page, 'post_allocation_y1q1', '订单统一分配后进入获单后履约阶段；广告、资格和申领控件自动禁用。', 6);

  // Complete Y1Q1 and roll through the remaining pre-order development periods.
  await clickRecommendationAndSubmit(page);
  while ((await page.locator('#period').textContent()) !== 'Y2Q1') {
    await clickRecommendationAndSubmit(page);
    await clickRecommendationAndSubmit(page);
  }

  await page.locator('[data-screen="orders"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#orders-table input[data-order]').length > 20);
  await addScene(page, 'public_orders', 'Y2Q1 公开订单池出现后，系统按资格、利润、交期和可执行产能筛选机会。', 7);

  const orderRows = page.locator('#orders-table tr');
  const products = new Map();
  for (let i = 0; i < Math.min(await orderRows.count(), 100); i += 1) {
    const row = orderRows.nth(i);
    const box = row.locator('input[data-order]');
    if (!(await box.count())) continue;
    const product = (await row.locator('td').nth(4).textContent()).trim();
    const items = products.get(product) || [];
    items.push(box);
    products.set(product, items);
  }
  const pair = [...products.values()].find(items => items.length >= 2);
  if (pair) {
    await pair[0].check();
    await pair[1].check();
    await page.locator('#claim-portfolio').click();
    await addScene(page, 'portfolio_claim', '组合申领为主订单生成同产品、容量兼容的回退候选，降低冲突后的空置。', 7);
    await page.locator('#clear-plan').click();
  }

  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#phase-pill').textContent.includes('获单后履约'));
  await addScene(page, 'awarded_orders', '环境独立处理六家企业的订单竞争，只把 TEAM_01 的实际获单反馈回来。', 7);

  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await addScene(page, 'fulfillment_plan', 'Agent 根据实际获单重新安排融资、采购、生产和交付，而不是读取历史终局答案。', 7);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#period').textContent === 'Y2Q2');
  await page.locator('[data-screen="reports"]').click();
  await addScene(page, 'feedback', '提交后的现金、交付、违约和破产由确定性状态机结算，并反馈到下一季度。', 7);

  await page.locator('#back-lobby').click();
  await page.locator('input[name="name"]').fill('GoAI 纯 Agent 终局演示');
  await page.locator('input[name="team_count"]').fill('6');
  await page.locator('input[name="human_slots"]').fill('0');
  await page.locator('select[name="bot_policy"]').selectOption('mixed');
  await page.locator('input[name="seed"]').fill('20260818');
  await page.locator('#create-form button[type="submit"]').click();
  await page.waitForSelector('#game-view:not(.hidden)');
  await page.locator('#start-match').click();
  await page.locator('#advance-bots').click();
  await page.waitForFunction(() => document.querySelector('#phase-pill').textContent.includes('获单后履约'));
  await addScene(page, 'agent_stage', '纯 Agent 训练场可以逐阶段观察，也可以自动运行完整 5 年 20 季度。', 6);
  await page.locator('#run-bots').click();
  await page.waitForFunction(() => document.querySelector('#status-pill').textContent.includes('已结束'), null, { timeout: 120000 });
  await page.locator('[data-screen="ranking"]').click();
  await addScene(page, 'terminal_ranking', '终局由环境统一生成排名、破产状态和可审计记录，用于比较不同策略。', 8);

  const finalMatch = await page.evaluate(() => ({
    matchId: document.querySelector('#match-id').textContent,
    period: document.querySelector('#period').textContent,
    progress: document.querySelector('#progress-text').textContent,
    ranking: [...document.querySelectorAll('#ranking-table tr')].map(row => [...row.children].map(cell => cell.textContent.trim())),
  }));
  fs.writeFileSync(path.join(output, 'scenes.json'), JSON.stringify({ scenes, finalMatch, consoleErrors }, null, 2));
  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(' | ')}`);
})();
