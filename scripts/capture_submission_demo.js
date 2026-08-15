const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs = require('fs');
const path = require('path');

const base = 'http://127.0.0.1:8765';
const output = path.resolve(process.argv[2] || 'artifact/submission/demo');
fs.mkdirSync(output, { recursive: true });
const voiceManifestPath = path.join(output, 'voice_manifest.json');
const voiceManifest = fs.existsSync(voiceManifestPath) ? JSON.parse(fs.readFileSync(voiceManifestPath, 'utf8')) : { segments: [] };

const scenes = [];
let recordingStarted = Date.now();
const addScene = async (page, name, caption, duration = 5) => {
  await page.evaluate(text => {
    let node = document.querySelector('#demo-caption');
    if (!node) {
      node = document.createElement('div');
      node.id = 'demo-caption';
      Object.assign(node.style, { position: 'fixed', left: '50%', bottom: '24px', transform: 'translateX(-50%)', zIndex: 9999, maxWidth: '1100px', padding: '13px 22px', borderRadius: '12px', background: 'rgba(13,55,39,.94)', color: '#fff', fontSize: '18px', lineHeight: '1.55', boxShadow: '0 12px 32px rgba(0,0,0,.25)', textAlign: 'center' });
      document.body.appendChild(node);
    }
    node.textContent = text;
  }, caption);
  const file = path.join(output, `${String(scenes.length + 1).padStart(2, '0')}_${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  const voiceDuration = Number(voiceManifest.segments?.[scenes.length]?.duration_seconds || 0);
  const atSeconds = (Date.now() - recordingStarted) / 1000;
  const holdSeconds = Math.max(duration * 0.45, voiceDuration + 0.8);
  scenes.push({ file, caption, duration, at_seconds: Number(atSeconds.toFixed(3)), hold_seconds: Number(holdSeconds.toFixed(3)) });
  await page.waitForTimeout(holdSeconds * 1000);
};

const clickRecommendationAndSubmit = async (page) => {
  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await page.waitForFunction(() => !document.querySelector('#submit-plan').disabled, null, { timeout: 60000 });
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => !document.querySelector('#submit-plan').disabled, null, { timeout: 60000 });
};

(async () => {
  const browser = await chromium.launch({
    executablePath: '/usr/bin/google-chrome',
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, recordVideo: { dir: output, size: { width: 1440, height: 900 } } });
  const page = await context.newPage();
  recordingStarted = Date.now();
  const video = page.video();
  const consoleErrors = [];
  page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });

  await page.goto(base, { waitUntil: 'networkidle' });
  await addScene(page, 'lobby', '创建可重复的企业经营比赛：每类模拟对手都有行为说明，支持人机、多人、纯用户和纯 Agent。', 6);

  await page.locator('input[name="name"]').fill('青屿制造人机协同演示赛');
  await page.locator('input[name="team_count"]').fill('6');
  await page.locator('input[name="human_slots"]').fill('1');
  await page.locator('select[name="bot_policy"]').selectOption('mixed');
  await page.locator('input[name="creator_name"]').fill('青屿制造');
  await page.locator('input[name="seed"]').evaluate(input => { input.value = '20260817'; });
  await page.locator('#create-form button[type="submit"]').click();
  await page.waitForSelector('#game-view:not(.hidden)');
  await page.locator('#start-match').click();
  await page.waitForFunction(() => document.querySelector('#status-pill').textContent.includes('比赛中'));
  await addScene(page, 'initial_state', '经营主界面只展示本企业现金、负债、产能和订单；Agent 可靠性指标与正式盘面分开。', 7);

  await page.locator('[data-screen="rules"]').click();
  await addScene(page, 'generated_rules', '每场模拟赛生成自己的比赛规则通知；规则来自综合沙盘机制范围，不冒充任何赛事官方规则。', 7);
  await page.locator('[data-screen="command"]').click();
  await page.locator('#user-prompt').fill('当前经营状况怎么样？本季度适合哪种风险档位？请解释融资、资格和产能动作。');

  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length >= 1);
  await addScene(page, 'agent_plan', 'Agent 如实回答当前状态，推荐风险档位，再由六个专业模块生成带公式、警告与风险预演的联合方案。', 7);
  const firstRemove = page.locator('#plan-list [data-remove]').first();
  if (await firstRemove.count()) await firstRemove.click();
  await addScene(page, 'human_edit', '人工删除一项建议后再提交；待提交区使用业务语言，不暴露内部 JSON。', 5);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#period').textContent === 'Y1Q2');

  await page.locator('[data-screen="global-orders"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#orders-table input[data-order]').length >= 700);
  await addScene(page, 'public_orders', '全赛程订单从开局即可查看，用于提前规划资格和产能；第一年度没有订单，未到申领窗口不能勾选。', 7);

  // Advance to Y1Q4, one quarter before the first Y2Q1 order release.
  await page.locator('[data-screen="command"]').click();
  await clickRecommendationAndSubmit(page);
  await clickRecommendationAndSubmit(page);
  await page.waitForFunction(() => document.querySelector('#period').textContent === 'Y1Q4');
  await page.locator('[data-screen="global-orders"]').click();
  await page.waitForFunction(() => document.querySelectorAll('#orders-table input[data-order]:not(:disabled)').length > 0);
  await addScene(page, 'claim_window', 'Y1Q4 进入 Y2Q1 订单的广告与申领窗口；每条订单的申领期、释放期和交期都可核验。', 7);

  const orderRows = page.locator('#orders-table tr');
  const products = new Map();
  for (let i = 0; i < Math.min(await orderRows.count(), 100); i += 1) {
    const row = orderRows.nth(i);
    const box = row.locator('input[data-order]');
    if (!(await box.count()) || await box.isDisabled()) continue;
    const product = (await row.locator('td').nth(4).textContent()).trim();
    const items = products.get(product) || [];
    items.push(box);
    products.set(product, items);
  }
  const pair = [...products.values()].find(items => items.length >= 2);
  if (pair && await page.locator('#claim-portfolio').isEnabled()) {
    await pair[0].check();
    await pair[1].check();
    await page.locator('#claim-portfolio').click();
    await addScene(page, 'portfolio_claim', '组合申领为主订单生成同产品、容量兼容的回退候选，降低冲突后的空置。', 7);
    await page.locator('#clear-plan').click();
  }

  await page.locator('[data-screen="command"]').click();
  await page.locator('#get-recommendation').click();
  await page.waitForFunction(() => document.querySelectorAll('#plan-list .plan-item').length > 0);
  await page.locator('#submit-plan').click();
  await page.waitForFunction(() => document.querySelector('#period').textContent === 'Y2Q1');
  await page.locator('[data-screen="owned-orders"]').click();
  await addScene(page, 'awarded_orders', '环境独立处理六家企业的订单竞争；结算后只把青屿制造的实际获单写入本企业订单页。', 7);

  await page.locator('[data-screen="reports"]').click();
  await addScene(page, 'feedback', '季度提交后，独立模拟器生成裁判反馈、状态变化、报表和复盘建议，供下一季度滚动修订。', 7);

  await page.locator('[data-screen="evaluation"]').click();
  await addScene(page, 'agent_evaluation', 'Agent 可靠性页单独展示决策依据、风险预演和人机差异，明确这些不是比赛官方盘面。', 7);

  page.once('dialog', dialog => dialog.accept());
  await page.locator('#autopilot-player').click();
  await page.waitForFunction(() => document.querySelector('#status-pill').textContent.includes('已结束'), null, { timeout: 120000 });
  await page.locator('[data-screen="reports"]').click();
  await addScene(page, 'terminal_review', 'Agent 托管仍逐季度向环境提交动作；无论输赢，比赛结束后都会生成基于实际结算的终局复盘。', 7);
  await page.locator('[data-screen="ranking"]').click();
  await addScene(page, 'terminal_ranking', '终局由环境统一生成排名、破产状态和可审计记录，用于比较不同策略。', 8);

  const finalMatch = await page.evaluate(() => ({
    matchId: document.querySelector('#match-id').textContent,
    period: document.querySelector('#period').textContent,
    progress: document.querySelector('#progress-text').textContent,
    ranking: [...document.querySelectorAll('#ranking-table tr')].map(row => [...row.children].map(cell => cell.textContent.trim())),
  }));
  fs.writeFileSync(path.join(output, 'scenes.json'), JSON.stringify({ scenes, finalMatch, consoleErrors, statement: '本视频证明规则生成、部分可观测、年度规划与季度单次提交、带理由建议、人工修订、订单竞争、反馈重规划、独立结算和终局审计闭环；不证明任意真实对手下策略最优。' }, null, 2));
  await context.close();
  await video.saveAs(path.join(output, 'StratPilot_Interactive_Demo_Silent.webm'));
  await browser.close();
  if (consoleErrors.length) throw new Error(`Browser console errors: ${consoleErrors.join(' | ')}`);
})();
