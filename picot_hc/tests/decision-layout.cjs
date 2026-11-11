const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const decision=require('./decision-explanation.cjs');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.HC_BROWSER_EXECUTABLE?{executablePath:process.env.HC_BROWSER_EXECUTABLE}:{})});
 try {
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<!doctype html><html lang="nl"><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><main><section class="panel"><div id="decision"></div><div id="costs"></div></section></main></body></html>');
  await page.addStyleTag({content:fs.readFileSync(path.join(__dirname,'../picot_hc/web/style.css'),'utf8')});
  await page.addScriptTag({content:'function el(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;}'});
  await page.addScriptTag({content:fs.readFileSync(path.join(__dirname,'../picot_hc/web/heating.js'),'utf8')});
  await page.evaluate(d=>{renderHeatDecision(document.getElementById('decision'),d);renderHeatPrices(document.getElementById('costs'),d);},decision);
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   assert.ok((await page.locator('#decision').innerText()).includes('CV gekozen omdat'));
  }
  assert.deepEqual(errors,[]);
  console.log('Decision layout passed at desktop and mobile widths.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
