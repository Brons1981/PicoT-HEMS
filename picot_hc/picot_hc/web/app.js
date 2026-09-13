const $=id=>document.getElementById(id);
const fmt=(t)=>new Intl.DateTimeFormat('nl-NL',{timeZone:'Europe/Amsterdam',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(t*1000));
const labels={not_configured:'Nog niet gekoppeld',missing:'Niet gevonden',unknown:'Onbekend',unavailable:'Niet beschikbaar',invalid:'Ongeldige waarde',unit_mismatch:'Eenheid controleren'};
function value(s){return s.quality==='available'?`${typeof s.value==='number'?s.value.toLocaleString('nl-NL',{maximumFractionDigits:2}):s.value}${s.unit?' '+s.unit:''}`:labels[s.quality]||s.quality;}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function chart(id,records,key,colors){const c=$(id),w=c.clientWidth,h=Number(c.dataset.height||c.getAttribute('height')),dpr=window.devicePixelRatio||1;c.dataset.height=h;c.width=w*dpr;c.height=h*dpr;c.style.height=h+'px';const x=c.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,w,h);x.font='12px system-ui';x.fillStyle='#756d7e';const all=records.flat().filter(r=>r.value!==null);if(!all.length){x.fillText('Nog geen bruikbare meetgegevens.',20,40);return;}const t0=Math.min(...all.map(r=>r.start)),t1=Math.max(...all.map(r=>r.end??r.start))+1;let lo=Math.min(...all.map(r=>r.value)),hi=Math.max(...all.map(r=>r.value));if(key==='prices'){lo=Math.min(0,lo);hi=Math.max(0,hi);}if(hi===lo){lo-=1;hi+=1;}const X=t=>48+(t-t0)/(t1-t0)*(w-65),Y=v=>h-36-(v-lo)/(hi-lo)*(h-60);for(let i=0;i<=4;i++){let v=lo+(hi-lo)*i/4;x.fillStyle='#756d7e';x.fillText(v.toFixed(key==='prices'?2:1),2,Y(v)+4);x.strokeStyle='#ede8f2';x.beginPath();x.moveTo(45,Y(v));x.lineTo(w-10,Y(v));x.stroke();}records.forEach((series,j)=>{x.strokeStyle=colors[j];x.fillStyle=colors[j];x.lineWidth=2;let prev=null;for(const r of series){if(r.value===null){prev=null;continue;}if(key==='prices'){x.fillRect(X(r.start),Math.min(Y(r.value),Y(0)),Math.max(1,X(r.end)-X(r.start)-1),Math.max(1,Math.abs(Y(r.value)-Y(0))));}else{if(prev&&r.start-prev.start<300){x.beginPath();x.moveTo(X(prev.start),Y(prev.value));x.lineTo(X(r.start),Y(r.value));x.stroke();}x.beginPath();x.arc(X(r.start),Y(r.value),2,0,2*Math.PI);x.fill();prev=r;}}});x.fillStyle='#756d7e';x.fillText(fmt(t0),48,h-8);const last=fmt(t1);x.fillText(last,Math.max(48,w-130),h-8);}
let current=null,hist=[],settingsRevision=0;
function graphs(){if(current)chart('prices',[current.prices],'prices',['#8053ac']);const ids=['beneden','boven','badkamer'];chart('history',ids.map(id=>hist.map(r=>({start:r.time,value:(r.zones.find(z=>z.id===id)?.samples.temperature||{}).value??null}))),'temperature',['#8053ac','#367cad','#c67c32']);}
const zoneCards = new Map();
function temperatureForm(zone) {
  const form = el('form', undefined, 'temperature-settings');
  const title = el('h3', 'Temperatuur instellen');
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
      status.textContent = 'Opgeslagen. Automatische regeling is nog niet actief.';
    } catch (error) { status.textContent = error.message || 'Opslaan mislukt. Probeer opnieuw.'; }
    finally {
      form.saving = false; button.disabled = false;
      Object.values(inputs).forEach(input => input.disabled = false);
    }
  });
  return form;
}
function renderZones(zones) {
  for (const z of zones) {
    let parts = zoneCards.get(z.id);
    if (!parts) {
      const card = el('article', undefined, 'zone');
      const title = el('h2'), reading = el('div', undefined, 'reading');
      const humidity = el('div', undefined, 'sub'), facts = el('dl');
      const reason = el('p', undefined, 'reason'), form = temperatureForm(z);
      card.append(title, reading, humidity, facts, form, reason);
      $('zones').append(card);
      parts = {title, reading, humidity, facts, reason, form}; zoneCards.set(z.id, parts);
    }
    parts.title.textContent = z.name;
    parts.reading.textContent = value(z.samples.temperature);
    parts.humidity.textContent = 'Luchtvochtigheid: ' + value(z.samples.humidity);
    parts.facts.replaceChildren();
    for (const [key, val] of [['Apparaat', value(z.samples.device)], ['Vermogen', value(z.samples.power)], ['Energie', value(z.samples.energy)], ['Vochtband', z.settings.humidity_min + '–' + z.settings.humidity_max + '%']]) {
      parts.facts.append(el('dt', key), el('dd', val));
    }
    parts.reason.textContent = z.reason;
    parts.form.sync(z.settings);
  }
}
async function refresh(){try{const [a,b]=await Promise.all([fetch('api/snapshot'),fetch('api/history')]);if(!a.ok||!b.ok)throw Error();const received=await a.json();if(current&&current.csrf_token!==received.csrf_token)settingsRevision=0;current=received;hist=await b.json();const d=current;document.body.classList.toggle('stale',d.stale||d.connection!=='connected');$('connection').textContent=d.connection==='connected'&&!d.stale?'HA verbonden — alleen lezen':'HA nog niet verbonden of gegevens verouderd';$('updated').textContent=d.collected?'Laatste ontvangst: '+fmt(d.collected):'Nog geen metingen ontvangen';$('error').textContent=d.error||'';if(d.settings_revision>=settingsRevision){settingsRevision=d.settings_revision;renderZones(d.zones);}$('warnings').textContent=d.warnings.join(' ');$('price-table').replaceChildren();for(const p of d.prices){const tr=el('tr');tr.append(el('td',fmt(p.start)),el('td',fmt(p.end)),el('td',p.value.toFixed(4)));$('price-table').append(tr);}$('shared').replaceChildren();for(const [name,s]of [['Buiten',d.outdoor],['Aanwezigheid',d.presence],['Cv-thermostaat',d.cv],['Cv-status (betekenis nog controleren)',d.cv_status],['Gas totaal, inclusief tapwater',d.gas],['CO₂ beneden',d.co2]])$('shared').append(el('div',name+': '+value(s)));$('shared').append(el('div','Gastarief: € '+d.gas_price.toLocaleString('nl-NL',{maximumFractionDigits:5})+'/m³ · geldig t/m '+d.gas_valid_until));$('history-note').textContent='Registratie sinds HC draait. Dit is meetgeschiedenis, geen voorspelling.';graphs();}catch(e){$('connection').textContent='Dashboard kan HC niet bereiken';document.body.classList.add('stale');}finally{setTimeout(refresh,15000);}}
window.addEventListener('resize',graphs);refresh();
