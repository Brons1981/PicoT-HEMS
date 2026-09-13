// Real HC HTTP server and browser; HA is intentionally disconnected.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');
(async () => {
  const data = mkdtempSync(path.join(tmpdir(), 'hc-browser-'));
  const root = path.resolve(__dirname, '..');
  const weatherState = {entity_id:'weather.buienradar',state:'cloudy',last_updated:new Date().toISOString(),
    attributes:{temperature:20.7,apparent_temperature:20.7,temperature_unit:'°C',humidity:81,
      pressure:1021.3,pressure_unit:'hPa',wind_speed:9.72,wind_gust_speed:18,wind_speed_unit:'km/h',precipitation_unit:'mm'}};
  const fakeHA = http.createServer((req,res) => {
    res.setHeader('Content-Type','application/json');
    if(req.method === 'GET' && req.url === '/api/states') res.end(JSON.stringify([weatherState]));
    else if(req.method === 'POST' && req.url === '/api/services/weather/get_forecasts?return_response') {
      req.resume();
      res.end(JSON.stringify({service_response:{'weather.buienradar':{forecast:[1,2,3,4,5].map(days=>({datetime:new Date(Date.now()+days*86400000).toISOString(),condition:'rainy',temperature:18,templow:11,precipitation:days===2?0.04:days===3?0.001:0,wind_speed:12}))}}}));
    } else {res.statusCode=404;res.end('{}');}
  });
  await new Promise(resolve=>fakeHA.listen(19098,'127.0.0.1',resolve));
  const server = spawn('python3', ['-m', 'picot_hc', '--config', 'options.example.json', '--data', data, '--port', '19099'], {cwd: root, env:{...process.env, HC_HA_API:'http://127.0.0.1:19098/api', HC_HA_TOKEN:'browser-test-token'}});
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    for(let i=0;i<50;i++) {
      try { await page.goto('http://127.0.0.1:19099'); break; }
      catch(error) { if(i===49) throw error; await new Promise(resolve=>setTimeout(resolve,100)); }
    }
    const form = page.locator('form').first();
    await form.waitFor();
    assert.equal(await page.locator('form').count(), 3);
    await page.waitForFunction(()=>document.querySelectorAll('.forecast-day').length===5);
    assert.match(await page.locator('#weather-current').textContent(), /Bewolkt/);
    assert.match(await page.locator('#weather-current').textContent(), /20,7 °C/);
    assert.doesNotMatch(await page.locator('#weather-forecast').textContent(), /Neerslag | mm|bron voorspelt regen/);
    assert.match(await page.locator('.forecast-day').first().textContent(), /Regen/);
    assert.match(await page.locator('#price-description').textContent(), /Bevestigd elektriciteitstarief/);
    assert.doesNotMatch(await page.locator('#warnings').textContent(), /Tariefbasis nog niet bevestigd/);
    await form.locator('[name=minimum]').fill('16');
    await form.locator('[name=target]').fill('19.5');
    await form.locator('[name=maximum]').fill('22');
    // Invoke the actual refresh path while editing: DOM node and draft survive.
    await page.evaluate(() => refresh());
    assert.equal(await form.locator('[name=target]').inputValue(), '19.5');
    await form.getByRole('button', {name:'Opslaan'}).click();
    await page.waitForFunction(() => document.querySelector('.save-status').textContent.startsWith('Opgeslagen.'));
    await page.reload();
    await page.waitForFunction(() => document.querySelector('input[name=target]')?.value === '19.5');
    await form.locator('[name=minimum]').fill('23');
    await form.getByRole('button', {name:'Opslaan'}).click();
    assert.match(await form.locator('.save-status').textContent(), /minimum/);
    await page.reload();
    await page.waitForFunction(() => document.querySelector('input[name=minimum]')?.value === '16');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Dashboard: save, reload, refresh draft, invalid bounds and mobile width passed.');
  } finally {
    if(browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit',resolve));
    await new Promise(resolve=>fakeHA.close(resolve));
    rmSync(data, {recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
