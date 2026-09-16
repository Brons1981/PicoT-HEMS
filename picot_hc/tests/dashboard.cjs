// Real HC server and browser with a simulated HA API; no real devices.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const {mkdtempSync, rmSync, readFileSync, writeFileSync} = require('node:fs');
const {tmpdir} = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const http = require('node:http');
const {gunzipSync} = require('node:zlib');
(async () => {
  const data = mkdtempSync(path.join(tmpdir(), 'hc-browser-'));
  const root = path.resolve(__dirname, '..');
  const weatherState = {entity_id:'weather.buienradar',state:'cloudy',last_updated:new Date().toISOString(),
    attributes:{temperature:20.7,apparent_temperature:20.7,temperature_unit:'°C',humidity:81,
      pressure:1021.3,pressure_unit:'hPa',wind_speed:9.72,wind_gust_speed:18,wind_speed_unit:'km/h',precipitation_unit:'mm'}};
  const deviceCalls=[];
  const deviceStates=['climate.airco_woonkamer','climate.19791209313101_climate','climate.huiskamer','switch.1_5_3_badkamer_verwarming_badkamer'].map(entity_id=>({entity_id,state:'off',last_updated:new Date().toISOString(),attributes:{temperature:20,min_temp:16,max_temp:30,target_temp_step:0.5,supported_features:1,hvac_modes:['off','heat','dry'],hvac_action:'idle'}}));
  const cv=deviceStates.find(s=>s.entity_id==='climate.huiskamer');
  delete cv.attributes.target_temp_step;
  Object.assign(cv.attributes,{min_temp:5,supported_features:401,hvac_modes:['off','heat','auto']});
  deviceStates.push({entity_id:'sensor.downstairs',state:'19',attributes:{unit_of_measurement:'°C'},last_reported:new Date().toISOString()});
  const doorState={entity_id:'binary_sensor.1_3_woonkamer_deur_raam_sensor_achterdeur_contact',state:'on',attributes:{device_class:'door'},last_updated:new Date().toISOString()};
  deviceStates.push(doorState,{entity_id:'sensor.gw1200a_temperature_1',state:'10',attributes:{unit_of_measurement:'°C'},last_reported:new Date().toISOString()});
  const options=JSON.parse(readFileSync(path.join(root,'options.example.json'),'utf8'));
  options.zones[0].temperature='sensor.downstairs';options.poll_seconds=10;options.stale_seconds=30;
  for(const [entity_id,state,attributes] of [
    ['sensor.gw1200a_indoor_dewpoint','11.5',{unit_of_measurement:'°C'}],
    ['sensor.gw1200a_dewpoint_2','12.5',{unit_of_measurement:'°C'}],
    ['sensor.gw1200a_humidity_2','70',{unit_of_measurement:'%'}],
    ['sensor.gw1200a_dewpoint_3','14.5',{unit_of_measurement:'°C'}],
    ['sensor.gw1200a_dewpoint_1','8.5',{unit_of_measurement:'°C'}],
    ['binary_sensor.gw1200a_battery_1','off',{device_class:'battery'}],
    ['binary_sensor.gw1200a_battery_2','on',{device_class:'battery'}],
    ['binary_sensor.gw1200a_battery_3','unavailable',{device_class:'battery'}],
  ]) deviceStates.push({entity_id,state,attributes,last_updated:new Date().toISOString()});
  const configPath=path.join(data,'options.json');writeFileSync(configPath,JSON.stringify(options));
  const fakeHA = http.createServer((req,res) => {
    res.setHeader('Content-Type','application/json');
    deviceStates.find(s=>s.entity_id==='sensor.downstairs').last_reported=new Date().toISOString();
    if(req.method === 'GET' && req.url === '/api/states') res.end(JSON.stringify([weatherState,...deviceStates]));
    else if(req.method === 'GET' && req.url === '/api/config') res.end(JSON.stringify({unit_system:{temperature:'°C'}}));
    else if(req.method === 'POST' && req.url === '/api/template') {
      let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
        const ids=JSON.parse(JSON.parse(body).template.split('{% for id in ')[1].split(' %}')[0]);
        res.end(JSON.stringify(deviceStates.filter(s=>ids.includes(s.entity_id)).map(s=>({...s,last_reported:s.actual_reported||s.last_reported||s.last_updated,last_updated:s.last_updated||s.last_reported}))));
      });
    }
    else if(req.method === 'POST' && ['/api/services/climate/set_hvac_mode','/api/services/climate/set_temperature','/api/services/switch/turn_on','/api/services/switch/turn_off'].includes(req.url)) {
      let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{
        const payload=JSON.parse(body);deviceCalls.push({path:req.url,payload});
        const device=deviceStates.find(s=>s.entity_id===payload.entity_id);
        if(payload.hvac_mode)device.state=payload.hvac_mode;
        if(payload.temperature!=null)device.attributes.temperature=payload.temperature;
        if(req.url.includes('/services/switch/'))device.state=req.url.endsWith('turn_on')?'on':'off';
        device.last_updated=new Date().toISOString();res.end('[]');
      });
    }
    else if(req.method === 'POST' && req.url === '/api/services/weather/get_forecasts?return_response') {
      req.resume();
      res.end(JSON.stringify({service_response:{'weather.buienradar':{forecast:[1,2,3,4,5].map(days=>({datetime:new Date(Date.now()+days*86400000).toISOString(),condition:'rainy',temperature:18,templow:11,precipitation:days===2?0.04:days===3?0.001:0,wind_speed:12}))}}}));
    } else {res.statusCode=404;res.end('{}');}
  });
  await new Promise(resolve=>fakeHA.listen(19098,'127.0.0.1',resolve));
  const server = spawn('python3', ['-m', 'picot_hc', '--config', configPath, '--data', data, '--port', '19099'], {cwd: root, env:{...process.env, HC_HA_API:'http://127.0.0.1:19098/api', HC_HA_TOKEN:'browser-test-token'}});
  let browser;
  try {
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    // Local HA over HTTP has getRandomValues, but no randomUUID.
    await page.addInitScript(()=>Object.defineProperty(crypto,'randomUUID',{value:undefined,configurable:true}));
    page.setDefaultTimeout(30000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    for(let i=0;i<50;i++) {
      try { await page.goto('http://127.0.0.1:19099'); break; }
      catch(error) { if(i===49) throw error; await new Promise(resolve=>setTimeout(resolve,100)); }
    }
    const form = page.locator('form.temperature-settings').first();
    await form.waitFor();
    assert.equal(await page.locator('form.temperature-settings').count(), 3);
    await page.waitForFunction(()=>document.querySelectorAll('.forecast-day').length===5);
    assert.match(await page.locator('#weather-measured').textContent(), /Dauwpunt: 8,5 °C/);
    assert.match(await page.locator('#weather-measured').textContent(), /Sensorbatterij: Normaal/);
    const zoneText=await page.locator('#zones').textContent();
    assert.match(zoneText,/11,5 °C/);assert.match(zoneText,/12,5 °C/);assert.match(zoneText,/14,5 °C/);
    assert.match(zoneText,/SensorbatterijNiet van toepassing/);
    assert.match(zoneText,/SensorbatterijBatterij bijna leeg/);
    assert.match(zoneText,/SensorbatterijNiet beschikbaar/);
    assert.equal(await page.locator('#zones .battery-low').count(),1);
    assert.equal(await page.locator('.zone-climate-panel canvas').count(),3);
    assert.match(await page.locator('#climate-readout-beneden').textContent(),/Temperatuur 19 °C/);
    assert.match(await page.locator('#climate-readout-beneden').textContent(),/Dauwpunt 11,5 °C/);
    assert.match(await page.locator('#climate-readout-beneden').textContent(),/Luchtvochtigheid Niet beschikbaar/);
    assert.match(await page.locator('#climate-readout-boven').textContent(),/Dauwpunt 12,5 °C/);
    assert.match(await page.locator('#climate-readout-badkamer').textContent(),/Dauwpunt 14,5 °C/);
    assert.match(await page.locator('#climate-readout-boven').textContent(),/Luchtvochtigheid 70 %/);
    const climateCanvas=page.locator('#climate-beneden');
    await climateCanvas.focus();await page.keyboard.press('ArrowLeft');
    assert.match(await page.locator('#climate-readout-beneden').textContent(),/Temperatuur 19 °C/);
    await climateCanvas.click({position:{x:100,y:100}});
    assert.equal(await page.evaluate(()=>document.querySelector('#climate-beneden').userSelected),true);
    assert.match(await page.locator('#building-status').textContent(),/Registratie loopt/);
    assert.match(await page.locator('#building-retention').textContent(),/90 dagen/);
    assert.match(await page.locator('#zones .zone').first().textContent(),/Binnen − buiten9 °C/);
    assert.match(await page.locator('#zones .zone').first().textContent(),/AchterdeurOpen/);
    const [download]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Meetgegevens downloaden'}).click()]);
    const archive=gunzipSync(readFileSync(await download.path())).toString();
    const measurements=archive.trim().split('\n').map(row=>JSON.parse(row));
    assert.equal(measurements[0].format,'picot_hc_building_history');
    assert.equal(measurements.at(-1).building.back_door.value,'on');
    assert.equal(measurements.at(-1).building.zones[0].delta_t_k,9);
    assert.equal(deviceCalls.length,0);
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
    assert.equal(deviceCalls.length,0,'Startup and settings changes must never dispatch');
    assert.equal(await page.evaluate(()=>typeof crypto.randomUUID),'undefined');
    const source=page.locator('.source-control').filter({has:page.getByRole('heading',{name:'Beneden',exact:true})});
    await source.locator('select').selectOption('heat');
    await page.evaluate(()=>{
      window.originalGetRandomValues=crypto.getRandomValues.bind(crypto);
      crypto.getRandomValues=()=>{throw Error('Opdracht voorbereiden mislukt');};
    });
    await source.getByRole('button',{name:'Modus toepassen',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.command-status') && [...document.querySelectorAll('.command-status')].some(s=>s.textContent==='Opdracht voorbereiden mislukt'));
    assert.equal(deviceCalls.length,0,'Preparation failure must not dispatch');
    assert.equal(await source.getByRole('button',{name:'Modus toepassen',exact:true}).isEnabled(),true);
    await page.evaluate(()=>{crypto.getRandomValues=window.originalGetRandomValues;});
    await source.getByRole('button',{name:'Modus toepassen',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#command-history').textContent.includes('Instelling bevestigd'));
    assert.equal(deviceCalls.length,1);
    assert.equal(deviceCalls[0].payload.hvac_mode,'heat');
    await source.locator('input').fill('21.5');
    await source.getByRole('button',{name:'Temperatuur toepassen',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#command-history').textContent.includes('Instelling bevestigd · 21.5 °C'));
    assert.equal(deviceCalls.length,2);
    assert.equal(deviceCalls[1].payload.temperature,21.5);
    await source.getByRole('button',{name:'Uit',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#command-history').textContent.includes('Instelling bevestigd · Uit'));
    assert.equal(deviceCalls.length,3);
    await page.reload();
    await page.locator('.source-control').first().waitFor();
    assert.equal(deviceCalls.length,3,'Reload must not replay commands');
    const cvCard=page.locator('.source-control').filter({has:page.getByRole('heading',{name:'Cv · beneden en boven',exact:true})});
    await cvCard.locator('select').selectOption('auto');
    await cvCard.getByRole('button',{name:'Modus toepassen',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#command-history').textContent.includes('Instelling bevestigd · Automatisch'));
    assert.equal(await cvCard.locator('input').getAttribute('step'),'0.5');
    await cvCard.locator('input').fill('19.5');
    await cvCard.getByRole('button',{name:'Temperatuur toepassen',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#command-history').textContent.includes('Instelling bevestigd · 19.5 °C'));
    assert.equal(deviceCalls.length,5);
    assert.deepEqual(deviceCalls[4],{path:'/api/services/climate/set_temperature',payload:{entity_id:'climate.huiskamer',temperature:19.5}});
    const schedule=page.locator('.schedule-form');
    assert.equal(await schedule.locator('[name=source]').count(),0,'Comfort windows cannot bind a source');
    assert.equal(await page.getByRole('heading',{name:'Vaste temperatuur instellen',exact:true}).count(),2);
    assert.equal(await schedule.locator('[name=minimum], [name=maximum]').count(),0);
    await schedule.locator('[name=optimization_band]').fill('1');
    await schedule.getByRole('button',{name:'Venster toevoegen'}).click();
    const evening=schedule.locator('.schedule-row').last();
    await evening.getByRole('button',{name:'Alle dagen',exact:true}).click();
    await evening.locator('[name=start]').fill('18:00');
    await evening.locator('[name=end]').fill('22:00');
    await evening.locator('[name=target]').fill('20');
    await evening.locator('[name=hard]').check();
    await evening.getByRole('button',{name:'Dupliceren',exact:true}).click();
    const night=schedule.locator('.schedule-row').last();
    await night.getByRole('button',{name:'Ma–vr',exact:true}).click();
    await night.locator('[name=start]').fill('22:00');
    await night.locator('[name=end]').fill('06:00');
    await night.locator('[name=target]').fill('17');
    await night.locator('[name=hard]').uncheck();
    await page.evaluate(()=>refresh());
    assert.equal(await schedule.locator('.schedule-row').count(),2,'Refresh retains unsaved windows');
    await schedule.getByRole('button',{name:'Comfortschema opslaan'}).click();
    await page.waitForFunction(()=>document.querySelector('.schedule-save-status').textContent==='Comfortschema opgeslagen.');
    await page.reload();
    await page.waitForFunction(()=>document.querySelectorAll('.schedule-row').length===2);
    assert.equal(deviceCalls.length,5,'Saving comfort requirements must not dispatch');
    assert.equal(await page.evaluate(()=>current.schedule.settings.windows.length),12);
    assert.equal(await schedule.locator('[name=optimization_band]').inputValue(),'1');
    assert.equal(await schedule.locator('[name=day]:checked').count(),12);
    await schedule.locator('[name=enabled]').check();
    await schedule.getByRole('button',{name:'Comfortschema opslaan'}).click();
    await page.waitForFunction(()=>document.querySelector('.schedule-save-status').textContent==='Comfortschema opgeslagen.');
    await page.evaluate(()=>refresh());
    assert.equal(await page.evaluate(()=>current.schedule.comfort.planner_status),'not_implemented');
    assert.equal(await page.evaluate(()=>current.schedule.comfort.selected_sources),null);
    assert.equal(deviceCalls.length,5,'Enabling a comfort schedule must not choose or dispatch a source');
    cv.attributes.temperature=18.5;cv.last_updated=new Date().toISOString();
    await page.waitForFunction(()=>current?.schedule?.overrides?.some(h=>h.source==='cv'&&h.temperature===18.5&&h.status==='observed'),null,{timeout:45000});
    assert.match(await page.locator('#forced-sources').textContent(),/Gedwongen bron: 18.5 °C/);
    assert.equal(deviceCalls.length,5);
    await cvCard.locator('input').fill('20.5');
    await cvCard.getByRole('button',{name:'Temperatuur toepassen',exact:true}).click();
    await page.waitForFunction(()=>current?.schedule?.overrides?.some(h=>h.source==='cv'&&h.temperature===20.5&&h.confirmed));
    assert.equal(deviceCalls.length,6);
    assert.equal(await page.evaluate(()=>current.schedule.overrides.find(h=>h.source==='cv').until!==null),true);
    await schedule.getByRole('button',{name:'HC hervatten'}).click();
    await page.waitForFunction(()=>document.querySelector('.schedule-save-status').textContent==='Handmatige bronkeuzes vrijgegeven.');
    assert.equal(await page.evaluate(()=>current.schedule.overrides.length),0);
    assert.equal(cv.attributes.temperature,20.5,'Resume clears the constraint without inventing a financial plan');
    assert.equal(deviceCalls.length,6);
    await schedule.locator('[name=enabled]').uncheck();
    await schedule.getByRole('button',{name:'Comfortschema opslaan'}).click();
    await page.waitForFunction(()=>document.querySelector('.schedule-save-status').textContent==='Comfortschema opgeslagen.');
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#schedule-status').textContent.startsWith('Tijdvensters staan uit'));
    assert.equal(deviceCalls.length,6);
    doorState.state='unknown';
    await page.waitForFunction(()=>document.querySelector('#zones .zone').textContent.includes('AchterdeurOnbekend'),null,{timeout:45000});
    // Enable the real automatic regulator through the UI, with simulated sources.
    for(const device of deviceStates.filter(d=>d.entity_id.startsWith('climate.')||d.entity_id.startsWith('switch.')))device.state='off';
    for(const zone of options.zones){
      let sensor=deviceStates.find(d=>d.entity_id===zone.temperature);
      if(!sensor){sensor={entity_id:zone.temperature,attributes:{unit_of_measurement:'°C'}};deviceStates.push(sensor);}
      // Reproduce HA's cached REST report while direct template data remains fresh.
      sensor.state='18';sensor.last_reported=new Date(Date.now()-3600000).toISOString();
      sensor.actual_reported=new Date().toISOString();
    }
    deviceStates.push({entity_id:options.price_entity,state:'0.25',attributes:{unit_of_measurement:'EUR/kWh',raw_today:[{start:new Date(Date.now()-3600000).toISOString(),end:new Date(Date.now()+3600000).toISOString(),value:.25}]}});
    doorState.state='off';
    await schedule.locator('details summary').click();
    await schedule.locator('[name=door_close_seconds]').fill('0');
    await schedule.getByRole('button',{name:'Comfortschema opslaan'}).click();
    await page.waitForFunction(()=>document.querySelector('.schedule-save-status').textContent==='Comfortschema opgeslagen.');
    for(const zoneForm of await page.locator('.temperature-settings').all()){
      await zoneForm.locator('[name=minimum]').fill('10');await zoneForm.locator('[name=target]').fill('20');await zoneForm.locator('[name=maximum]').fill('25');
      await zoneForm.getByRole('button',{name:'Opslaan',exact:true}).click();
      await page.waitForFunction(()=>![...document.querySelectorAll('.temperature-settings button')].some(b=>b.disabled));
    }
    await page.evaluate(async()=>{await fetch('api/resume',{method:'POST',headers:{'Content-Type':'application/json','X-HC-CSRF':current.csrf_token},body:'{}'});});
    const heating=page.locator('#heating-editor .heating-form');
    await heating.locator('[name=cop_boven]').fill('3.1');
    await page.evaluate(()=>refresh());
    assert.equal(await heating.locator('[name=cop_boven]').inputValue(),'3.1');
    await heating.locator('[name=enabled]').check();
    await heating.getByRole('button',{name:'Regeling opslaan',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.heating-save-status').textContent==='Regeling opgeslagen.');
    await page.waitForFunction(()=>current?.commands?.filter(c=>c.origin==='schedule'&&c.field!=='mode'&&c.status==='confirmed').length>=3,null,{timeout:90000});
    assert.equal(deviceStates.find(d=>d.entity_id===options.zones[0].device).state,'heat');
    assert.equal(deviceStates.find(d=>d.entity_id===options.zones[1].device).state,'heat');
    assert.equal(deviceStates.find(d=>d.entity_id===options.zones[2].device).state,'on');
    assert.equal(cv.state,'off');
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#heating-editor input[name=enabled]')?.checked);
    assert.equal(await heating.locator('[name=cop_boven]').inputValue(),'3.1');
    await heating.getByRole('button',{name:'Automatische verwarming uit',exact:true}).click();
    await page.waitForFunction(()=>current?.heating&&!current.heating.enabled&&Object.keys(current.heating.owned).length===0,null,{timeout:90000});
    assert.ok(deviceStates.filter(d=>d.entity_id.startsWith('climate.')||d.entity_id.startsWith('switch.')).every(d=>d.state==='off'));
    const timer=page.locator('#bathroom-timer');
    await timer.locator('[name=minutes]').fill('15');
    await timer.locator('[name=temperature]').fill('17');
    await page.evaluate(()=>refresh());
    assert.equal(await timer.locator('[name=minutes]').inputValue(),'15');
    await timer.getByRole('button',{name:'Start timer',exact:true}).click();
    await page.waitForFunction(()=>current.heating.timer.active);
    assert.equal(await page.evaluate(()=>current.heating.timer.temperature),17);
    await page.reload();
    await page.waitForFunction(()=>document.querySelector('#bathroom-timer')?.textContent.includes('Timer actief: 17'));
    assert.equal(await timer.locator('[name=minutes]').inputValue(),'15');
    await timer.getByRole('button',{name:'Stop timer',exact:true}).click();
    await page.waitForFunction(()=>current.heating.timer.status==='stopped');
    assert.equal(await page.evaluate(()=>current.heating.enabled),false);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Dashboard: settings, manual commands without randomUUID, feedback, reload and mobile width passed.');
  } finally {
    if(browser) await browser.close();
    server.kill();
    await new Promise(resolve => server.exitCode !== null ? resolve() : server.once('exit',resolve));
    await new Promise(resolve=>fakeHA.close(resolve));
    rmSync(data, {recursive:true,force:true});
  }
})().catch(error => {console.error(error);process.exitCode=1;});
