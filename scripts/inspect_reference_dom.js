const { chromium } = require('/home/undefined/.npm/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs = require('fs');
(async()=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});
 const context=await browser.newContext({viewport:{width:1440,height:1000},ignoreHTTPSErrors:true});
 const page=await context.newPage();
 await page.goto('https://shapan.hdu.edu.cn/',{waitUntil:'domcontentloaded',timeout:60000});
 await page.waitForTimeout(2000);
 const frameData=[];
 for(const frame of page.frames()){
  const data=await frame.evaluate(()=>({
   url:location.href,
   elements:[...document.querySelectorAll('input,button,a,[onclick],[role="button"]')].map((el,index)=>({
    index,tag:el.tagName,type:el.getAttribute('type'),id:el.id,name:el.getAttribute('name'),
    text:(el.innerText||el.getAttribute('title')||el.getAttribute('placeholder')||'').trim().slice(0,120),
    href:el.getAttribute('href'),onclick:el.getAttribute('onclick'),visible:!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length)
   }))
  })).catch(e=>({url:frame.url(),error:String(e)}));
  frameData.push(data);
 }
 fs.writeFileSync('/tmp/goai_reference_dom.json',JSON.stringify(frameData,null,2));
 await browser.close();
})();
