const $=id=>document.getElementById(id);
const fmt=(t)=>new Intl.DateTimeFormat('nl-NL',{timeZone:'Europe/Amsterdam',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(t*1000));
const labels={not_configured:'Nog niet gekoppeld',missing:'Niet gevonden',unknown:'Onbekend',unavailable:'Niet beschikbaar',invalid:'Ongeldige waarde',unit_mismatch:'Eenheid controleren',device_class_mismatch:'Type batterijsensor controleren'};
function value(s){return s.quality==='available'?`${typeof s.value==='number'?s.value.toLocaleString('nl-NL',{maximumFractionDigits:2}):s.value}${s.unit?' '+s.unit:''}`:labels[s.quality]||s.quality;}
function batteryValue(s){if(!s)return 'Nog geen meting';if(s.quality==='not_configured')return 'Niet van toepassing';if(s.quality!=='available')return value(s);return {normal:'Normaal',low:'Batterij bijna leeg'}[s.battery_status]||'Onbekend';}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function chart(id,records,key,colors){const c=$(id),w=c.clientWidth,h=Number(c.dataset.height||c.getAttribute('height')),dpr=window.devicePixelRatio||1;c.dataset.height=h;c.width=w*dpr;c.height=h*dpr;c.style.height=h+'px';const x=c.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,w,h);x.font='12px system-ui';x.fillStyle='#756d7e';const all=records.flat().filter(r=>r.value!==null);if(!all.length){x.fillText('Nog geen bruikbare meetgegevens.',20,40);return;}const t0=Math.min(...all.map(r=>r.start)),t1=Math.max(...all.map(r=>r.end??r.start))+1;let lo=Math.min(...all.map(r=>r.value)),hi=Math.max(...all.map(r=>r.value));if(key==='prices'){lo=Math.min(0,lo);hi=Math.max(0,hi);}if(hi===lo){lo-=1;hi+=1;}const X=t=>48+(t-t0)/(t1-t0)*(w-65),Y=v=>h-36-(v-lo)/(hi-lo)*(h-60);for(let i=0;i<=4;i++){let v=lo+(hi-lo)*i/4;x.fillStyle='#756d7e';x.fillText(v.toFixed(key==='prices'?2:1),2,Y(v)+4);x.strokeStyle='#ede8f2';x.beginPath();x.moveTo(45,Y(v));x.lineTo(w-10,Y(v));x.stroke();}records.forEach((series,j)=>{x.strokeStyle=colors[j];x.fillStyle=colors[j];x.lineWidth=2;let prev=null;for(const r of series){if(r.value===null){prev=null;continue;}if(key==='prices'){x.fillRect(X(r.start),Math.min(Y(r.value),Y(0)),Math.max(1,X(r.end)-X(r.start)-1),Math.max(1,Math.abs(Y(r.value)-Y(0))));}else{if(prev&&r.start-prev.start<300){x.beginPath();x.moveTo(X(prev.start),Y(prev.value));x.lineTo(X(r.start),Y(r.value));x.stroke();}x.beginPath();x.arc(X(r.start),Y(r.value),2,0,2*Math.PI);x.fill();prev=r;}}});x.fillStyle='#756d7e';x.fillText(fmt(t0),48,h-8);const last=fmt(t1);x.fillText(last,Math.max(48,w-130),h-8);}
let current=null,hist=[],settingsRevision=0;
function graphs(){if(current)chart('prices',[current.prices],'prices',['#8053ac']);const ids=['beneden','boven','badkamer','garage'];chart('history',ids.map(id=>hist.map(r=>({start:r.time,value:(r.zones.find(z=>z.id===id)?.samples.temperature||{}).value??null}))),'temperature',['#8053ac','#367cad','#c67c32','#42916a']);for(const id of ids)drawZoneClimate($('climate-'+id),hist,id);}
const zoneCards = new Map();
function temperatureForm(zone) {
  const form = el('form', undefined, 'temperature-settings');
  const title = el('h3', zone.id==='beneden'?'Basis buiten tijdvensters':'Vaste temperatuur instellen');
  const fields = el('div', undefined, 'temperature-fields');
  const inputs = {};
  for (const [key, label] of [['minimum', 'Minimum'], ['target', 'Gewenst'], ['maximum', 'Maximum']]) {
    const wrapper = el('label', label + ' (°C)');
    const input = el('input');
    input.type = 'number'; input.step = 'any'; input.inputMode = 'decimal';
    input.name = key; input.placeholder = 'Niet ingesteld';
    inputs[key] = input; wrapper.append(input); fields.append(wrapper);
  }
  const button = el('button', 'Opslaan'); button.type = 'submit';
  const status = el('p', '', 'save-status'); status.setAttribute('role', 'status');
  form.append(title, fields, button, status);
  form.dirty = false; form.saving = false;
  form.sync = settings => {
    if (!form.dirty && !form.saving) {
      for (const [key, input] of Object.entries(inputs)) input.value = settings[key] ?? '';
    }
  };
  form.sync(zone.settings);
  form.addEventListener('input', () => { form.dirty = true; status.textContent = 'Nog niet opgeslagen'; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const values = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value === '' ? null : Number(input.value)]));
    const ordered = ['minimum', 'target', 'maximum'].map(key => values[key]).filter(v => v !== null);
    if (ordered.some((v, i) => !Number.isFinite(v) || (i > 0 && v < ordered[i - 1]))) {
      status.textContent = 'Houd minimum ≤ gewenst ≤ maximum aan.'; return;
    }
    form.saving = true; button.disabled = true;
    Object.values(inputs).forEach(input => input.disabled = true);
    status.textContent = 'Opslaan…';
    try {
      const response = await fetch('api/settings', {
        method: 'POST', headers: {'Content-Type': 'application/json', 'X-HC-CSRF': current.csrf_token},
        body: JSON.stringify({zone_id: zone.id, values})
      });
      if (!response.ok) {
        if (response.status === 403) throw Error('Sessie vernieuwd. Wacht even en probeer opnieuw.');
        const failure = await response.json(); throw Error(failure.error || 'Opslaan mislukt.');
      }
      const result = await response.json();
      settingsRevision = Math.max(settingsRevision, result.settings_revision);
      zone.settings = result.settings;
      form.dirty = false;
      status.textContent = 'Opgeslagen. Een actieve regeling gebruikt dit doel bij de volgende controle.';
    } catch (error) { status.textContent = error.message || 'Opslaan mislukt. Probeer opnieuw.'; }
    finally {
      form.saving = false; button.disabled = false;
      Object.values(inputs).forEach(input => input.disabled = false);
    }
  });
  return form;
}
function doorValue(s) {
  if(!s) return 'Nog geen meting';
  if(s.quality!=='available') return value(s);
  return {on:'Open',off:'Dicht'}[s.value] || 'Onbekend';
}
function renderBuilding(data) {
  const recording=data.building?.version===1;
  $('building-status').textContent=recording
    ? 'Laatste woningmeting: '+fmt(data.collected)+'. '+(data.stale||data.connection!=='connected'?'Registratie wacht op actuele HA-gegevens.':'Registratie loopt.')
    : 'Wacht op de eerste woningmeting met bron- en deurcontext.';
  $('building-retention').textContent='Bewaartermijn: '+data.retention_days+' dagen. Download de meetreeks om deze langer te bewaren.';
}
function renderZones(zones, building) {
  for (const z of zones) {
    let parts = zoneCards.get(z.id);
    if (!parts) {
      const card = el('article', undefined, 'zone');
      const title = el('h2'), reading = el('div', undefined, 'reading');
      const humidity = el('div', undefined, 'sub'), facts = el('dl');
      const reason = el('p', undefined, 'reason'), form = z.settings.monitor_only ? el('p', 'Verwarmd via cv · alleen monitoring') : z.id==='beneden' ? el('p', 'Instellen via Comfortschema / thermostaat beneden.') : temperatureForm(z);
      card.append(title, reading, humidity, facts, form, reason);
      $('zones').append(card);
      parts = {title, reading, humidity, facts, reason, form}; zoneCards.set(z.id, parts);
    }
    parts.title.textContent = z.name;
    parts.reading.textContent = value(z.samples.temperature);
    parts.humidity.textContent = 'Luchtvochtigheid: ' + value(z.samples.humidity);
    parts.facts.replaceChildren();
    for (const [key, val] of [['Dauwpunt', z.samples.dewpoint?value(z.samples.dewpoint):'Nog geen meting'], ['Sensorbatterij', batteryValue(z.samples.battery)], ['Apparaat', value(z.samples.device)], ['Vermogen', value(z.samples.power)], ['Energie', value(z.samples.energy)], ['Vochtband', z.settings.humidity_min + '–' + z.settings.humidity_max + '%']]) {
      parts.facts.append(el('dt', key), el('dd', val, key==='Sensorbatterij'&&z.samples.battery?.battery_status==='low'?'battery-low':undefined));
    }
    const delta=building?.zones.find(zone=>zone.id===z.id)?.delta_t_k;
    parts.facts.append(el('dt','Binnen − buiten'),el('dd',typeof delta==='number'?delta.toLocaleString('nl-NL',{maximumFractionDigits:1})+' °C':'Nog geen bruikbaar meetpaar'));
    if(z.id==='beneden') parts.facts.append(el('dt','Achterdeur'),el('dd',doorValue(building?.back_door)));
    parts.reason.textContent = z.reason;
    parts.form.sync?.(z.settings);
  }
}
const weatherNames = {
  cloudy: ['☁', 'Bewolkt'], sunny: ['☀', 'Zonnig'], partlycloudy: ['⛅', 'Halfbewolkt'],
  rainy: ['🌧', 'Regen'], pouring: ['🌧', 'Zware regen'], snowy: ['❄', 'Sneeuw'],
  'snowy-rainy': ['🌨', 'Natte sneeuw'], fog: ['🌫', 'Mist'], hail: ['🌨', 'Hagel'],
  lightning: ['ϟ', 'Onweer'], 'lightning-rainy': ['⛈', 'Onweer met regen'],
  windy: ['≋', 'Wind'], 'windy-variant': ['≋', 'Bewolkt en winderig'],
  'clear-night': ['☾', 'Heldere nacht'], exceptional: ['!', 'Uitzonderlijk weer']
};
function weatherLabel(condition) { return weatherNames[condition] || ['—', condition || 'Onbekend']; }
function forecastNumber(number, unit) {
  return typeof number === 'number' && unit ? number.toLocaleString('nl-NL', {maximumFractionDigits:1}) + ' ' + unit : 'Niet beschikbaar';
}
function renderWeather(weather, stale, outdoor, humidity, dewpoint, battery, vpd) {
  const measured=$('weather-measured');measured.replaceChildren();
  measured.append(el('div',outdoor?value(outdoor):'Nog geen meting','weather-temperature'),
    el('div','Luchtvochtigheid: '+(humidity?value(humidity):'Nog geen meting'),'sub'),
    el('div','VPD: '+(vpd?value(vpd):'Nog geen meting'),'sub'),
    el('div','Dauwpunt: '+(dewpoint?value(dewpoint):'Nog geen meting'),'sub'),
    el('div','Sensorbatterij: '+batteryValue(battery),battery?.battery_status==='low'?'sub battery-low':'sub'));
  const times=[['Temperatuur',outdoor],['Luchtvochtigheid',humidity],['Dauwpunt',dewpoint],['VPD',vpd],['Sensorbatterij',battery]].map(([name,s])=>
    name+': '+(s?.source_updated?'bron bijgewerkt '+fmt(Date.parse(s.source_updated)/1000):'geen brontijd'));
  $('weather-measured-status').textContent=(stale?'Metingen niet actueel. ':'')+times.join(' · ');

  const box = $('weather-current'); box.replaceChildren();
  const forecast = $('weather-forecast'); forecast.replaceChildren();
  if (!weather) { $('weather-status').textContent = 'Nog geen weergegevens ontvangen.'; return; }
  const condition = weather.condition;
  const [symbol, name] = weatherLabel(condition.quality === 'available' ? condition.value : null);
  const heading = el('div', undefined, 'weather-heading');
  const icon = el('span', symbol, 'weather-icon'); icon.setAttribute('aria-hidden', 'true');
  heading.append(icon, el('strong', condition.quality === 'available' ? name : value(condition)),
    el('span', value(weather.metrics.temperature), 'weather-temperature'));
  box.append(heading);
  const facts = el('div', undefined, 'weather-facts');
  for (const [key, label] of [['apparent_temperature', 'Gevoel'], ['humidity', 'Luchtvochtigheid'], ['wind_speed', 'Wind'], ['wind_gust_speed', 'Windstoten'], ['pressure', 'Luchtdruk']]) {
    if (weather.metrics[key]) facts.append(el('span', label + ': ' + value(weather.metrics[key])));
  }
  box.append(facts);
  $('weather-status').textContent = (stale ? 'Weergegevens niet actueel. ' : '') +
    (condition.source_updated ? 'Bron bijgewerkt: ' + fmt(Date.parse(condition.source_updated)/1000) : 'Nog geen brontijd ontvangen.');
  const f = weather.forecast;
  if (f) for (const row of f.rows) {
    const day = el('article', undefined, 'forecast-day');
    const date = new Intl.DateTimeFormat('nl-NL', {timeZone:'Europe/Amsterdam', weekday:'short', day:'numeric', month:'short'}).format(new Date(row.time*1000));
    const [glyph, description] = weatherLabel(row.condition);
    day.append(el('strong', date), el('div', glyph + ' ' + description),
      el('div', 'Max ' + forecastNumber(row.temperature, f.temperature_unit)),
      el('div', 'Min ' + forecastNumber(row.templow, f.temperature_unit)),
      el('div', 'Wind ' + forecastNumber(row.wind_speed, f.wind_speed_unit)));
    if(row.precipitation_probability !== null) day.append(el('div', 'Neerslagkans ' + forecastNumber(row.precipitation_probability, '%')));
    forecast.append(day);
  }
  $('forecast-status').textContent = !f || !f.rows.length ? (f?.error || 'Nog geen dagverwachting beschikbaar.') :
    (f.stale ? 'Verouderde verwachting. ' : '') + (f.error ? f.error + ' ' : '') +
    (f.received ? 'Ontvangen: ' + fmt(f.received) : '');
  const hourly=weather.hourly;
  $('forecast-status').textContent+=' '+({ready:'Uurverwachting beschikbaar voor verwarmingsplannen.',unsupported:'Deze weerbron biedt geen uurverwachting; leren gebruikt waargenomen weer.',unavailable:'Uurverwachting onvolledig of niet beschikbaar; nieuwe weerafhankelijke plannen wachten.',stale:'Uurverwachting verouderd; nieuwe weerafhankelijke plannen wachten.'}[hourly?.status]||'Uurverwachting nog niet gecontroleerd.');
}
const controlCards = new Map();
const modeNames = {off:'Uit',heat:'Verwarmen',cool:'Koelen',heat_cool:'Verwarmen/koelen',auto:'Automatisch (apparaat)',dry:'Ontvochtigen',fan_only:'Ventilator'};
const commandNames = {sending:'Verzending gestart',awaiting_feedback:'Wachten op terugmelding',confirmed:'Instelling bevestigd',already_set:'Instelling stond al zo',uncertain:'Verzendresultaat onbekend',failed:'Opdracht afgewezen',timed_out:'Niet bevestigd binnen wachttijd',interrupted:'Bewaking onderbroken door herstart',superseded:'Vervangen door uit-opdracht'};
function commandText(c) {
  return (commandNames[c.status] || c.status) + ' · ' + (['temperature','heating'].includes(c.field)?c.value+' °C':modeNames[c.value]||c.value) + (c.error?' · '+c.error:'');
}
function renderControls(sources, commands) {
  for (const source of sources || []) {
    let card = controlCards.get(source.id);
    if (!card) {
      const root=el('article',undefined,'source-control'), title=el('h3',source.name);
      const reported=el('p'), reason=el('p',undefined,'sub'), status=el('p','', 'command-status');status.setAttribute('role','status');
      const select=el('select');select.setAttribute('aria-label',source.name+' apparaatmodus');
      const modeButton=el('button','Modus toepassen');modeButton.type='button';
      const target=el('input');target.type='number';target.placeholder='Apparaatdoel';target.setAttribute('aria-label',source.name+' apparaattemperatuur');
      const targetButton=el('button','Temperatuur toepassen');targetButton.type='button';
      const off=el('button','Uit','off-button');off.type='button';
      const row=el('div',undefined,'control-row');row.append(select,modeButton);
      const targetRow=el('div',undefined,'control-row');targetRow.append(target,targetButton);
      root.append(title,reported,row,targetRow,off,reason,status);$('source-controls').append(root);
      card={root,reported,reason,status,select,modeButton,target,targetButton,off,row,targetRow,source,busy:false,dirty:false,retry:null};
      const send=async(field,value)=>{
        if(card.busy)return;
        card.busy=true;card.lastRequest=null;
        try {
          renderControls(current.sources,current.commands);status.textContent='Opdracht versturen…';
          const signature=JSON.stringify({field,value});
          // getRandomValues also works on local HTTP; randomUUID requires HTTPS.
          if(!card.retry||card.retry.signature!==signature){
            const bytes=crypto.getRandomValues(new Uint8Array(16));
            card.retry={signature,id:Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('')};
          }
          card.lastRequest=card.retry.id;
          const response=await fetch('api/commands',{method:'POST',headers:{'Content-Type':'application/json','X-HC-CSRF':current.csrf_token},body:JSON.stringify({request_id:card.retry.id,source:source.id,field,value})});
          if(!response.ok){
            if(response.status===403)throw Error('Sessie verlopen. Vernieuw het dashboard.');
            const failure=await response.json();throw Error(failure.error||'Opdracht niet verstuurd.');
          }
          const result=await response.json();
          status.textContent=commandText(result.command);card.retry=null;card.dirty=false;
          current.commands=[result.command,...(current.commands||[]).filter(c=>c.id!==result.command.id)].slice(0,20);
        } catch(error){status.textContent=error.message||'Geen antwoord. Controleer de opdrachtstatus vóór opnieuw proberen.';}
        finally{card.busy=false;renderControls(current.sources,current.commands);}
      };
      select.addEventListener('change',()=>{card.retry=null;});
      target.addEventListener('input',()=>{card.dirty=true;card.retry=null;});
      modeButton.addEventListener('click',()=>send(card.source.kind==='switch'?'state':'mode',select.value));
      off.addEventListener('click',()=>send(card.source.kind==='switch'?'state':'mode','off'));
      targetButton.addEventListener('click',()=>{
        if(target.value===''||!target.reportValidity()){status.textContent='Vul een geldige apparaattemperatuur in.';return;}
        send('temperature',Number(target.value));
      });
      controlCards.set(source.id,card);
    }
    card.source=source;
    const latest=(commands||[]).find(c=>c.id===card.lastRequest);
    if(latest&&!card.busy)card.status.textContent=commandText(latest);
    const modes=source.kind==='switch'?['off','on']:source.modes;
    const wanted=JSON.stringify(modes);
    if(card.select.dataset.modes!==wanted){
      const selected=card.select.value;card.select.replaceChildren();
      for(const mode of modes){const option=el('option',modeNames[mode]||(mode==='on'?'Aan':mode));option.value=mode;card.select.append(option);}
      card.select.value=modes.includes(selected)?selected:modes.includes(source.state)?source.state:modes[0]||'';
      card.select.dataset.modes=wanted;
    }
    const pending=(commands||[]).some(c=>c.entity_id===source.entity_id&&['sending','awaiting_feedback','uncertain'].includes(c.status));
    card.reported.textContent='Gemeld: '+(modeNames[source.state]||source.state||'Onbekend')+(source.temperature!=null?' · doel '+source.temperature+(source.unit?' '+source.unit:''):'')+(source.action?' · activiteit '+source.action:'');
    card.modeButton.disabled=card.busy||!source.available||pending||!modes.length;
    card.select.disabled=card.busy||!source.available;
    card.off.disabled=card.busy||!source.available||!modes.includes('off');
    card.targetRow.hidden=source.kind!=='climate';
    card.target.disabled=card.busy||!source.available||!source.temperature_supported;
    card.targetButton.disabled=card.target.disabled||pending;
    if(source.minimum!=null)card.target.min=source.minimum;
    if(source.maximum!=null)card.target.max=source.maximum;
    card.target.step=source.step||'any';
    if(!card.dirty&&!pending&&document.activeElement!==card.target)card.target.value=source.temperature??'';
    card.reason.textContent=source.reason||(pending?'Wachten op terugmelding; Uit blijft beschikbaar.':source.kind==='climate'&&!source.temperature_supported?'Temperatuurbediening wacht op HA-grenzen, stapgrootte en °C-eenheid.':'Handmatige bronbediening.');
  }
  const history=$('command-history');history.replaceChildren();
  if(!commands?.length)history.append(el('p','Nog geen opdrachten vanuit HC.'));
  for(const c of commands||[]){const name=(sources||[]).find(s=>s.id===c.source)?.name||c.source;history.append(el('p',fmt(c.created)+' · '+name+' · '+(c.origin==='schedule'?'Automatisch · ':'Handmatig · ')+commandText(c)));}
}
const weekdays=['Maandag','Dinsdag','Woensdag','Donderdag','Vrijdag','Zaterdag','Zondag'];
let scheduleForm=null;
function renderSchedule(data){
  if(!data)return;
  renderHeating(current.heating);
  let energy=$('energy-outlook-status');
  if(!energy){energy=el('p',undefined,'sub');energy.id='energy-outlook-status';$('planner-status').after(energy);}
  let assessment=$('energy-assessment-status');
  if(!assessment){assessment=el('p',undefined,'sub');assessment.id='energy-assessment-status';energy.after(assessment);}
  const reviewed=current.energy_assessment;
  assessment.textContent=reviewed?.status==='selected' ? 'HEMS adviseert voorstel '+reviewed.selected_plan_id+'. Nog geen uitvoeringsopdracht.' : (reviewed?.reason||'Nog geen HC-energievoorstellen ter beoordeling.');
  let assessmentDetails=$('energy-assessment-details');
  if(!assessmentDetails){assessmentDetails=el('div');assessmentDetails.id='energy-assessment-details';assessment.after(assessmentDetails);}
  assessmentDetails.replaceChildren();
  for(const row of reviewed?.assessments||[]){
    let detail=row.plan_id+': ';
    if(row.status==='feasible')detail+='geschatte extra totaalkosten '+row.total_incremental_cost_eur.toLocaleString('nl-NL',{style:'currency',currency:'EUR'})+'.';
    else if(row.constraint?.kind==='verified_scaled_profile')detail+='past niet binnen de behouden route. Geteste kleinere variant: '+(row.constraint.verified_profile_energy_wh/1000).toFixed(2)+' kWh op dezelfde tijden. HC moet het comfort opnieuw toetsen.';
    else if(row.constraint?.kind==='end_before')detail+='moet uiterlijk eindigen op '+fmt(Date.parse(row.constraint.ends_at)/1000)+'.';
    else detail+='nog niet haalbaar binnen de behouden route.';
    assessmentDetails.append(el('p',detail,'sub'));
  }
  const outlook=current.energy_outlook;
  let loadHistory=$('energy-load-history');
  if(!loadHistory){loadHistory=el('p',undefined,'sub');loadHistory.id='energy-load-history';energy.after(loadHistory);}
  loadHistory.textContent=outlook?.replacement_basis ? 'HEMS kan voorstellen voor airco beneden zonder dubbeltelling beoordelen vanaf '+fmt(outlook.replacement_basis.starts_at)+'.' : outlook?.load_history_status==='history_ready' ? 'Afzonderlijke verbruiksraming beschikbaar; nog onvoldoende aansluiting op de actieve huisprognose om verwarmingsvoorstellen zonder dubbeltelling te beoordelen.' : outlook?.load_history_status==='collecting' ? 'HEMS verzamelt gelijktijdige metingen van huisverbruik en airco beneden. Ontbrekende metingen tellen niet als nulverbruik.' : 'Nog geen actuele bevestiging van HEMS over de afzonderlijke verbruikshistorie.';
  let proposals=$('energy-proposals-status');
  if(!proposals){proposals=el('p',undefined,'sub');proposals.id='energy-proposals-status';loadHistory.after(proposals);}
  const offered=current.energy_proposals;
  let selection=$('energy-selection-status');
  if(!selection){selection=el('p',undefined,'sub');selection.id='energy-selection-status';proposals.after(selection);}
  const selected=current.energy_selection;
  let intentStatus=$('start-intent-status');
  if(!intentStatus){intentStatus=el('p',undefined,'sub');intentStatus.id='start-intent-status';selection.after(intentStatus);}
  const intent=current.start_intent;
  intentStatus.textContent=intent?.heat_starts_at ? 'Startvoornemen beneden ('+(intent.source==='cv'?'CV':'airco')+'): '+fmt(intent.heat_starts_at)+'. '+(intent.reason||'') : 'Nog geen vast startvoornemen voor beneden.';
  selection.textContent=selected?.status==='confirmed' ? 'HEMS-keuze gecontroleerd: '+(selected.source==='cv'?'CV, ':'airco, ')+selected.target+' °C'+(selected.heat_starts_at?' vanaf '+fmt(selected.heat_starts_at):'')+'. Keuze wordt teruggemeld. Een geplande start vereist afzonderlijke actuele HEMS-starttoestemming.' : 'Nog geen actuele, lokaal bevestigde HEMS-keuze.';
  let warmup=$('warmup-energy-status');
  if(!warmup){warmup=el('p',undefined,'sub');warmup.id='warmup-energy-status';proposals.after(warmup);}
  const warming=current.warmup_energy;
  let startup=$('startup-energy-status');
  if(!startup){startup=el('p',undefined,'sub');startup.id='startup-energy-status';warmup.after(startup);}
  const starting=current.startup_energy;
  let cvLearning=$('cv-warmup-status');
  if(!cvLearning){cvLearning=el('p',undefined,'sub');cvLearning.id='cv-warmup-status';startup.after(cvLearning);}
  const cvEvidence=current.cv_warmup;
  let cvEstimate=$('cv-energy-estimate');
  if(!cvEstimate){cvEstimate=el('p',undefined,'sub');cvEstimate.id='cv-energy-estimate';cvLearning.after(cvEstimate);}
  const cvEnergy=cvEvidence?.energy_estimate;
  let cvHolding=$('cv-holding-estimate');
  if(!cvHolding){cvHolding=el('p',undefined,'sub');cvHolding.id='cv-holding-estimate';cvEstimate.after(cvHolding);}
  const cvHold=current.cv_maintenance;
  cvHolding.textContent=cvHold?.status==='estimated' ? 'CV handhaven: geraamd '+cvHold.gas_m3_per_hour.toFixed(3)+' m³/uur en '+cvHold.power_w.toFixed(0)+' W hulpverbruik.' : 'CV handhaven leren: '+(cvHold?.samples??0)+' van minimaal 3 passende, gecontroleerde meetperioden.';
  cvEstimate.textContent=cvEnergy?.status==='estimated'
    ? 'CV-opwarmraming: '+cvEnergy.gas_m3.toFixed(3)+' m³ gas, '+Math.ceil(cvEnergy.duration_seconds/60)+' minuten en '+cvEnergy.electricity.energy_wh.toFixed(1)+' Wh geschat hulpverbruik. Inclusief 25% marge; naloop apart '+cvEnergy.electricity.postrun_energy_wh.toFixed(1)+' Wh.'+(Number.isFinite(cvEnergy.gas_cost_eur)?' Gaskosten € '+cvEnergy.gas_cost_eur.toFixed(2)+'.':' Gastarief ontbreekt.')+' CV-start vereist een passend handhaafprofiel en HEMS-toestemming.'
    : 'CV-opwarmraming: '+(cvEnergy?.samples??0)+' van minimaal 3 passende, gecontroleerde opwarmbeurten.';
  cvLearning.textContent='CV-opwarmmetingen: '+(cvEvidence?.completed_sessions??0)+' afgerond.'+(cvEvidence?.measuring?' Meting loopt.':'')+(cvEvidence?.pending_gas_reviews?' Warmwatercontrole wacht op vertraagde meldingen.':'')+' Warmwatercontrole: '+({dhw_observed:'warmwatergebruik waargenomen; gasmeting vermengd',no_dhw_observed:'niet waargenomen; gas nog niet afgebakend',incomplete:'onbekend of onvolledig'}[cvEvidence?.latest?.gas_screening?.status]??'onbekend')+'. Alleen de temperatuur beneden bepaalt het opwarmresultaat. De gasmeting kan ander gasverbruik bevatten; elektrisch CV-verbruik: '+(cvEvidence?.latest?.electricity_measured?'gemeten met aparte CV-meter':cvEvidence?.latest?.electricity?.status==='estimated'?'geschat '+cvEvidence.latest.electricity.energy_wh.toFixed(1)+' Wh, plus '+cvEvidence.latest.electricity.postrun_energy_wh.toFixed(1)+' Wh verwachte naloop na stoppen':'onbekend of onvolledig')+'. Passende metingen worden gebruikt voor CV-alternatieven aan HEMS.';

  startup.textContent=starting?.status==='ready' ? 'Volledige start geraamd: '+(starting.energy_wh/1000).toFixed(2)+' kWh en '+Math.ceil(starting.duration_seconds/60)+' minuten, inclusief gemeten wachttijd tot bevestiging. Startvoorstellen gebruiken deze raming; uitstel van de gewone voorverwarmstart vereist actuele HEMS-toestemming en voldoende tijdmarge.' : 'Volledige starts leren: '+(starting?.completed_sessions??0)+' afgerond, '+(starting?.samples??0)+' passend.'+(starting?.awaiting_confirmation?' Startmeting loopt; verwarmingsopdracht nog niet bevestigd.':starting?.measuring?' Startmeting loopt tot de doeltemperatuur bereikt is.':'');
  warmup.textContent=warming?.status==='ready' ? 'Opwarmraming: '+(warming.energy_wh/1000).toFixed(2)+' kWh en '+Math.ceil(warming.duration_seconds/60)+' minuten op basis van '+warming.samples+' vergelijkbare metingen. Inclusief schattingsmarge; gebruikt voor passende energievoorstellen.' : 'Opwarmenergie leren: '+(warming?.completed_sessions??0)+' afgeronde metingen, '+(warming?.samples??0)+' passend bij de huidige omstandigheden. Minimaal drie passende metingen nodig.'+(warming?.measuring?' Opwarmmeting loopt.':'');
  proposals.textContent=offered?.status==='proposed' ? 'HC-voorstel: '+offered.target+' °C handhaven van '+fmt(offered.starts_at)+' tot '+fmt(offered.ends_at)+', geraamd '+(offered.energy_wh/1000).toFixed(2)+' kWh. Ter beoordeling; de regeling wordt hierdoor niet gewijzigd.' : (offered?.reason||'Nog geen automatisch energievoorstel.')+(offered?.samples?' Passende meetperioden: '+offered.samples+'.':'');
  energy.textContent=outlook?.status==='ready' ? 'HEMS: kleinste verwachte batterijmarge boven het technische minimum tot '+fmt(outlook.horizon_end)+': '+(outlook.projected_minimum_margin_wh/1000).toFixed(2)+' kWh. Dit is geen vrij te besteden budget; tijdvakken zijn niet optelbaar. Een gekozen verwarmingsplan vereist afzonderlijke HEMS-toestemming.' : 'HEMS: '+(outlook?.reason||'Nog geen energierichtlijn beschikbaar.');
  $('schedule-status').textContent=data.reason+(data.migration?' '+data.migration:'');
  if(offered?.status==='proposed'&&offered.kind==='delayed_start')proposals.textContent=offered.alternatives+' starttijdvoorstel(len) aan HEMS aangeboden: '+offered.heat_starts_at.map((t,i)=>(offered.sources?.[i]==='cv'?'CV ':'airco ')+fmt(t)).join(' / ')+', doel '+offered.targets[0]+' °C. Inclusief wachten, opwarmen en handhaven. Starten vereist actuele HEMS-starttoestemming.';
  if(offered?.status==='proposed'&&offered.kind==='warmup')proposals.textContent=offered.alternatives+' opwarmvoorstel(len) aan HEMS aangeboden voor '+offered.targets.join(' / ')+' °C. Beoordelingsperiode '+fmt(offered.starts_at)+' tot '+fmt(offered.ends_at)+'. De regeling wordt hierdoor niet gewijzigd.';
  const active=data.current;
  $('schedule-next').textContent=(active?'Nu: '+active.target+' °C · '+(active.hard?'comforttemperatuur':'band '+active.minimum+'–'+active.maximum+' °C')+'. ':'')+(data.next?'Volgend venster: '+fmt(data.next.starts_at)+' · '+data.next.target+' °C'+(data.next.hard?' moet bij aanvang bereikt zijn.':'.'):'Geen volgend venster ingesteld.');
  const learned=current.heating?.learning_status;
  $('planner-status').textContent=learned?.enabled ? 'Lerend voorverwarmen: '+learned.lead_minutes+' minuten voorlooptijd; '+learned.outcomes.length+' beoordeelde opwarmbeurten. '+(current.heating.preheating?'Voorverwarmen gepland; bronbeveiligingen blijven gelden. ':'')+'Afkoelmetingen: '+(learned.cooling_samples??0)+'. '+({coast:'Eerder afbouwen binnen de comfortmarge.',setback:'Voorzichtige verlaging buiten comfort: '+learned.target+' °C.',unsupported_target:'Geleerd doel niet ondersteund; schemadoel blijft gelden.'}[learned.phase]||'')+' '+(learned.weather?'Weer meegenomen: '+learned.weather.wind_m_s.toFixed(1)+' m/s, '+({clear:'helder',mixed:'gedeeltelijk bewolkt',overcast:'bewolkt'}[learned.weather.sky]||learned.weather.sky)+', '+(learned.weather.daylight?'overdag':'nacht')+'; '+learned.weather_samples+' passende opwarmbeurten.':'Geen volledige verse weerwaarneming; alleen metingen zonder weerlabel vergelijkbaar.')+' Tijdig comfort is nog geen garantie.' : 'Lerend voorverwarmen staat uit. De regeling volgt het huidige temperatuurdoel.';
  const holds=$('forced-sources');holds.replaceChildren();
  if(data.legacy_pause)holds.append(el('p','Eerdere handmatige pauze bewaard: '+data.legacy_pause.reason));
  for(const hold of data.overrides){
    const name=current.sources?.find(s=>s.id===hold.source)?.name||hold.source;
    holds.append(el('p',name+' · '+(hold.forced_source?(hold.active?'Gedwongen bron: ':'Bronverzoek: ')+hold.temperature+' °C':'Handmatige stand: '+(modeNames[hold.value]||hold.value))+' · '+(commandNames[hold.status]||({'observed':'Waargenomen in HA','unrecorded':'Opdracht niet geregistreerd'}[hold.status])||hold.status)+(hold.until?' · tot '+fmt(hold.until):' · tot HC hervatten')));
  }
  for(const zone of Object.values(data.comfort.zones))for(const error of zone.errors)holds.append(el('p',error));
  if(!scheduleForm){
    const form=el('form',undefined,'schedule-form'), fields=el('fieldset');
    const enabled=el('input');enabled.type='checkbox';enabled.name='enabled';
    const enabledLabel=el('label','Tijdvensters gebruiken');enabledLabel.prepend(enabled);
    const age=el('input');age.type='number';age.min=30;age.max=86400;age.step=1;age.required=true;age.name='sensor_max_age_seconds';
    const ageLabel=el('label','Maximale meetleeftijd beneden (seconden)');ageLabel.append(age);
    const band=el('input');band.type='number';band.name='optimization_band';band.min=0;band.max=5;band.step='any';band.required=true;
    const bandLabel=el('label','Optimalisatieband (± °C)');bandLabel.append(band);
    const setback=el('input');setback.type='number';setback.min=5;setback.max=35;setback.step='any';setback.name='setback_temperature';
    const setbackLabel=el('label','Minimum buiten comfortvensters (°C)');setbackLabel.append(setback);
    const thermostat=el('input');thermostat.type='number';thermostat.min=5;thermostat.max=35;thermostat.step='any';thermostat.name='thermostat_temperature';
    const thermostatLabel=el('label','Handmatige thermostaat (°C) — bij uitgeschakeld schema');thermostatLabel.append(thermostat);
    const modeFields=()=>{thermostat.disabled=enabled.checked;setback.disabled=!enabled.checked;setback.required=enabled.checked;};
    enabled.addEventListener('change',modeFields);
    const learning=el('input');learning.type='checkbox';learning.name='learning_enabled';
    const learningLabel=el('label','Opwarmtijd beneden automatisch bijleren');learningLabel.prepend(learning);
    const coolingFlags={};
    const learningFields={};
    const learningPanel=el('div');learningPanel.append(learningLabel);
    for(const [key,label,defaultValue] of [['initial_preheat_minutes','Eerste opwarmtijd (minuten)',45],['max_preheat_minutes','Maximale opwarmtijd (minuten)',180],['max_coast_minutes','Maximaal eerder afbouwen (minuten)',60]]){
      const input=el('input');Object.assign(input,{type:'number',name:key,min:key==='max_coast_minutes'?0:15,max:key==='max_coast_minutes'?60:180,step:1,required:true,value:defaultValue});
      const wrapper=el('label',label);wrapper.append(input);learningPanel.append(wrapper);learningFields[key]=input;
    }
    for(const [key,label] of [['adaptive_setback_enabled','Temperatuurverlaging voorzichtig bijleren'],['coast_enabled','Eerder afbouwen binnen comfortmarge'],['energy_start_enabled','Gekozen start beneden automatisch uitvoeren (proef)']]){
      const input=el('input');input.type='checkbox';input.name=key;const wrapper=el('label',label);wrapper.prepend(input);learningPanel.append(wrapper);coolingFlags[key]=input;
    }
    learningPanel.append(el('p','Een gekozen start wordt alleen met recente HEMS-starttoestemming uitgevoerd. De gewone voorverwarmstart mag alleen worden uitgesteld met actuele HEMS-toestemming en voldoende gemeten opwarmtijd. Bij twijfel krijgt comfort voorrang. HEMS neemt het gekozen profiel vooraf mee zolang HC het bevestigt. Dit garandeert geen batterijdekking voor de volledige verwarmingsperiode.','sub'));
    learningPanel.append(el('p','Begint maximaal 1 °C onder het volgende comfortdoel. Na drie geslaagde opwarmbeurten en voldoende afkoelmetingen mag dit 0,5 °C verder dalen, nooit onder je minimum. Eerder afbouwen verlaagt het doel maximaal 0,5 °C en schakelt de bron niet uit. Wind en zon zijn nog niet gemodelleerd.','sub'));
    learningPanel.append(el('p','Alleen met actief comfortschema en automatische verwarming. Te laat: 15 minuten eerder; ruim op tijd: 5 minuten later. Veranderen van comfortinstellingen start een nieuwe leerreeks.','sub'));
    const rows=el('div',undefined,'schedule-rows');
    const add=el('button','Venster toevoegen');add.type='button';
    const door=el('details'), summary=el('summary','Meetleeftijd en deurvertraging');door.append(summary,ageLabel);
    const delays={};
    for(const [key,label] of [['door_open_seconds','Achterdeur open: blokkeer airco na (seconden)'],['door_close_seconds','Achterdeur dicht: airco weer beschikbaar na (seconden)']]){
      const wrapper=el('label',label), input=el('input');input.type='number';input.min=0;input.max=1800;input.step=1;input.required=true;input.name=key;wrapper.append(input);door.append(wrapper);delays[key]=input;
    }
    const save=el('button','Comfortschema opslaan');save.type='submit';
    const resume=el('button','HC hervatten');resume.type='button';
    const status=el('p','', 'schedule-save-status');status.setAttribute('role','status');
    fields.append(enabledLabel,thermostatLabel,setbackLabel,bandLabel,learningPanel,rows,add,door,save,resume);form.append(fields,status);$('schedule-editor').append(form);
    form.dirty=false;form.busy=false;form.revision=0;
    const mark=()=>{form.dirty=true;status.textContent='Nog niet opgeslagen';};
    form.addEventListener('input',mark);form.addEventListener('change',mark);
    const addRow=(entry={days:[0],start:'',end:'',target:'',hard:false})=>{
      const row=el('div',undefined,'schedule-row comfort-window');
      const wrap=(label,input)=>{const wrapper=el('label',label);wrapper.append(input);row.append(wrapper);};
      const days=el('div',undefined,'window-days');
      const choices=[];
      weekdays.forEach((name,index)=>{
        const input=el('input');input.type='checkbox';input.name='day';input.value=index;input.checked=entry.days.includes(index);
        const label=el('label',name.slice(0,2));label.prepend(input);days.append(label);choices.push(input);
      });
      const presets=el('div',undefined,'day-presets');
      for(const [label,selected] of [['Ma–vr',[0,1,2,3,4]],['Weekend',[5,6]],['Alle dagen',[0,1,2,3,4,5,6]]]){
        const button=el('button',label);button.type='button';button.addEventListener('click',()=>{choices.forEach((c,i)=>c.checked=selected.includes(i));mark();});presets.append(button);
      }
      days.append(presets);row.append(days);
      const start=el('input');start.type='time';start.required=true;start.name='start';start.value=entry.start;wrap('Vanaf',start);
      const end=el('input');end.type='text';end.required=true;end.name='end';end.value=entry.end;end.placeholder='24:00';end.pattern='([01][0-9]|2[0-3]):[0-5][0-9]|24:00';wrap('Tot',end);
      const target=el('input');target.type='number';target.min=5;target.max=35;target.step='any';target.required=true;target.name='target';target.value=entry.target;wrap('Temperatuur (°C)',target);
      const hard=el('input');hard.type='checkbox';hard.name='hard';hard.checked=entry.hard;wrap('Comforttemperatuur',hard);
      const copy=el('button','Dupliceren');copy.type='button';copy.addEventListener('click',()=>{
        if(rows.children.length>=112)return;
        addRow({days:choices.filter(c=>c.checked).map(c=>Number(c.value)),start:start.value,end:end.value,target:target.value,hard:hard.checked});mark();
      });row.append(copy);
      const remove=el('button','Verwijderen');remove.type='button';remove.addEventListener('click',()=>{row.remove();mark();});
      row.append(remove);rows.append(row);
    };
    add.addEventListener('click',()=>{if(rows.children.length<112){addRow();mark();}});
    const post=async(path,payload)=>{
      if(form.busy)return;
      form.busy=true;fields.disabled=true;status.textContent='Opslaan…';
      try{
        const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-HC-CSRF':current.csrf_token},body:JSON.stringify(payload)});
        if(response.status===403)throw Error('Sessie verlopen. Herlaad het dashboard.');
        const result=await response.json();if(!response.ok)throw Error(result.error||'Opslaan mislukt.');
        if(path==='api/schedule'){form.dirty=false;form.revision=result.schedule.revision;}
        current.schedule=result.schedule;status.textContent=path==='api/resume'?'Handmatige bronkeuzes vrijgegeven.':'Comfortschema opgeslagen.';
      }catch(error){status.textContent=error.message||'Geen antwoord; controleer de actuele status.';}
      finally{form.busy=false;fields.disabled=false;renderSchedule(current.schedule);}
    };
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const windows=[];
      for(const row of rows.children){
        const get=name=>row.querySelector('[name='+name+']');
        const days=[...row.querySelectorAll('[name=day]:checked')];
        if(!days.length){status.textContent='Selecteer voor ieder venster minstens één dag.';return;}
        for(const day of days)windows.push({day:Number(day.value),start:get('start').value,end:get('end').value,target:Number(get('target').value),hard:get('hard').checked});
      }
      post('api/schedule',{revision:form.revision,settings:{enabled:enabled.checked,learning_enabled:learning.checked,...Object.fromEntries(Object.entries(coolingFlags).map(([k,v])=>[k,v.checked])),...Object.fromEntries(Object.entries(learningFields).map(([k,v])=>[k,Number(v.value)])),setback_temperature:setback.value===''?null:Number(setback.value),thermostat_temperature:thermostat.value===''?null:Number(thermostat.value),optimization_band:Number(band.value),windows,sensor_max_age_seconds:Number(age.value),door_open_seconds:Number(delays.door_open_seconds.value),door_close_seconds:Number(delays.door_close_seconds.value)}});
    });
    resume.addEventListener('click',()=>post('api/resume',{}));
    form.sync=d=>{
      if(!form.dirty&&!form.busy&&d.revision>=form.revision){
        learning.checked=d.settings.learning_enabled;
        for(const [key,input] of Object.entries(coolingFlags))input.checked=d.settings[key];
        for(const [key,input] of Object.entries(learningFields))input.value=d.settings[key];
        enabled.checked=d.settings.enabled;band.value=d.settings.optimization_band;age.value=d.settings.sensor_max_age_seconds;rows.replaceChildren();
        setback.value=d.settings.setback_temperature??'';thermostat.value=d.settings.thermostat_temperature??'';modeFields();
        const groups=new Map();
        for(const w of d.settings.windows){
          const key=JSON.stringify([w.start,w.end,w.target,w.hard]);
          if(!groups.has(key))groups.set(key,{...w,days:[]});groups.get(key).days.push(w.day);
        }
        [...groups.values()].sort((a,b)=>a.start.localeCompare(b.start)).forEach(addRow);
        for(const [key,input]of Object.entries(delays))input.value=d.settings[key];form.revision=d.revision;
      }
      resume.disabled=form.busy||(!d.overrides.length&&!d.legacy_pause);
    };
    scheduleForm=form;
  }
  scheduleForm.sync(data);
}
async function refresh(){try{const [a,b]=await Promise.all([fetch('api/snapshot'),fetch('api/history')]);if(!a.ok||!b.ok)throw Error();const received=await a.json();if(current&&current.csrf_token!==received.csrf_token)settingsRevision=0;current=received;hist=await b.json();const d=current;document.body.classList.toggle('stale',d.stale||d.connection!=='connected');$('connection').textContent=d.connection==='connected'&&!d.stale?'HA verbonden — handmatige bediening beschikbaar':'HA nog niet verbonden of gegevens verouderd';$('updated').textContent=d.collected?'Laatste ontvangst: '+fmt(d.collected):'Nog geen metingen ontvangen';$('error').textContent=d.error||'';if(d.settings_revision>=settingsRevision){settingsRevision=d.settings_revision;renderZones(d.zones,d.building);}renderWeather(d.weather,d.stale||d.connection!=='connected',d.outdoor,d.outdoor_humidity,d.outdoor_dewpoint,d.outdoor_battery,d.outdoor_vpd);renderBuilding(d);renderControls(d.sources,d.commands);renderSchedule(d.schedule);$('price-description').textContent=(d.price_basis_confirmed?'Bevestigd elektriciteitstarief':'Bronprijzen')+' in €/kWh · Europe/Amsterdam';$('warnings').textContent=d.warnings.join(' ');$('price-table').replaceChildren();for(const p of d.prices){const tr=el('tr');tr.append(el('td',fmt(p.start)),el('td',fmt(p.end)),el('td',p.value.toFixed(4)));$('price-table').append(tr);}$('shared').replaceChildren();for(const [name,s]of [['Aanwezigheid',d.presence],['Cv-thermostaat',d.cv],['Cv-status (betekenis nog controleren)',d.cv_status],['Gas totaal, inclusief tapwater',d.gas],['CO₂ beneden',d.co2]])$('shared').append(el('div',name+': '+value(s)));$('shared').append(el('div','Gastarief: € '+d.gas_price.toLocaleString('nl-NL',{maximumFractionDigits:5})+'/m³ · geldig t/m '+d.gas_valid_until));$('history-note').textContent='Registratie sinds HC draait. Dit is meetgeschiedenis, geen voorspelling.';graphs();}catch(e){$('connection').textContent='Dashboard kan HC niet bereiken';document.body.classList.add('stale');}finally{setTimeout(refresh,15000);}}
window.addEventListener('resize',graphs);refresh();

