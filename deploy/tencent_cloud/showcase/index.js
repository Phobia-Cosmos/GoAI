const http = require('node:http');

const PORT = 9000;
const HOST = '0.0.0.0';
const ASSET_ROOT = 'https://arithmetic-challenge-d0ac567f37e-1325808540.tcloudbaseapp.com/qice-assets';
const GITHUB_URL = 'https://github.com/Phobia-Cosmos/StratPilot';

const scenes = [
  ['01_lobby.png', '创建比赛', '选择企业数量、人类席位和模拟对手类型。'],
  ['03_generated_rules.png', '阅读本场规则', '每场模拟赛生成独立规则通知，比赛开始前即可查看。'],
  ['04_agent_plan.png', 'Agent 状态问答', 'Agent 根据我方状态回答问题、推荐风险档位并生成联合方案。'],
  ['06_post_allocation_y1q1.png', '查看实际获单', '系统自动完成统一订单分配，我方获单立即进入私有订单表。'],
  ['11_feedback.png', '系统评估与复盘', '独立模拟器根据真实状态转移生成裁判反馈、报表和复盘。'],
  ['13_terminal_ranking.png', '终局排名', '五年二十季度结束后生成排名、破产结果和可审计记录。'],
];

const escapeHtml = value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));

function page() {
  const sceneData = JSON.stringify(scenes).replace(/</g, '\\u003c');
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>StratPilot · 在线展示</title><style>
  :root{--ink:#17211d;--muted:#647069;--green:#164f3a;--lime:#d6ef80;--paper:#f4f1e9;--panel:#fffdf8;--line:#d9ddd6}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0,#e6edd9,transparent 36%),var(--paper);color:var(--ink);font-family:Inter,"PingFang SC","Microsoft YaHei",sans-serif}header{padding:20px 5vw;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #ccd3ca}header strong{font-size:22px;color:var(--green)}header span{font-size:13px;color:var(--muted)}main{width:min(1180px,92vw);margin:36px auto 70px}.hero{padding:52px;border-radius:24px;background:linear-gradient(135deg,#123e2f,#2f7458);color:white}.hero h1{font:700 clamp(40px,7vw,72px) Georgia,"Songti SC",serif;margin:10px 0}.hero h1 em{font-style:normal;color:var(--lime)}.hero p{max-width:800px;font-size:17px;line-height:1.8;color:#e5eee7}.actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:25px}.actions a{padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:800;background:var(--lime);color:var(--green)}.actions a.secondary{background:#fff;color:var(--green)}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:20px 0}.card,.demo,.notice{padding:22px;border:1px solid var(--line);border-radius:16px;background:var(--panel)}.card strong{display:block;color:var(--green);font-size:18px}.card p,.notice{font-size:14px;line-height:1.7;color:var(--muted)}.demo{margin-top:20px}.demo h2{font-size:27px;margin:0 0 8px}.demo video{width:100%;margin-top:15px;border-radius:12px;background:#102019}.scene{display:grid;grid-template-columns:1.5fr 1fr;gap:22px;align-items:center;margin-top:18px}.scene img{width:100%;border:1px solid var(--line);border-radius:12px}.scene h3{font-size:24px;color:var(--green)}.scene p{line-height:1.8;color:var(--muted)}.scene-nav{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}.scene-nav button{border:0;border-radius:8px;padding:9px 12px;background:#e8eee8;color:var(--green);font-weight:800;cursor:pointer}.scene-nav button.active{background:var(--green);color:#fff}.notice{border-left:5px solid var(--green);margin-top:20px}.metrics{display:flex;gap:24px;flex-wrap:wrap;margin-top:18px}.metrics strong{font:700 28px Georgia;color:var(--lime)}.metrics span{display:block;font-size:12px;color:#dce8df}@media(max-width:780px){.hero{padding:32px 24px}.grid{grid-template-columns:1fr}.scene{grid-template-columns:1fr}header span{display:none}}
  </style></head><body><header><strong>StratPilot</strong><span>企业经营沙盘决策智能体 · 公开成果展示</span></header><main><section class="hero"><p>ENTERPRISE DECISION INTELLIGENCE</p><h1>让复杂经营决策<br><em>可解释、可预演、可复盘。</em></h1><p>面向企业经营沙盘的单企业人机协同决策系统。多专业 Agent 联合分析资金、资格、产能、供应、订单和风险，独立模拟器负责统一订单分配、财务结算、违约与破产判定。</p><div class="metrics"><div><strong>20</strong><span>季度闭环</span></div><div><strong>800</strong><span>模拟订单</span></div><div><strong>110</strong><span>自动化测试通过</span></div><div><strong>13</strong><span>有声演示场景</span></div></div><div class="actions"><a href="#demo">观看有声 Demo</a><a class="secondary" href="${GITHUB_URL}" target="_blank" rel="noreferrer">查看公开仓库</a></div></section><section class="grid"><article class="card"><strong>决策智能体</strong><p>读取我方私有状态、公开订单和比赛规则，回答经营问题、推荐风险档位并生成带理由的动作方案。</p></article><article class="card"><strong>独立模拟环境</strong><p>Agent 不能直接修改状态；获单、现金、权益、违约、破产和报表均由确定性状态机统一结算。</p></article><article class="card"><strong>系统评估</strong><p>记录人工与 Agent 方案差异、季度反馈、年度报表和终局轨迹，为 VPD 与反事实复盘预留接口。</p></article></section><section id="demo" class="demo"><h2>带普通话讲解的操作演示</h2><p>标准普通话女声按操作场景同步讲解。视频使用虚构企业和模拟规则，不包含历史比赛原始数据。</p><video controls preload="metadata" poster="${ASSET_ROOT}/scenes/01_lobby.png"><source src="${ASSET_ROOT}/stratpilot-demo-zh.webm" type="video/webm">浏览器不支持 WebM 视频，请使用下载链接。</video><div class="actions"><a href="${ASSET_ROOT}/stratpilot-demo-zh.webm" download>下载有声视频</a></div><div class="scene"><img id="scene-image" src="${ASSET_ROOT}/scenes/${scenes[0][0]}" alt="${escapeHtml(scenes[0][1])}"><div><h3 id="scene-title">${escapeHtml(scenes[0][1])}</h3><p id="scene-caption">${escapeHtml(scenes[0][2])}</p><div id="scene-nav" class="scene-nav"></div></div></div></section><section class="notice"><strong>在线版本边界：</strong>当前腾讯 CloudBase 体验环境未开通容器云托管，因此本地址提供成果展示、有声视频与操作导览；完整可交互 Python 模拟器运行在私有部署和本地演示环境中。公开仓库不包含完整源码、原始比赛数据或可直接复现全部策略的参数。</section></main><script>const scenes=${sceneData},root=${JSON.stringify(ASSET_ROOT)},image=document.querySelector('#scene-image'),title=document.querySelector('#scene-title'),caption=document.querySelector('#scene-caption'),nav=document.querySelector('#scene-nav');scenes.forEach((row,index)=>{const button=document.createElement('button');button.textContent=index+1;button.onclick=()=>{image.src=root+'/scenes/'+row[0];image.alt=row[1];title.textContent=row[1];caption.textContent=row[2];[...nav.children].forEach((node,i)=>node.classList.toggle('active',i===index))};if(index===0)button.className='active';nav.appendChild(button)});</script></body></html>`;
}

http.createServer((request, response) => {
  if (request.url.endsWith('/health')) {
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify({ status: 'ok', service: 'stratpilot-showcase', version: '1.0.0' }));
    return;
  }
  response.writeHead(200, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'public, max-age=300',
    'Content-Security-Policy': "default-src 'self' https://arithmetic-challenge-d0ac567f37e-1325808540.tcloudbaseapp.com; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' https://arithmetic-challenge-d0ac567f37e-1325808540.tcloudbaseapp.com; media-src https://arithmetic-challenge-d0ac567f37e-1325808540.tcloudbaseapp.com; frame-ancestors 'none'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
  });
  response.end(page());
}).listen(PORT, HOST);
