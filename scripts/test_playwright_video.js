const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
(async()=>{
  const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
  const context=await browser.newContext({viewport:{width:960,height:600},recordVideo:{dir:'/tmp/goai_video_test',size:{width:960,height:600}}});
  const page=await context.newPage();
  await page.goto('http://127.0.0.1:8765');
  await page.waitForTimeout(1500);
  await context.close();
  await browser.close();
})();
