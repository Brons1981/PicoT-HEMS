// Real HC HTTP server and browser; HA is intentionally disconnected.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const data = mkdtempSync(path.join(tmpdir(), 'hc-browser-'));
  const root = path.resolve(__dirname, '..');
  const server = spawn('python3', ['-m', 'picot_hc', '--config', 'options.example.json', '--data', data, '--port', '19099'], {cwd: root});
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
    rmSync(data, {recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
